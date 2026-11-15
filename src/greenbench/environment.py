"""Machine fingerprint stored with every campaign (documented hardware = repeatable results).

Nothing identifying is recorded: no hostname, user name or file paths, because results
are meant to be published alongside the code.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import psutil

from greenbench import __version__
from greenbench.meters import probe_meters
from greenbench.meters.model import detect_tdp


def cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    if sys.platform.startswith("linux"):
        try:
            for line in open("/proc/cpuinfo", encoding="utf-8"):
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    if sys.platform == "darwin":
        try:
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                  text=True, timeout=5).stdout.strip()
        except OSError:
            pass
    return platform.processor() or "unknown"


def _windows_power_plan() -> str | None:
    try:
        out = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"\(([^)]+)\)\s*$", out.strip())
        return m.group(1) if m else None
    except OSError:
        return None


def _read_sys(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None


def linux_cpufreq(root: Path = Path("/sys/devices/system/cpu")) -> dict | None:
    """Frequency-scaling state on Linux (the counterpart of the Windows power plan).

    The governor, the energy-performance preference and turbo all change how much energy the
    same computation costs, so they are recorded with every campaign run on Linux.
    """
    cpu0 = root / "cpu0" / "cpufreq"
    if not cpu0.exists():
        return None
    driver = _read_sys(cpu0 / "scaling_driver")
    turbo = None
    no_turbo = _read_sys(root / "intel_pstate" / "no_turbo")
    boost = _read_sys(root / "cpufreq" / "boost")
    if no_turbo is not None:
        turbo = no_turbo == "0"
    elif boost is not None:
        turbo = boost == "1"
    governors = sorted({g for g in (_read_sys(c / "cpufreq" / "scaling_governor")
                                    for c in root.glob("cpu[0-9]*")) if g})
    return {"driver": driver, "governor": governors[0] if len(governors) == 1 else ",".join(governors) or None,
            "energy_performance_preference": _read_sys(cpu0 / "energy_performance_preference"),
            "turbo": turbo,
            "intel_pstate_status": _read_sys(root / "intel_pstate" / "status")}


def _virtualization() -> dict:
    info = {"container": False, "wsl": False, "vm_guest": False}
    if os.path.exists("/.dockerenv") or os.environ.get("container"):
        info["container"] = True
    try:
        cg = open("/proc/1/cgroup", encoding="utf-8").read()
        if any(k in cg for k in ("docker", "kubepods", "containerd", "lxc")):
            info["container"] = True
    except OSError:
        pass
    if "microsoft" in platform.release().lower():
        info["wsl"] = True
    try:
        flags = open("/proc/cpuinfo", encoding="utf-8").read()
        info["vm_guest"] = " hypervisor" in flags
    except OSError:
        pass
    info["virtualized"] = any(info.values())
    return info


def _os_release() -> str:
    """platform.release() says "10" on Windows 11 before Python 3.12; builds >= 22000 are Windows 11."""
    release = platform.release()
    if platform.system() == "Windows" and release == "10":
        try:
            if int(platform.version().split(".")[2]) >= 22000:
                return "11"
        except (IndexError, ValueError):
            pass
    return release


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def fingerprint(include_meters: bool = True) -> dict:
    name = cpu_name()
    tdp, tdp_source = detect_tdp(name)
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    freq = psutil.cpu_freq()
    cpufreq = linux_cpufreq() if sys.platform.startswith("linux") else None
    env = {
        "greenbench": __version__,
        "os": {"system": platform.system(), "release": _os_release(), "version": platform.version(),
               "machine": platform.machine()},
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation()},
        "cpu": {"name": name, "physical_cores": psutil.cpu_count(logical=False),
                "logical_cpus": psutil.cpu_count(logical=True),
                "max_mhz": round(freq.max) if freq and freq.max else None,
                "tdp_w": tdp, "tdp_source": tdp_source},
        "memory_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "power": {"ac_plugged": None if battery is None else bool(battery.power_plugged),
                  "battery_percent": None if battery is None else round(battery.percent),
                  "plan": _windows_power_plan() if sys.platform == "win32"
                  else (cpufreq or {}).get("governor"),
                  "cpufreq": cpufreq},
        "virtualization": _virtualization(),
        "libraries": {p: _version(p) for p in ("numpy", "pyarrow", "scipy", "psutil")},
    }
    if include_meters:
        env["meters"] = probe_meters()
    return env
