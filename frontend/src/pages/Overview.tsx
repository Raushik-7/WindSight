import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ReactNode } from 'react';
import { CalendarRange, Database, FileWarning } from 'lucide-react';
import { CutoffControl, CutoffHint, ExportButton } from '../components/Controls';
import KpiCard from '../components/KpiCard';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { useCutoffParams } from '../context/CutoffContext';
import { useApi } from '../hooks/useApi';
import {
  formatCount,
  formatMw,
  formatNumber,
  formatPct,
  formatSignedMw,
  formatTimestamp,
  originLabel,
  tooltipMw,
} from '../lib/format';
import type { OverviewResponse } from '../types';

function axisTick(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  }).format(date);
}

function shortTick(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    timeZone: 'UTC',
  }).format(date);
}

export default function Overview() {
  const cutoffParams = useCutoffParams();
  const { data, error, loading, reload } = useApi<OverviewResponse>('/api/overview', cutoffParams);

  if (loading) return <LoadingState label="Loading evaluation results…" />;
  if (error) return <ErrorState message={error.message} code={error.code} onRetry={reload} />;
  if (!data) return <EmptyState title="No data" description="The service returned no payload." />;

  const { metrics, coverage, period, cutoff, provenance, summary, bias_narrative: biasNarrative, warnings } = data;

  if (!metrics.available) {
    return (
      <div className="space-y-6">
        <PageHeader cutoff={cutoff} />
        <EmptyState
          title="No matched intervals in this selection"
          description="The backend returned no forecast/actual pairs for the current cutoff, so metrics are reported as unavailable rather than zero. Adjust the decision cutoff or inspect the data-quality page."
        />
      </div>
    );
  }

  const biasTone = (metrics.bias_mw ?? 0) > 0 ? 'negative' : 'positive';

  return (
    <div className="space-y-6">
      <PageHeader cutoff={cutoff} />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <KpiCard
          title="Mean absolute error"
          value={formatNumber(metrics.mae_mw, 0)}
          unit="MW"
          hint="Average absolute difference between the selected forecast and actual outturn."
          detail={`Median AE ${formatMw(metrics.median_ae_mw)} · 90th pct ${formatMw(metrics.p90_ae_mw)}`}
        />
        <KpiCard
          title="Root mean squared error"
          value={formatNumber(metrics.rmse_mw, 0)}
          unit="MW"
          hint="Quadratic error mean; penalises large misses more heavily."
          detail={`Largest miss ${formatMw(metrics.max_ae_mw)}`}
        />
        <KpiCard
          title="Forecast bias"
          value={formatSignedMw(metrics.bias_mw)}
          tone={biasTone}
          hint="Mean signed error. Positive = forecast overestimated wind generation."
          detail={`${formatCount(metrics.overforecast_n)} over · ${formatCount(metrics.underforecast_n)} under`}
        />
        <KpiCard
          title="MAPE"
          value={formatPct(metrics.mape_pct)}
          hint="Mean absolute percentage error over intervals with non-zero actual output."
          detail={`${formatCount(metrics.mape_n)} of ${formatCount(metrics.n)} intervals used${
            metrics.mape_excluded_zero_actual
              ? ` · ${formatCount(metrics.mape_excluded_zero_actual)} excluded (actual = 0)`
              : ''
          }`}
        />
        <KpiCard
          title="Matched intervals"
          value={formatCount(coverage.matched)}
          detail={`of ${formatCount(coverage.expected)} expected half-hourly intervals`}
        />
        <KpiCard
          title="Data coverage"
          value={formatPct(coverage.coverage_pct)}
          tone={coverage.coverage_pct !== null && coverage.coverage_pct < 95 ? 'warning' : 'neutral'}
          detail={`${formatCount(coverage.status_counts.missing_actual ?? 0)} missing actual · ${formatCount(
            coverage.status_counts.missing_eligible_forecast ?? 0,
          )} missing forecast`}
        />
      </section>

      <section className="card p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <h2 className="text-sm font-semibold text-ink-900">Evaluation summary</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-800">{summary}</p>
            <p className="mt-2 text-sm leading-relaxed text-muted">{biasNarrative}</p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <ExportButton params={cutoffParams} label="Export matched intervals" />
            <p className="text-right text-xs text-muted">
              Period {period.label}
              <br />
              {formatCount(period.expected_intervals)} expected intervals
            </p>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <article className="card">
          <div className="card-header">
            <div>
              <h2 className="text-sm font-semibold text-ink-900">Forecast vs actual generation</h2>
              <p className="mt-1 text-xs text-muted">
                Hourly means across the evaluation period (MW), UTC timestamps
              </p>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <span className="flex items-center gap-1.5">
                <span className="h-0.5 w-4 bg-ink-700" aria-hidden="true" /> Forecast
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-0.5 w-4 bg-accent" aria-hidden="true" /> Actual
              </span>
            </div>
          </div>
          <div className="p-4" role="img" aria-label="Line chart comparing hourly forecast and actual wind generation across January 2026">
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={data.series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="time" tickFormatter={shortTick} minTickGap={40} tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} width={54} label={{ value: 'MW', angle: -90, position: 'insideLeft', fontSize: 11 }} />
                <Tooltip
                  labelFormatter={(value) => axisTick(String(value))}
                  formatter={(value: number, name: string) => [formatMw(value), name]}
                />
                <Line type="monotone" dataKey="forecast_mw" name="Forecast" stroke="#1c4a74" dot={false} strokeWidth={1.6} isAnimationActive={false} />
                <Line type="monotone" dataKey="actual_mw" name="Actual" stroke="#0f9d58" dot={false} strokeWidth={1.6} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="card">
          <div className="card-header">
            <div>
              <h2 className="text-sm font-semibold text-ink-900">Daily mean absolute error</h2>
              <p className="mt-1 text-xs text-muted">MAE per delivery date (MW)</p>
            </div>
          </div>
          <div className="p-4" role="img" aria-label="Bar chart of daily mean absolute error in megawatts">
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={data.daily} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(8)} minTickGap={12} tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} width={54} />
                <Tooltip
                  formatter={tooltipMw}
                  labelFormatter={(label) => `Delivery date ${label}`}
                />
                <ReferenceLine y={metrics.mae_mw ?? 0} stroke="#b45309" strokeDasharray="4 4" label={{ value: 'period MAE', fontSize: 10, fill: '#b45309', position: 'insideTopRight' }} />
                <Line
                  type="monotone"
                  dataKey="mae_mw"
                  name="MAE"
                  stroke="#0b1f33"
                  strokeWidth={1.8}
                  dot={{ r: 2 }}
                  isAnimationActive={false}
                  connectNulls={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </article>
      </section>

      <section className="card">
        <div className="card-header">
          <h2 className="text-sm font-semibold text-ink-900">Data provenance</h2>
          <span
            className={`rounded-full border px-2.5 py-1 text-xs ${
              provenance.origin === 'live'
                ? 'border-accent/30 bg-accent/10 text-accent-strong'
                : 'border-warn/30 bg-warn/10 text-warn'
            }`}
          >
            {originLabel(provenance.origin)}
          </span>
        </div>
        <div className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <ProvenanceItem label="Actual records" value={formatCount(provenance.actual_records)} icon={<Database className="h-4 w-4" />} />
          <ProvenanceItem label="Forecast records" value={formatCount(provenance.forecast_records)} icon={<Database className="h-4 w-4" />} />
          <ProvenanceItem label="Retrieved at" value={formatTimestamp(provenance.retrieved_at)} icon={<CalendarRange className="h-4 w-4" />} />
          <ProvenanceItem
            label="Upstream requests"
            value={formatCount(provenance.upstream_requests)}
            icon={<FileWarning className="h-4 w-4" />}
          />
        </div>
        {provenance.source_datasets?.length ? (
          <div className="border-t border-line px-5 py-4 text-xs text-muted">
            {provenance.source_datasets.map((dataset) => (
              <p key={dataset.name} className="mb-1">
                <span className="font-semibold text-ink-800">{dataset.name}</span> — {dataset.role}{' '}
                <a className="text-info underline" href={dataset.docs} target="_blank" rel="noreferrer">
                  documentation
                </a>
              </p>
            ))}
          </div>
        ) : null}
      </section>

      {warnings.length ? (
        <section className="card border-warn/30 bg-warn/5 p-5" aria-live="polite">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-warn">
            <FileWarning className="h-4 w-4" aria-hidden="true" /> Data-quality notices
          </h2>
          <ul className="mt-2 space-y-1 text-sm text-ink-800">
            {warnings.map((warning, index) => (
              <li key={`${index}`}>{warning.message}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function ProvenanceItem({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 text-muted" aria-hidden="true">
        {icon}
      </span>
      <div>
        <p className="label-caps">{label}</p>
        <p className="mt-1 text-sm font-medium text-ink-900">{value}</p>
      </div>
    </div>
  );
}

function PageHeader({ cutoff }: { cutoff: OverviewResponse['cutoff'] }) {
  return (
    <header className="card p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="label-caps">Evaluation period</p>
          <h1 className="mt-1 text-xl font-semibold text-ink-900 sm:text-2xl">
            January 2026 wind forecast reliability
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-muted">
            What the day-ahead forecast said when the procurement decision had to be made, compared
            with actual half-hourly wind outturn from Elexon BMRS.
          </p>
        </div>
        <div className="lg:w-96">
          <CutoffControl id="overview-cutoff" />
          <CutoffHint description={cutoff.description} />
        </div>
      </div>
    </header>
  );
}
