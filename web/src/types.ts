export type Params = Record<string, string | number>;

export interface MetricStats {
  n: number;
  median: number;
  ci_low: number;
  ci_high: number;
  mean: number;
  std: number;
  cv: number | null;
  q1: number;
  q3: number;
  min: number;
  max: number;
  values: number[];
}

export interface PhaseStats {
  duration_s: number;
  energy_pkg_j?: number;
  energy_dyn_j?: number;
}

export interface ConfigAnalysis {
  key: string;
  workload: string;
  variant: string;
  params: Params;
  label: string;
  labels: Record<string, string>;
  studies: string[];
  skipped: string | null;
  exact: boolean;
  n_runs: number;
  n_valid: number;
  n_invalid: number;
  n_errors: number;
  n_noisy: number;
  metrics: Record<string, MetricStats>;
  phases: Record<string, PhaseStats>;
  accuracy?: Record<string, { mape: number; p95_ape: number }>;
}

export interface ComparisonRow {
  key: string;
  label: string;
  variant: string;
  is_baseline: boolean;
  skipped: string | null;
  exact: boolean;
  energy?: Record<string, number>;
  duration_s?: number;
  energy_ratio?: number;
  energy_ratio_ci?: [number, number];
  energy_change_pct?: number;
  energy_change_ci_pct?: [number, number];
  duration_ratio?: number;
  duration_change_pct?: number;
  package_energy_change_pct?: number;
  p_value?: number;
  p_adj?: number;
  significant?: boolean;
  cliffs_delta?: number;
  magnitude?: string;
  pareto?: boolean;
}

export interface StudyGroup {
  group: Params;
  baseline: string | null;
  rows: ComparisonRow[];
}

export interface Recommendation {
  study: string;
  group: Params;
  kind: "switch" | "keep" | "inconclusive" | "trade-off";
  config: string;
  label: string;
  baseline: string;
  baseline_label: string;
  text: string;
  significant: boolean;
  exact: boolean;
  energy_change_pct: number;
  energy_change_ci_pct: [number, number];
  duration_change_pct: number;
  package_energy_change_pct: number | null;
  p_adj: number | null;
  cliffs_delta: number;
  magnitude: string;
  accuracy?: Record<string, { mape: number; p95_ape: number }>;
}

export interface StudyAnalysis {
  id: string;
  title: string;
  question: string;
  workload: string;
  factors: Record<string, (string | number)[]>;
  baseline: Params;
  group_by: string[];
  groups: StudyGroup[];
  recommendations: Recommendation[];
  insights: string[];
}

export interface MeterCheck {
  n: number;
  spearman_model_vs_dynamic: number;
  pearson_model_vs_dynamic: number;
  median_ratio_model_over_dynamic: number | null;
  median_ratio_model_over_package: number;
  points?: { model: number; dynamic: number }[];
  verdicts?: {
    hardware_significant_pairs: number;
    model_agrees: number;
    model_reverses: number;
    reversals: { study: string; a: string; b: string; hardware_ratio: number; model_ratio: number }[];
  };
}

export interface Analysis {
  campaign_id: string;
  generated_at: string;
  primary_metric: string;
  metrics: Record<string, { label: string; unit: string; description: string }>;
  idle_w: number | null;
  idle_drift_w: number | null;
  idle_background_cores: number;
  configs: ConfigAnalysis[];
  studies: StudyAnalysis[];
  recommendations: Recommendation[];
  meter_check: MeterCheck | null;
  quality: { runs: number; valid: number; invalid: number; errors: number; noisy: number; median_cv: number | null };
  totals: { energy_pkg_j: number; measured_seconds: number };
}

export interface CampaignStatus {
  state: string;
  done?: number;
  total?: number;
  measured?: number;
  invalid?: number;
  errors?: number;
  current?: { config: string; label: string; round: number } | null;
  eta_s?: number | null;
  started_at?: string;
  finished_at?: string;
  updated_at?: string;
}

export interface CampaignSummary {
  id: string;
  created_at: string;
  finished_at: string | null;
  preset: string;
  scale: string;
  repetitions: number;
  warmups: number;
  studies: string[];
  notes: string;
  n_configs: number;
  status: CampaignStatus;
  cpu: string;
  meter: string | null;
  quality: Analysis["quality"] | null;
  totals: Analysis["totals"] | null;
  idle_w: number | null;
  best: Recommendation | null;
}

export interface Variant { name: string; label: string; description: string; exact: boolean }

export interface WorkloadInfo {
  name: string;
  title: string;
  summary: string;
  description: string;
  icon: string;
  inputs: string[];
  phases: string[];
  variants: Variant[];
  knobs: Record<string, (string | number)[]>;
  defaults: Params;
  reference_variant: string;
  studies: string[];
}

export interface StudyInfo {
  id: string;
  title: string;
  question: string;
  workload: string;
  factors: Record<string, (string | number)[]>;
  baseline: Params;
  n_configs: number;
  n_skipped: number;
}

export interface Preset {
  name: string;
  label: string;
  description: string;
  scale: string;
  repetitions: number;
  warmups: number;
  cooldown_s: number;
  idle_s: number;
  runs: number;
}

export interface RoadmapTask { week: number; status: string; text: string }
export interface RoadmapPhase {
  id: string;
  title: string;
  weeks: [number, number];
  status: "done" | "in-progress" | "todo";
  summary: string;
  deliverable: string;
  links: { label: string; doc: string }[];
  tasks: RoadmapTask[];
}
export interface Roadmap { current_week: number; total_weeks: number; phases: RoadmapPhase[] }

export interface Overview {
  version: string;
  roadmap: Roadmap;
  latest: CampaignSummary | null;
  running: CampaignSummary | null;
  campaigns: number;
  runs_measured: number;
  energy_measured_j: number;
  recommendations: Recommendation[];
  studies: { id: string; title: string; insights: string[] }[];
  meter_check: Partial<MeterCheck>;
  idle_w: number | null;
}

export interface Environment {
  greenbench: string;
  os: { system: string; release: string; version: string; machine: string };
  python: { version: string };
  cpu: { name: string; physical_cores: number; logical_cpus: number; max_mhz: number | null; tdp_w: number; tdp_source: string };
  memory_gb: number;
  power: { ac_plugged: boolean | null; battery_percent: number | null; plan: string | null };
  virtualization: { virtualized: boolean; container: boolean; wsl: boolean; vm_guest: boolean };
  libraries: Record<string, string | null>;
  meters: Record<string, { available: boolean; reason?: string; interface?: string; provider?: string; domains?: string[] }>;
}
