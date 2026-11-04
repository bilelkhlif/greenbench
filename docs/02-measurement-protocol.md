# Measurement protocol

*Deliverable 2, weeks 4–6. Documented and automated: every step below is implemented in the `greenbench` package and runs with one command.*

```bash
greenbench run --preset standard      # the week-7 campaign: 5 studies, 29 configurations, 348 runs
greenbench report latest              # Markdown report with every statistic
greenbench serve                      # dashboard on http://127.0.0.1:8000
```

## 1. Principle

For one task, every variant must produce **the same result** (checked, not assumed). Each variant is run **many times, in isolation, in random order**, while **hardware energy counters** are read around the measured region. Differences are reported as **ratios of medians with confidence intervals, significance tests and effect sizes**, never as single averages.

## 2. What is recorded for every run

| Quantity | How | Unit |
|---|---|---|
| Package energy | RAPL package counter, read before and after each phase | J |
| Core energy | Sum of the per-core RAPL counters (when exposed) | J |
| Dynamic energy | Package energy − idle power × duration (the primary metric) | J |
| Duration | `perf_counter` around the measured region | s |
| CPU time | User + system time of the run process, all threads | s |
| Peak memory | Peak working set (Windows) / max RSS (Linux) of the run process | MB |
| Phase breakdown | Energy, time and CPU time of each phase (load, build/join, query/aggregate) | J, s |
| Model estimate | TDP / logical CPUs × CPU time + 0.375 W/GB × peak memory × duration | J |
| Background load | System-wide busy CPU time minus the run's own CPU time | CPU-s |
| Result checksum | SHA-256 of the canonical result arrays (first 16 hex digits) | – |
| Accuracy | Mean, 95th-percentile and maximum relative error vs the reference (approximate variants) | % |

## 3. Energy meters

GreenBench picks the first available hardware meter and always records the software model next to it.

**Windows: Energy Meter Interface (EMI).** Windows publishes energy counters to user mode through devices implementing `GUID_DEVICE_ENERGY_METER` (`{45bd8344-7ed6-49cf-a440-c276c933b053}`). GreenBench enumerates them from the registry, opens them read-only and issues `IOCTL_EMI_GET_MEASUREMENT` (energy in picowatt-hours, timestamps in 100 ns). Channels named `RAPL_Package*_PKG` map to the *package* domain, `RAPL_Package*_Core*_CORE` / `PP0` to *cores*, `DRAM` to *dram*. On the reference laptop (AMD Ryzen 7 6800HS) we measured:

| Device | Channels | Refresh | Read cost | Use |
|---|---|---|---|---|
| Microsoft PPM | `RAPL_Package0_PKG`, `RAPL_Package0_Core0..7_CORE` | on every read | ≈ 8 µs | per-run and per-phase energy |
| AMD `AMDI0100` | VDDCR_VDD, VDDCR_SOC, socket power, APU power | ≈ 1 s | ≈ 7 µs | idle baselines only |

No administrator rights, no driver installation.

**Linux: `powercap`.** `/sys/class/powercap/intel-rapl:*/energy_uj` (also used by AMD Zen since Linux 5.8). Counters wrap at `max_energy_range_uj`; wrap-around is corrected on every read. Since 2020 the files are root-readable only: run as root, grant read access (`sudo chmod a+r /sys/class/powercap/intel-rapl:*/energy_uj`), or run the Docker image with the directory mounted.

**Software model.** The CodeCarbon-style estimate in the table above. The TDP comes from the CPU name (35 W for the Ryzen 7 6800HS) or the `GREENBENCH_TDP_W` variable. It is recorded on every run so that its agreement with the hardware counter can be measured; it is never presented as a measurement.

## 4. Data

A seeded generator (seed 20261104) produces five tables modelling several sources: `customers` (CRM database), `orders` (API + file exports + database, with 3 % orphan foreign keys), `documents` (support tickets with a Zipf vocabulary), `events` (one day of time-ordered IoT/click events) and `kv` (a key-value store). Three scales exist; the campaign uses **medium**:

| Table | Rows (medium) | Parquet + Snappy |
|---|---|---|
| orders | 2,000,000 | 35 MB |
| customers | 200,000 | 2 MB |
| documents | 50,000 | 5 MB |
| events | 2,000,000 | 14 MB |
| kv | 2,000,000 | 29 MB |

Seven storage options are derived from the canonical copy: CSV, CSV + Zstd, JSON lines, JSON lines + Zstd, Parquet uncompressed, Parquet + Snappy (the default) and Parquet + Zstd. All are read with Apache Arrow's own readers, so the reader library stays constant and only the on-disk representation changes. Reading is single-threaded unless the `threads` knob is above 1.

## 5. Workloads and correctness

| Workload | Variants | Reference |
|---|---|---|
| Join: revenue per country = orders ⋈ customers, group by country | hash join (open addressing), sort-merge join; partitioned versions when threads > 1 | hash join |
| Text search: 1–2 term AND queries | regex full scan, inverted index | inverted index |
| Streaming: 5-min windows sliding every minute, per region: count, sum, distinct users | batch recompute, incremental panes, incremental + HyperLogLog (p = 10), 10 % user sample | incremental |
| Indexing: point lookups (80 % hits) + range queries | full scan, bulk-loaded B+-tree (fanout 64), hash index | B+-tree |

Before a campaign, the reference variant runs once per dataset (and per query count when it changes the answer); its result is stored. After every measured run, the worker compares its checksum with the reference. **An exact variant that does not reproduce the reference is marked invalid and excluded.** Approximate variants are scored on their relative error instead. Unit tests check that every exact variant agrees with the reference on every storage format and thread count.

## 6. One run

Each run is a fresh Python process (`python -m greenbench.protocol.worker`) receiving a JSON specification:

1. **Outside measurement:** import modules, set Arrow's thread pools to the `threads` knob, open the meter, load query sets, collect garbage, read the resident memory and the system-wide CPU times.
2. **Measured region:** the workload runs its phases (`load` → `build`/`join` → `query`/`aggregate`). At every phase boundary the context records wall time, the meter reading and the process CPU time.
3. **Outside measurement again:** read peak memory and system CPU times, compute the model estimate, the checksum and the accuracy, print one JSON record.

The parent appends the record to `runs.jsonl`. Environment variables `PYTHONHASHSEED=0` and single-threaded BLAS settings keep the interpreter deterministic.

## 7. A campaign

| Step | Standard preset |
|---|---|
| Fingerprint: CPU, cores, memory, OS, Python and library versions, power plan, AC/battery, virtualisation, meters | always |
| Prepare datasets, storage copies, query sets and reference results (never measured) | always |
| Idle baseline: package power over 1-second windows with nothing running | 10 s |
| Warm-up block: every configuration runs W times; records kept but excluded | W = 2 |
| Measured rounds: every configuration once per round, in a new random order (seeded) | R = 10 |
| Cool-down between runs | 0.5 s |
| Idle baseline again | every 60 runs (5 s) and at the end (10 s) |
| Analysis and report | at the end |

Configurations shared by two studies (hash join, 1 thread, Parquet + Snappy) are measured once and reused. Configurations that would take minutes per run are skipped and listed as such (full scans beyond 2,000 index queries). A campaign can be stopped between runs; partial results stay valid.

## 8. Validity checks

* **Invalid result:** checksum mismatch, so the run is excluded and counted.
* **Errors:** a crashed or timed-out run (10 minutes) is recorded with its error and excluded.
* **Noisy run:** other processes used at least one core more than during the idle baseline, and more than 50 ms of CPU in total (Windows CPU counters advance in 15.6 ms ticks). Noisy runs are counted and reported; they are kept, because removing them after the fact would bias the sample.
* **Idle drift:** the spread of the idle measurements across the campaign is reported.
* **Virtualisation:** containers, WSL and hypervisor guests are detected and recorded.

## 9. Statistical analysis

For every configuration and metric: median, percentile-bootstrap 95 % CI of the median (4,000 resamples), mean, standard deviation, coefficient of variation, quartiles.

Each study compares configurations with its baseline, within groups that share a query count:

* **Effect:** ratio of medians (variant / baseline) with a bootstrap 95 % CI, shown as a percentage change, for energy and for duration.
* **Significance:** two-sided Mann–Whitney U; p-values corrected with Holm–Bonferroni across all comparisons of the study; significant when the corrected p < 0.05.
* **Effect size:** Cliff's δ with the Romano et al. thresholds (negligible / small / medium / large).
* **Pareto front:** configurations that no other configuration beats on both median energy and median duration.
* **Recommendation:** the exact configuration with the lowest median energy, stated only if significantly better than the baseline, in the form *"X cuts energy by N % versus B, for a Y % latency cost"*. The best approximate configuration is reported separately, with its error.
* **Break-even (index studies):** queries needed for an index to repay its extra build energy = Δ build energy / (scan energy per query − index energy per query), using per-query costs measured at the largest query count.
* **Cross-check:** Spearman and Pearson correlation between the model estimate and the measured dynamic energy over all runs, and their median ratio.

## 10. Reproducing a campaign

```bash
python -m venv .venv && .venv\Scripts\activate      # Linux/macOS: source .venv/bin/activate
pip install -e .[dev]
greenbench env          # fingerprint and meter availability
greenbench meter        # live package power, to see the meter respond
greenbench run --preset quick       # a few minutes
greenbench run --preset standard    # about 20 minutes on the reference laptop
```

On Linux, the Docker image pins the environment: `docker build -t greenbench .` then `docker run --privileged -v /sys/class/powercap:/sys/class/powercap:ro greenbench run --preset standard`. Inside a VM or on Docker Desktop (Windows, macOS) no RAPL counter is visible and GreenBench falls back to the software model, which it says explicitly.

## 11. Outputs

Each campaign lives in `results/<campaign-id>/`:

| File | Content |
|---|---|
| `campaign.json` | configuration, environment fingerprint, meter description, studies, configurations, dataset sizes, idle measurements |
| `runs.jsonl` | one JSON record per run (warm-ups included, flagged) |
| `status.json` | live progress |
| `analysis.json` | every statistic shown in the dashboard |
| `report.md` | the human-readable report |

## 12. Known limitations

* One reference machine so far; a Linux machine is planned for weeks 8–9.
* The package domain excludes DRAM, storage and the rest of the platform.
* AMD RAPL values are model-based on-chip estimates: relative differences between variants are more trustworthy than absolute joules.
* The idle baseline is a single median per campaign; drift is reported, not modelled.
* Windows CPU-time counters tick every 15.6 ms, so the software model and the background-load check are coarse for very short runs. Medium-scale runs last 0.2–30 s.
