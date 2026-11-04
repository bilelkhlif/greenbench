# State of the art: energy benchmarking of data-processing software

*Deliverable 1, weeks 1–3. GreenBench AI · SUP'COM INDP3 SIA · Bajar Omar, Khlif Bilel. Supervised by Mohamed Ayadi & Nejib Boubaker (SUP'COM) and Soumaya Bouchemi (AIVRA / GET Wireless).*

## 1. Why measure the energy of data processing

Data centres used about 415 TWh of electricity in 2024, roughly 1.5 % of global consumption, and the International Energy Agency's base case projects about 945 TWh by 2030 [IEA 2025]. A large share of that work is ordinary data processing: joins, searches, aggregations, index lookups. Engineering teams already optimise these tasks for latency and correctness, but energy is rarely measured and almost never compared across implementation choices.

Two implementations can return exactly the same result and still consume very different amounts of energy. Making that difference visible requires a measurement method that is accurate enough, repeatable, and statistically sound. The Green Software Foundation's Software Carbon Intensity specification, standardised as ISO/IEC 21031:2024, defines how to *report* the carbon intensity of software; it does not tell a team which of two algorithms to choose. GreenBench targets that gap: controlled, reusable comparisons of implementation choices for the same task.

## 2. How software energy is measured

### 2.1 External power meters

A wall-plug or DC-side power meter measures the whole system and is the reference used by industrial benchmarks such as SPECpower_ssj2008 and the TPC-Energy specification. It captures everything (CPU, memory, storage, fans, power-supply losses), but it cannot attribute energy to a process, typically samples at 1 Hz or slower, and needs extra hardware for each machine. It is the right tool for validating other meters, not for comparing sub-second algorithm variants on several machines.

### 2.2 On-chip energy counters (RAPL)

Since the Sandy Bridge generation, Intel processors expose *Running Average Power Limit* (RAPL) energy counters through model-specific registers [Intel SDM, vol. 3B; David et al. 2010]. The usual domains are the package, the cores (PP0), the uncore or integrated GPU (PP1), DRAM, and on recent parts the whole platform (PSYS). The counters update roughly every millisecond and are 32 bits wide, so they wrap and must be read often enough [Hähnel et al. 2012].

Accuracy depends on the generation. On early Intel parts RAPL was a model; from Haswell on, package values come from measurements of the integrated voltage regulators and track external meters closely [Hackenberg et al. 2015; Khan et al. 2018]. DRAM values have been validated separately [Desrochers et al. 2016]. AMD Zen processors implement the same interface, but studies found that their values are produced by an on-chip power model rather than measured, which preserves relative differences better than absolute joules [Schöne et al. 2021].

Access is the practical difficulty:

* **Linux** exposes RAPL through the `powercap` sysfs interface. Since the PLATYPUS power side-channel attack [Lipp et al. 2021], `energy_uj` is readable by root only, so tools need elevated rights or a deliberate permission change.
* **Virtual machines** usually do not expose RAPL at all (Windows Subsystem for Linux 2 and most cloud VMs included), and containers see the host's system-wide counters.
* **Windows** has no `powercap`, but it publishes energy counters to user mode through the *Energy Meter Interface* (EMI), a documented driver interface (`emi.h`, `IOCTL_EMI_GET_MEASUREMENT`). On the AMD Ryzen 7 6800HS laptop used in this project, the "Microsoft PPM" provider exposes `RAPL_Package0_PKG` and one `RAPL_Package0_CoreN_CORE` channel per core. We verified that these channels refresh on every read (about 8 µs per read, no administrator rights), while a second, vendor-specific meter (AMD socket and APU rails) refreshes only once per second. To our knowledge, mainstream measurement tools do not use EMI; it is what makes hardware measurements possible on an ordinary Windows laptop.

RAPL covers the processor package, not the whole machine: storage, network, screen and power-supply losses are outside it. For CPU-bound data processing on one machine, the package domain is where the variants differ, which is why benchmarking studies commonly rely on it [Pereira et al. 2017; 2021].

### 2.3 Software estimators

When no counter is available, tools estimate energy from activity:

| Tool | Source of the number | Granularity | Notes |
|---|---|---|---|
| CodeCarbon | RAPL on Linux; otherwise TDP × CPU load; RAM by a fixed heuristic (historically 3 W per 8 GB) | seconds (default 15 s interval) | Carbon accounting for ML jobs; coarse for short runs |
| Scaphandre | RAPL, split per process by CPU-time share | ~1 s | Prometheus exporter; Windows needs a kernel driver |
| PowerJoular / JoularJX | RAPL (Linux), vendor tools for GPUs, models for Raspberry Pi | 1 s | Per-process and per-method (Java) attribution [Noureddine 2022] |
| PowerAPI / SmartWatts | RAPL + performance counters, self-calibrating model | sub-second | Per-container estimates [Fieni et al. 2020] |
| Kepler | RAPL or trained models, eBPF activity | seconds | Kubernetes pods |
| Green Algorithms | Calculator: hardware power × runtime × usage | per job | Order-of-magnitude reporting [Lannelongue et al. 2021] |

An experimental comparison of software power meters found that tools built on RAPL agree with each other far better than model-only estimators, whose outputs can diverge substantially for the same workload [Jay et al. 2023]. For comparing variants, a model that is proportional to CPU time also hides the effects we want to see: parallel efficiency, frequency scaling and memory-bound phases change power, not just time.

### 2.4 What we retain

* **Primary measurement:** hardware counters. RAPL through EMI on Windows and through `powercap` on Linux, read at the boundaries of each measured phase.
* **Cross-check:** a CodeCarbon-style software model (TDP share × CPU time + DRAM heuristic) recorded for every run, so the agreement between model and hardware becomes a result in itself rather than an assumption.
* **Honesty about scope:** package energy only; on AMD, trust relative differences more than absolute joules.

## 3. Measurement biases and how to avoid them

Benchmarking is notoriously sensitive to details that look irrelevant: changing the size of the environment variables or the link order can move results by more than the effect being studied [Mytkowicz et al. 2009]. Energy adds its own failure modes.

| Bias | Mechanism | Counter-measure in the literature | GreenBench choice |
|---|---|---|---|
| Warm-up | Cold caches, page cache, lazy imports, frequency ramp-up | Discard initial iterations [Georges et al. 2007] | 2 warm-up runs per configuration, discarded |
| Order and drift | Thermal state, turbo budgets and background activity drift over a campaign | Randomise and interleave [Kalibera & Jones 2013] | A fresh random order in every round |
| Shared state | Allocator state, memory fragmentation, caches from previous runs | Process isolation | One new process per run |
| Background load | System-wide counters see every process | Quiet machine, idle baseline subtraction | Idle baseline at start, every 60 runs and at the end; background CPU measured per run |
| Static power | Idle power accrues for as long as a run lasts | Report dynamic (idle-subtracted) energy alongside total | Both reported; dynamic is the primary metric |
| Virtualisation | Counters absent or shared in VMs and containers | Bare metal, or flag the setting | Detected and recorded; local runs are bare metal |
| Short regions | Counter update interval, read overhead, timer resolution | Repeat or batch short code paths [Hähnel et al. 2012] | Medium-scale data (runs of 0.2–30 s), 10+ repetitions |
| Wrong result | A fast variant that silently computes something else | Validate outputs | Checksum against a reference result for every run |
| Power configuration | Power plan, AC/battery, turbo settings | Document the hardware and settings | Fingerprint stored with every campaign |

## 4. Statistics that hold

Benchmark samples are small, often skewed, and sometimes bimodal (a background task, a frequency step). The literature therefore recommends reporting variability and confidence intervals rather than single averages [Georges et al. 2007; Kalibera & Jones 2013]:

* **Location and uncertainty:** the median with a percentile-bootstrap 95 % confidence interval [Efron & Tibshirani 1993]; the ratio of medians between two variants gets its own bootstrap interval.
* **Significance:** the Mann–Whitney U test [Mann & Whitney 1947], which assumes neither normality nor equal variances, with the Holm–Bonferroni correction across the comparisons of a study [Holm 1979].
* **Effect size:** Cliff's δ [Cliff 1993], the probability that one variant uses less energy than the other minus the reverse, graded with the thresholds of Romano et al. (2006): negligible < 0.147, small < 0.33, medium < 0.474, large otherwise. A tiny but significant difference is not a recommendation.
* **Trade-offs:** energy against time on one chart, with the Pareto front; never a dual-axis chart.

## 5. What is known about data-processing energy

* **Database systems.** Energy efficiency was proposed as a first-class design goal for data management [Harizopoulos et al. 2009; Lang & Patel 2009]. On a single-node database server, Tsirogiannis et al. (2010) found that the most energy-efficient configuration was typically the highest-performing one, while Xu et al. (2010) showed that power-performance trade-offs exist across query plans. Whether "fastest equals greenest" holds is therefore an empirical question per task.
* **Languages.** Comparing 27 programming languages on the same benchmarks, Pereira et al. (2017; 2021) showed that energy, time and memory are related but that the fastest language is not always the most energy-efficient.
* **Joins.** Sort-based and hash-based joins have been compared repeatedly on multi-core CPUs, with conclusions that depend on hardware, data size and implementation effort [Kim et al. 2009; Blanas et al. 2011; Balkesen et al. 2013]. Energy was not the target of those studies.
* **Text search.** Inverted indexes are the standard structure for keyword search [Zobel & Moffat 2006]; their cost is front-loaded in the build, which a full scan avoids.
* **Streaming aggregation.** Sliding windows can be evaluated incrementally from per-slice partial aggregates, the *panes* technique [Li et al. 2005], generalised by Tangwongsan et al. (2015). Distinct counts can be approximated with mergeable HyperLogLog sketches [Flajolet et al. 2007], trading accuracy for memory and work.
* **Indexing.** B-trees [Bayer & McCreight 1972; Comer 1979] support point and range queries; hash indexes answer point lookups in expected constant time but cannot answer ranges.
* **Storage formats.** Columnar formats with lightweight compression reduce the bytes read and can speed up execution [Abadi et al. 2006]; Apache Parquet with Snappy or Zstandard [RFC 8878] is the de facto standard, CSV and JSON lines remain common interchange formats.

## 6. Gap and positioning

System-level energy benchmarks (SPECpower, TPC-Energy) rate whole machines; carbon calculators and trackers report the footprint of a job; academic studies compare languages or database configurations. None gives a data team a reusable way to answer *"for this task, which implementation should we use, and what does it cost in latency?"* with measured energy and sound statistics. GreenBench provides:

1. a protocol (isolation, warm-ups, randomisation, idle baseline, result validation) automated end to end;
2. hardware measurements on machines teams actually have, including Windows laptops through EMI;
3. recommendations stated with their uncertainty and their cost, in the form *"X cuts energy by N % for a Y % latency cost"*.

## 7. Workload selection

The proposal asks for 4–5 representative multi-source tasks. We selected four, each with variants that must return the same result (or, for approximate variants, a measured error):

| Workload | Variants | Knobs | Expected trade-off |
|---|---|---|---|
| Large-volume join (orders ⋈ customers, then group-by) | hash join, sort-merge join | threads 1–8, storage format × compression | Parallel speed-up vs extra energy from partitioning and contention |
| Text search (1–2 term AND queries over tickets) | regular-expression full scan, inverted index | number of queries 1–100 | Index build cost vs per-query cost: a break-even point |
| Streaming aggregation (5-min windows sliding every minute) | batch recompute, incremental panes, HyperLogLog, 10 % sampling | storage | Exact vs approximate; redundant vs incremental work |
| Indexing (point and range lookups) | full scan, B+-tree, hash index | number of queries 1,000–100,000 | Build cost vs query cost; ranges defeat hash indexes |

Storage format (CSV, JSON lines, Parquet) and compression (none, Snappy, Zstandard) form a cross-cutting study on the join, whose inputs are the largest. Data come from a seeded generator that models several sources (CRM database, API exports, event stream, key-value store), so any machine benchmarks byte-identical inputs.

## References

* Abadi, D., Madden, S., & Ferreira, M. (2006). Integrating compression and execution in column-oriented database systems. *SIGMOD*.
* Balkesen, C., Alonso, G., Teubner, J., & Özsu, M. T. (2013). Multi-core, main-memory joins: Sort vs. hash revisited. *PVLDB* 7(1).
* Bayer, R., & McCreight, E. (1972). Organization and maintenance of large ordered indexes. *Acta Informatica* 1.
* Blanas, S., Li, Y., & Patel, J. M. (2011). Design and evaluation of main memory hash join algorithms for multi-core CPUs. *SIGMOD*.
* Cliff, N. (1993). Dominance statistics: Ordinal analyses to answer ordinal questions. *Psychological Bulletin* 114(3).
* Collet, Y., & Kucherawy, M. (2021). *Zstandard Compression and the 'application/zstd' Media Type*. RFC 8878.
* Comer, D. (1979). The ubiquitous B-tree. *ACM Computing Surveys* 11(2).
* David, H., Gorbatov, E., Hanebutte, U. R., Khanna, R., & Le, C. (2010). RAPL: Memory power estimation and capping. *ISLPED*.
* Desrochers, S., Paradis, C., & Weaver, V. M. (2016). A validation of DRAM RAPL power measurements. *MEMSYS*.
* Efron, B., & Tibshirani, R. J. (1993). *An Introduction to the Bootstrap*. Chapman & Hall.
* Fieni, G., Rouvoy, R., & Seinturier, L. (2020). SmartWatts: Self-calibrating software-defined power meter for containers. *CCGrid*.
* Flajolet, P., Fusy, É., Gandouet, O., & Meunier, F. (2007). HyperLogLog: The analysis of a near-optimal cardinality estimation algorithm. *AofA*.
* Georges, A., Buytaert, D., & Eeckhout, L. (2007). Statistically rigorous Java performance evaluation. *OOPSLA*.
* Hackenberg, D., Schöne, R., Ilsche, T., Molka, D., Schuchart, J., & Geyer, R. (2015). An energy efficiency feature survey of the Intel Haswell processor. *IPDPS Workshops*.
* Hähnel, M., Döbel, B., Völp, M., & Härtig, H. (2012). Measuring energy consumption for short code paths using RAPL. *ACM SIGMETRICS Performance Evaluation Review* 40(3).
* Harizopoulos, S., Shah, M. A., Meza, J., & Ranganathan, P. (2009). Energy efficiency: The new holy grail of data management systems research. *CIDR*.
* Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics* 6(2).
* IEA (2025). *Energy and AI*. International Energy Agency.
* Intel. *Intel 64 and IA-32 Architectures Software Developer's Manual*, Volume 3B (power and thermal management).
* ISO/IEC 21031:2024. *Information technology: Software Carbon Intensity (SCI) specification*.
* Jay, M., Ostapenco, V., Lefèvre, L., Trystram, D., Orgerie, A.-C., & Fichel, B. (2023). An experimental comparison of software-based power meters: Focus on CPU and GPU. *CCGrid*.
* Kalibera, T., & Jones, R. (2013). Rigorous benchmarking in reasonable time. *ISMM*.
* Khan, K. N., Hirki, M., Niemi, T., Nurminen, J. K., & Ou, Z. (2018). RAPL in action: Experiences in using RAPL for power measurements. *ACM TOMPECS* 3(2).
* Kim, C., Kaldewey, T., Lee, V. W., Sedlar, E., Nguyen, A. D., Satish, N., Chhugani, J., Di Blas, A., & Dubey, P. (2009). Sort vs. hash revisited: Fast join implementation on modern multi-core CPUs. *PVLDB* 2(2).
* Lang, W., & Patel, J. M. (2009). Towards eco-friendly database management systems. *CIDR*.
* Lannelongue, L., Grealey, J., & Inouye, M. (2021). Green Algorithms: Quantifying the carbon footprint of computation. *Advanced Science* 8(12).
* Li, J., Maier, D., Tufte, K., Papadimos, V., & Tucker, P. A. (2005). No pane, no gain: Efficient evaluation of sliding-window aggregates over data streams. *SIGMOD Record* 34(1).
* Lipp, M., Kogler, A., Oswald, D., Schwarz, M., Easdon, C., Canella, C., & Gruss, D. (2021). PLATYPUS: Software-based power side-channel attacks on x86. *IEEE Symposium on Security and Privacy*.
* Mann, H. B., & Whitney, D. R. (1947). On a test of whether one of two random variables is stochastically larger than the other. *Annals of Mathematical Statistics* 18(1).
* Microsoft. *Energy Meter Interface* (Windows Driver Kit documentation, `emi.h`).
* Mytkowicz, T., Diwan, A., Hauswirth, M., & Sweeney, P. F. (2009). Producing wrong data without doing anything obviously wrong! *ASPLOS*.
* Noureddine, A. (2022). PowerJoular and JoularJX: Multi-platform software power monitoring tools. *International Conference on Intelligent Environments*.
* Pereira, R., Couto, M., Ribeiro, F., Rua, R., Cunha, J., Fernandes, J. P., & Saraiva, J. (2017). Energy efficiency across programming languages: How do energy, time, and memory relate? *SLE*.
* Pereira, R., Couto, M., Ribeiro, F., Rua, R., Cunha, J., Fernandes, J. P., & Saraiva, J. (2021). Ranking programming languages by energy efficiency. *Science of Computer Programming* 205.
* Romano, J., Kromrey, J. D., Coraggio, J., & Skowronek, J. (2006). Appropriate statistics for ordinal level data. *Annual Meeting of the Florida Association of Institutional Research*.
* Schöne, R., Ilsche, T., Bielert, M., Velten, M., Schmidl, M., & Hackenberg, D. (2021). Energy efficiency aspects of the AMD Zen 2 architecture. *IEEE CLUSTER*.
* Tangwongsan, K., Hirzel, M., Schneider, S., & Wu, K.-L. (2015). General incremental sliding-window aggregation. *PVLDB* 8(7).
* Tsirogiannis, D., Harizopoulos, S., & Shah, M. A. (2010). Analyzing the energy efficiency of a database server. *SIGMOD*.
* Xu, Z., Tu, Y.-C., & Wang, X. (2010). Exploring power-performance tradeoffs in database systems. *ICDE*.
* Zobel, J., & Moffat, A. (2006). Inverted files for text search engines. *ACM Computing Surveys* 38(2).
