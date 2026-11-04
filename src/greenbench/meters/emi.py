"""Windows Energy Meter Interface (EMI) reader.

Windows publishes on-chip energy counters to user mode through devices that implement
GUID_DEVICE_ENERGY_METER. On Intel and AMD machines the "Microsoft PPM" provider exposes
the RAPL domains (RAPL_Package0_PKG, per-core RAPL_Package0_CoreN_CORE, PP0/PP1/DRAM on
Intel). Those channels refresh on every read, so they can time sub-second regions.
Some platforms add vendor meters (e.g. AMD's AMDI0100 socket/APU rails) that refresh
about once per second; they are exposed as slow domains, usable for idle baselines only.

No administrator rights or drivers are needed: only read-only IOCTLs are issued.
Units are picowatt-hours (1 pWh = 3.6e-9 J); timestamps are in 100 ns units.
"""

from __future__ import annotations

import re
import struct
import sys
import time

from greenbench.meters.base import EnergyMeter, MeterUnavailable, Reading

GUID = "{45bd8344-7ed6-49cf-a440-c276c933b053}"
IOCTL_EMI_GET_VERSION = 0x224000
IOCTL_EMI_GET_METADATA_SIZE = 0x224004
IOCTL_EMI_GET_METADATA = 0x224008
IOCTL_EMI_GET_MEASUREMENT = 0x22400C
PWH_TO_J = 3.6e-9

# Channel name -> GreenBench domain. Anything matching RAPL_* refreshes on read.
_FAST_PATTERNS = [
    (re.compile(r"^RAPL_Package\d+_PKG$"), "pkg"),
    (re.compile(r"^RAPL_Package\d+_Core\d+_CORE$"), "cores"),
    (re.compile(r"^RAPL_Package\d+_PP0$"), "cores"),
    (re.compile(r"^RAPL_Package\d+_PP1$"), "gpu"),
    (re.compile(r"^RAPL_Package\d+_DRAM$"), "dram"),
    (re.compile(r"^RAPL_Package\d+_PSYS$"), "psys"),
]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class _Device:
    def __init__(self, k32, wt, ctypes, path: str):
        self._k32, self._wt, self._ctypes = k32, wt, ctypes
        self.path = path
        h = k32.CreateFileW(path, 0x80000000, 0x1 | 0x2, None, 3, 0, None)  # GENERIC_READ, OPEN_EXISTING
        if h in (None, wt.HANDLE(-1).value):
            raise OSError(ctypes.get_last_error(), f"cannot open {path}")
        self.handle = h
        self.version = struct.unpack("<H", self._ioctl(IOCTL_EMI_GET_VERSION, 2))[0]
        size = struct.unpack("<I", self._ioctl(IOCTL_EMI_GET_METADATA_SIZE, 4))[0]
        meta = self._ioctl(IOCTL_EMI_GET_METADATA, size)
        if self.version >= 2:
            self.oem = meta[0:32].decode("utf-16-le").rstrip("\x00")
            self.model = meta[32:64].decode("utf-16-le").rstrip("\x00")
            count = struct.unpack("<H", meta[66:68])[0]
            off, names = 68, []
            for _ in range(count):
                _unit, nsize = struct.unpack("<IH", meta[off:off + 6])
                names.append(meta[off + 6:off + 6 + nsize].decode("utf-16-le").rstrip("\x00"))
                off += 6 + nsize
            self.channels = names
        else:
            self.oem = meta[4:36].decode("utf-16-le").rstrip("\x00")
            self.model = meta[36:68].decode("utf-16-le").rstrip("\x00")
            nsize = struct.unpack("<H", meta[70:72])[0]
            self.channels = [meta[72:72 + nsize].decode("utf-16-le").rstrip("\x00")]
        self._out = ctypes.create_string_buffer(16 * len(self.channels))
        self._ret = wt.DWORD(0)

    def _ioctl(self, code: int, size: int) -> bytes:
        buf = self._ctypes.create_string_buffer(size)
        ret = self._wt.DWORD(0)
        ok = self._k32.DeviceIoControl(self.handle, code, None, 0, buf, size, self._ctypes.byref(ret), None)
        if not ok:
            raise OSError(self._ctypes.get_last_error(), "EMI ioctl failed")
        return buf.raw[:ret.value]

    def measure(self) -> list[tuple[int, int]]:
        """(energy_pWh, time_100ns) per channel."""
        n = 16 * len(self.channels)
        ok = self._k32.DeviceIoControl(self.handle, IOCTL_EMI_GET_MEASUREMENT, None, 0, self._out, n,
                                       self._ctypes.byref(self._ret), None)
        if not ok:
            raise OSError(self._ctypes.get_last_error(), "EMI measurement failed")
        raw = self._out.raw
        return [struct.unpack_from("<QQ", raw, 16 * i) for i in range(len(self.channels))]

    def close(self) -> None:
        self._k32.CloseHandle(self.handle)


def _load_kernel32():
    import ctypes
    import ctypes.wintypes as wt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    k32.DeviceIoControl.restype = wt.BOOL
    k32.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                    ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    return k32, wt, ctypes


def _device_paths() -> list[str]:
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SYSTEM\CurrentControlSet\Control\DeviceClasses" + "\\" + GUID)
    except OSError:
        return []
    count = winreg.QueryInfoKey(key)[0]
    # Registry names look like "##?#ACPI#...#{guid}"; the device path is "\\?\ACPI#...#{guid}".
    return ["\\\\?\\" + winreg.EnumKey(key, i)[4:] for i in range(count)]


class EmiMeter(EnergyMeter):
    name = "emi"
    kind = "hardware"

    def __init__(self, include_slow: bool = False):
        if sys.platform != "win32":
            raise MeterUnavailable("EMI is a Windows interface")
        k32, wt, ctypes = _load_kernel32()
        devices = []
        for path in _device_paths():
            try:
                devices.append(_Device(k32, wt, ctypes, path))
            except OSError:
                continue
        if not devices:
            raise MeterUnavailable("no readable Energy Meter Interface device")
        self._fast: list[tuple[_Device, list[str]]] = []
        self._slow: list[tuple[_Device, list[str]]] = []
        self.channels: dict[str, str] = {}
        for dev in devices:
            mapped = []
            for ch in dev.channels:
                dom = next((d for p, d in _FAST_PATTERNS if p.match(ch)), None)
                mapped.append(dom)
                if dom:
                    self.channels[ch] = dom
            if any(mapped):
                self._fast.append((dev, mapped))
            elif include_slow:
                slow_names = ["slow_" + _slug(ch) for ch in dev.channels]
                self._slow.append((dev, slow_names))
                for ch, dom in zip(dev.channels, slow_names):
                    self.channels[ch] = dom
            else:
                dev.close()
        doms = sorted({d for _, m in self._fast for d in m if d})
        if "pkg" not in doms:
            raise MeterUnavailable("EMI devices found, but no RAPL package channel")
        self.domains = tuple(["pkg"] + [d for d in doms if d != "pkg"])
        self.slow_domains = tuple(sorted({d for _, m in self._slow for d in m}))
        self.provider = ", ".join(sorted({f"{d.oem}/{d.model}".strip("/") for d, _ in self._fast}))

    def read(self) -> Reading:
        t = time.perf_counter()
        energy: dict[str, float] = {d: 0.0 for d in self.domains}
        for dev, mapped in self._fast:
            for (e, _ts), dom in zip(dev.measure(), mapped):
                if dom:
                    energy[dom] += e * PWH_TO_J
        for dev, names in self._slow:
            for (e, _ts), dom in zip(dev.measure(), names):
                energy[dom] = e * PWH_TO_J
        return Reading(t, energy)

    def power_w(self, seconds: float = 1.0) -> dict[str, float]:
        a = self.read()
        time.sleep(seconds)
        b = self.read()
        dt = b.t - a.t
        return {d: (b.energy_j[d] - a.energy_j[d]) / dt for d in b.energy_j}

    def describe(self) -> dict:
        info = super().describe()
        info.update({
            "provider": self.provider,
            "interface": "Windows Energy Meter Interface (EMI)",
            "channels": self.channels,
            "slow_domains": list(self.slow_domains),
        })
        return info

    def close(self) -> None:
        for dev, _ in self._fast + self._slow:
            dev.close()
