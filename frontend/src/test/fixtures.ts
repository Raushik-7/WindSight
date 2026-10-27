import type {
  AccuracyResponse,
  ForecastsResponse,
  OverviewResponse,
} from '../types';

/** Test payloads shaped exactly like the FastAPI responses (fixtures only). */

export const CUTOFF = {
  time: '12:00',
  day_offset: -1,
  timezone: 'Europe/London',
  label: '12:00 Europe/London (-1d)',
  description:
    'Day-ahead decision cutoff: 12:00 Europe/London on the calendar day before each delivery date.',
};

export const PROVENANCE = {
  available: true,
  origin: 'live',
  origin_detail: 'actuals=live (1488 rows), forecasts=live (35624 rows)',
  retrieved_at: '2026-01-31T23:59:00+00:00',
  upstream_requests: 8,
  actual_records: 1488,
  forecast_records: 35624,
  excluded_records: 0,
  fetch_errors: [] as string[],
  source_datasets: [
    {
      name: 'FUELHH',
      role: 'Actual half-hourly wind generation outturn',
      docs: 'https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream',
    },
  ],
  base_url: 'https://data.elexon.co.uk/bmrs/api/v1',
};

export const OVERVIEW: OverviewResponse = {
  period: {
    start: '2026-01-01',
    end: '2026-01-31',
    label: '01 January – 31 January 2026',
    expected_intervals: 1488,
    intervals_per_day: 48,
  },
  cutoff: CUTOFF,
  metrics: {
    available: true,
    n: 1488,
    mae_mw: 2020.6,
    rmse_mw: 2481.4,
    bias_mw: 1806.2,
    mape_pct: 19.74,
    mape_n: 1488,
    mape_excluded_zero_actual: 0,
    median_ae_mw: 1711,
    p90_ae_mw: 4025,
    max_ae_mw: 6885,
    overforecast_n: 1271,
    underforecast_n: 217,
    exact_n: 0,
  },
  coverage: {
    expected: 1488,
    matched: 1488,
    coverage_pct: 100,
    status_counts: {
      matched: 1488,
      missing_actual: 0,
      missing_eligible_forecast: 0,
      missing_forecast_and_actual: 0,
    },
  },
  summary: 'Between 01 January 2026 and 31 January 2026, 1,488 intervals matched.',
  bias_narrative: 'On average the selected forecast tends to overestimate wind generation.',
  daily: [
    {
      date: '2026-01-01',
      expected: 48,
      matched: 48,
      coverage_pct: 100,
      mae_mw: 1234,
      rmse_mw: 1500,
      bias_mw: 900,
      mape_pct: 12.5,
      n: 48,
      mean_forecast_mw: 9000,
      mean_actual_mw: 8100,
    },
  ],
  series: [
    { time: '2026-01-01T00:00:00+00:00', forecast_mw: 9500, actual_mw: 8000 },
    { time: '2026-01-01T01:00:00+00:00', forecast_mw: 9400, actual_mw: 8600 },
  ],
  provenance: PROVENANCE,
  warnings: [],
};

export const OVERVIEW_EMPTY_METRICS: OverviewResponse = {
  ...OVERVIEW,
  metrics: {
    ...OVERVIEW.metrics,
    available: false,
    n: 0,
    mae_mw: null,
    rmse_mw: null,
    bias_mw: null,
    mape_pct: null,
    mape_n: 0,
    median_ae_mw: null,
    p90_ae_mw: null,
    max_ae_mw: null,
  },
  coverage: { ...OVERVIEW.coverage, matched: 0, coverage_pct: 0 },
  summary: 'No matched forecast/actual intervals are available for this selection.',
  bias_narrative: 'Bias unavailable: no matched observations in this selection.',
};

function interval(slot: number, overrides: Record<string, unknown> = {}) {
  const minute = (slot * 30) % 60;
  const hour = Math.floor((slot * 30) / 60);
  const time = `2026-01-15 ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
  return {
    start_utc: `${time}:00+00:00`,
    start_local: time,
    delivery_date: '2026-01-15',
    slot,
    status: 'matched',
    forecast_mw: 9500,
    actual_mw: 8000,
    publish_time: '2026-01-14T11:30:00+00:00',
    forecast_source_start: `${time.slice(0, 13)}:00:00+00:00`,
    decision_cutoff: '2026-01-14T12:00:00+00:00',
    error_mw: 1500,
    absolute_error_mw: 1500,
    squared_error_mw2: 2250000,
    exclusion_reason: null,
    is_extreme_error: false,
    ...overrides,
  };
}

export const FORECASTS: ForecastsResponse = {
  date: '2026-01-15',
  cutoff: CUTOFF,
  intervals: Array.from({ length: 48 }, (_, slot) =>
    interval(
      slot,
      slot === 3
        ? {
            status: 'missing_actual',
            actual_mw: null,
            error_mw: null,
            absolute_error_mw: null,
            squared_error_mw2: null,
          }
        : slot === 4
          ? {
              status: 'missing_eligible_forecast',
              forecast_mw: null,
              publish_time: null,
              error_mw: null,
              absolute_error_mw: null,
              squared_error_mw2: null,
              exclusion_reason: 'all_forecasts_published_after_cutoff',
            }
          : {},
    ),
  ),
  metrics: {
    available: true,
    n: 46,
    mae_mw: 750,
    rmse_mw: 935.4,
    bias_mw: 750,
    mape_pct: 9.02,
    mape_n: 46,
    mape_excluded_zero_actual: 0,
    median_ae_mw: 750,
    p90_ae_mw: 1500,
    max_ae_mw: 1500,
    overforecast_n: 46,
    underforecast_n: 0,
    exact_n: 0,
  },
  coverage: {
    expected: 48,
    matched: 46,
    coverage_pct: 95.83,
    status_counts: {
      matched: 46,
      missing_actual: 1,
      missing_eligible_forecast: 1,
      missing_forecast_and_actual: 0,
    },
  },
  selected_publish_times: ['2026-01-14T11:30:00+00:00'],
  provenance: PROVENANCE,
  warnings: [],
  notes: ['WINDFOR publishes one value per hour; the hourly forecast is shown against each half-hour.'],
};

export const ACCURACY: AccuracyResponse = {
  date_from: '2026-01-01',
  date_to: '2026-01-31',
  cutoff: CUTOFF,
  metrics: OVERVIEW.metrics,
  coverage: OVERVIEW.coverage,
  daily: OVERVIEW.daily,
  by_hour: Array.from({ length: 24 }, (_, hour) => ({
    hour_utc: hour,
    n: 62,
    mae_mw: 2000,
    bias_mw: 1700,
    mean_actual_mw: 9000,
  })),
  error_distribution: [
    { range: '-500 to 0 MW', count: 120, direction: 'under' },
    { range: '0 to 500 MW', count: 400, direction: 'over' },
    { range: '500 to 2000 MW', count: 600, direction: 'over' },
  ],
  provenance: PROVENANCE,
  warnings: [],
};
