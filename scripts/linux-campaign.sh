#!/usr/bin/env bash
# Week 8: run the full campaign (30 repetitions) on the second reference machine (bare-metal Linux).
#
#   scripts/linux-campaign.sh              # preflight checks, then `greenbench run --preset full` natively
#   scripts/linux-campaign.sh --docker     # same campaign inside the pinned Docker image
#   scripts/linux-campaign.sh --check      # preflight checks only
#
# Extra arguments after `--` are passed to `greenbench run` (e.g. -- --studies text-search --repetitions 5).
# The script never changes system settings itself: it tells you what to change and why.
set -euo pipefail

MODE=native
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker) MODE=docker ;;
    --check) MODE=check ;;
    --) shift; EXTRA=("$@"); break ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
warn=0
ok()   { printf '  [ok]   %s\n' "$1"; }
bad()  { printf '  [warn] %s\n' "$1"; warn=$((warn + 1)); }
fail() { printf '  [fail] %s\n' "$1"; exit 1; }

echo "GreenBench preflight (second reference machine)"

[[ "$(uname -s)" == "Linux" ]] || fail "this script is for Linux hosts"

if grep -qw hypervisor /proc/cpuinfo 2>/dev/null; then
  bad "running under a hypervisor: RAPL counters are usually missing or synthetic in a VM"
else
  ok "bare metal (no hypervisor flag)"
fi

pkg=$(ls -d /sys/class/powercap/intel-rapl:[0-9] 2>/dev/null | head -1 || true)
[[ -n "$pkg" ]] || fail "no /sys/class/powercap/intel-rapl:N zone: RAPL is not exposed on this machine"
if cat "$pkg/energy_uj" >/dev/null 2>&1; then
  ok "RAPL readable ($(cat "$pkg/name"))"
elif [[ "$MODE" == "docker" ]]; then
  ok "RAPL root-only; the container runs privileged and can read it"
else
  fail "RAPL is root-only. Run: sudo chmod a+r /sys/class/powercap/intel-rapl:*/energy_uj   (resets at reboot)"
fi

gov=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo unknown)
if [[ "$gov" == "performance" ]]; then
  ok "governor: performance"
else
  bad "governor is '$gov'. For a stable baseline: sudo cpupower frequency-set -g performance (it is recorded either way)"
fi

if [[ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
  [[ "$(cat /sys/devices/system/cpu/intel_pstate/no_turbo)" == "1" ]] && ok "turbo disabled" \
    || bad "turbo enabled: more run-to-run variance (echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo)"
fi

if [[ -r /sys/class/power_supply/AC/online ]] && [[ "$(cat /sys/class/power_supply/AC/online)" != "1" ]]; then
  bad "on battery: plug in AC power"
fi

load=$(cut -d' ' -f1 /proc/loadavg)
awk -v l="$load" 'BEGIN { exit !(l < 0.5) }' && ok "load average $load" \
  || bad "load average $load: close other programs (runs with background load are flagged as noisy)"

echo "$warn warning(s)."
[[ "$MODE" == "check" ]] && exit 0

if [[ "$MODE" == "docker" ]]; then
  docker build -t greenbench "$ROOT"
  docker run --rm --privileged \
    -v /sys/class/powercap:/sys/class/powercap:ro \
    -v "$ROOT/results:/data/results" \
    greenbench run --preset full --notes "machine B (Linux), docker" ${EXTRA[@]+"${EXTRA[@]}"}
else
  cd "$ROOT"
  command -v greenbench >/dev/null || fail "greenbench not installed: python3 -m venv .venv && . .venv/bin/activate && pip install -e ."
  greenbench env >/dev/null
  greenbench run --preset full --notes "machine B (Linux), native" ${EXTRA[@]+"${EXTRA[@]}"}
fi

echo
echo "Next (week 9): compare with machine A, e.g."
echo "  python -m greenbench.analysis.compare 20261104-014744-standard <new-campaign-id> --out comparison.md"
