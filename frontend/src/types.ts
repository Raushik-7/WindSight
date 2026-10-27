/** Types mirroring the FastAPI response schemas. */

export interface CutoffPayload {
  time: string;
  day_offset: number;
  timezone: string;
  label: string;
  description: string;
}

export interface MetricPayload {
  available: boolean;
  n: number;
  mae_mw: number | null;
  rmse_mw: number | null;
  bias_mw: number | null;
  mape_pct: number | null;
  mape_n: number;
  mape_excluded_zero_actual: number;
  median_ae_mw: number | null;
  p90_ae_mw: number | null;
  max_ae_mw: number | null;
  overforecast_n: number;
  underforecast_n: number;
  exact_n: number;
}

export interface CoveragePayload {
  expected: number;
  matched: number;
  coverage_pct: number | null;
  status_counts: Record<string, number>;
}

export interface PeriodPayload {
  start: string;
  end: string;
  label: string;
  expected_intervals: number;
  intervals_per_day: number;
}

export interface DatasetPayload {
  name: string;
  role: string;
  docs: string;
}

export interface ProvenancePayload {
  available: boolean;
  origin?: string | null;
  origin_detail?: string | null;
  retrieved_at?: string | null;
  upstream_requests?: number | null;
  actual_records?: number | null;
  forecast_records?: number | null;
  excluded_records?: number | null;
  fetch_errors?: string[] | null;
  source_datasets?: DatasetPayload[] | null;
  base_url?: string | null;
  error?: string | null;
}

export interface WarningPayload {
  level: string;
  message: string;
}

export interface DailyRow {
  date: string;
  expected: number;
  matched: number;
  coverage_pct: number | null;
  mae_mw: number | null;
  rmse_mw: number | null;
  bias_mw: number | null;
  mape_pct: number | null;
  n: number;
  mean_forecast_mw: number | null;
  mean_actual_mw: number | null;
}

export interface SeriesPoint {
  time: string;
  forecast_mw: number;
  actual_mw: number;
}

export interface OverviewResponse {
  period: PeriodPayload;
  cutoff: CutoffPayload;
  metrics: MetricPayload;
  coverage: CoveragePayload;
  summary: string;
  bias_narrative: string;
  daily: DailyRow[];
  series: SeriesPoint[];
  provenance: ProvenancePayload;
  warnings: WarningPayload[];
}

export interface IntervalRow {
  start_utc: string;
  start_local: string;
  delivery_date: string;
  slot: number;
  status: string;
  forecast_mw: number | null;
  actual_mw: number | null;
  publish_time: string | null;
  forecast_source_start: string | null;
  decision_cutoff: string;
  error_mw: number | null;
  absolute_error_mw: number | null;
  squared_error_mw2: number | null;
  exclusion_reason: string | null;
  is_extreme_error: boolean;
}

export interface ForecastsResponse {
  date: string;
  cutoff: CutoffPayload;
  intervals: IntervalRow[];
  metrics: MetricPayload;
  coverage: CoveragePayload;
  selected_publish_times: string[];
  provenance: ProvenancePayload;
  warnings: WarningPayload[];
  notes: string[];
}

export interface HourRow {
  hour_utc: number;
  n: number;
  mae_mw: number | null;
  bias_mw: number | null;
  mean_actual_mw: number | null;
}

export interface DistributionRow {
  range: string;
  count: number;
  direction: string;
}

export interface AccuracyResponse {
  date_from: string;
  date_to: string;
  cutoff: CutoffPayload;
  metrics: MetricPayload;
  coverage: CoveragePayload;
  daily: DailyRow[];
  by_hour: HourRow[];
  error_distribution: DistributionRow[];
  provenance: ProvenancePayload;
  warnings: WarningPayload[];
}

export interface DataQualityResponse {
  coverage: CoveragePayload;
  record_exclusions: Record<string, number>;
  excluded_examples: { dataset: string; reason: string; detail: string }[];
  interval_reasons: Record<string, number>;
  late_forecast_excluded_intervals: number;
  distinct_selected_publish_times: number;
  selected_publish_times: string[];
  cutoff: CutoffPayload;
  provenance: ProvenancePayload;
  warnings: WarningPayload[];
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}
