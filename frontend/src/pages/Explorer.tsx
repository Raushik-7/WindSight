import { useMemo, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { ChevronLeft, ChevronRight, ArrowUpDown } from 'lucide-react';
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
  statusMeta,
} from '../lib/format';
import type { ForecastsResponse, IntervalRow } from '../types';

type SortKey = 'start_local' | 'publish_time' | 'forecast_mw' | 'actual_mw' | 'error_mw' | 'absolute_error_mw';

function isoDay(day: number): string {
  return `2026-01-${String(day).padStart(2, '0')}`;
}

function dayOf(iso: string): number {
  return Number(iso.slice(8, 10));
}

function timeTick(value: string) {
  return value.slice(11, 16);
}

function ChartTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload as IntervalRow;
  return (
    <div className="rounded-md border border-line bg-white p-3 text-xs shadow-lg">
      <p className="font-semibold text-ink-900">{row.start_local} (local)</p>
      <p className="text-muted">UTC {row.start_utc.replace('T', ' ').replace('+00:00', '')}</p>
      <div className="mt-2 space-y-1">
        <p>Forecast: <span className="font-medium">{formatMw(row.forecast_mw)}</span></p>
        <p>Actual: <span className="font-medium">{formatMw(row.actual_mw)}</span></p>
        <p>Error: <span className="font-medium">{formatSignedMw(row.error_mw)}</span></p>
        <p>Absolute error: <span className="font-medium">{formatMw(row.absolute_error_mw)}</span></p>
        <p className="text-muted">Published: {formatTimestamp(row.publish_time)}</p>
        <p className="text-muted">Status: {statusMeta(row.status).label}</p>
      </div>
    </div>
  );
}

export default function Explorer() {
  const cutoffParams = useCutoffParams();
  const [date, setDate] = useState('2026-01-15');
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({
    key: 'start_local',
    dir: 'asc',
  });

  const params = useMemo(() => ({ date, ...cutoffParams }), [date, cutoffParams]);
  const { data, error, loading, reload } = useApi<ForecastsResponse>('/api/forecasts', params);

  const rows = useMemo(() => {
    if (!data) return [];
    const copy = [...data.intervals];
    copy.sort((a, b) => {
      const left = a[sort.key];
      const right = b[sort.key];
      if (left === null && right === null) return 0;
      if (left === null) return 1; // missing values sort last
      if (right === null) return -1;
      const result =
        typeof left === 'number' && typeof right === 'number'
          ? left - right
          : String(left).localeCompare(String(right));
      return sort.dir === 'asc' ? result : -result;
    });
    return copy;
  }, [data, sort]);

  const day = dayOf(date);
  const chartData = data?.intervals ?? [];

  const toggleSort = (key: SortKey) =>
    setSort((prev) => ({ key, dir: prev.key === key && prev.dir === 'asc' ? 'desc' : 'asc' }));

  return (
    <div className="space-y-6">
      <header className="card p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="label-caps">Forecast explorer</p>
            <h1 className="mt-1 text-xl font-semibold text-ink-900 sm:text-2xl">
              Delivery date {date}
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-muted">
              All 48 half-hourly intervals for the selected day, with the forecast the cutoff rule
              actually selected and the actual outturn it was compared against.
            </p>
          </div>
          <div className="lg:w-96">
            <CutoffControl id="explorer-cutoff" />
            <CutoffHint description={data?.cutoff.description} />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="delivery-date" className="label-caps">
              Delivery date
            </label>
            <select
              id="delivery-date"
              className="input"
              value={date}
              onChange={(event) => setDate(event.target.value)}
            >
              {Array.from({ length: 31 }, (_, index) => index + 1).map((d) => (
                <option key={d} value={isoDay(d)}>
                  {isoDay(d)}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setDate(isoDay(Math.max(1, day - 1)))}
              disabled={day <= 1}
              aria-label="Previous delivery date"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              Previous
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setDate(isoDay(Math.min(31, day + 1)))}
              disabled={day >= 31}
              aria-label="Next delivery date"
            >
              Next
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>

          <div className="ml-auto">
            <ExportButton params={params} label="Export this day" />
          </div>
        </div>
      </header>

      {loading ? <LoadingState label="Loading delivery intervals…" /> : null}
      {error ? <ErrorState message={error.message} code={error.code} onRetry={reload} /> : null}

      {!loading && !error && data ? (
        <>
          <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              title="Selected publication"
              value={data.selected_publish_times.length ? data.selected_publish_times.length.toString() : '—'}
              detail={
                data.selected_publish_times.length
                  ? formatTimestamp(data.selected_publish_times[0])
                  : 'No eligible forecast for this date'
              }
              hint="Publication time of the latest forecast that was still eligible at the cutoff."
            />
            <KpiCard
              title="Day MAE"
              value={formatNumber(data.metrics.mae_mw, 0)}
              unit="MW"
              detail={`${formatCount(data.metrics.n)} matched intervals`}
            />
            <KpiCard
              title="Day bias"
              value={formatSignedMw(data.metrics.bias_mw)}
              tone={(data.metrics.bias_mw ?? 0) > 0 ? 'negative' : 'positive'}
              detail={`${formatCount(data.metrics.overforecast_n)} over · ${formatCount(data.metrics.underforecast_n)} under`}
            />
            <KpiCard
              title="Coverage"
              value={formatPct(data.coverage.coverage_pct)}
              detail={`${formatCount(data.coverage.matched)} of ${formatCount(data.coverage.expected)} intervals`}
            />
          </section>

          <section className="card">
            <div className="card-header">
              <div>
                <h2 className="text-sm font-semibold text-ink-900">Forecast, actual and error</h2>
                <p className="mt-1 text-xs text-muted">
                  Half-hourly intervals (local time, Europe/London) · MW
                </p>
              </div>
              <div className="flex items-center gap-3 text-xs">
                <span className="flex items-center gap-1.5">
                  <span className="h-0.5 w-4 bg-ink-700" aria-hidden="true" /> Forecast
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-0.5 w-4 bg-accent" aria-hidden="true" /> Actual
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-3 bg-warn/70" aria-hidden="true" /> |Error|
                </span>
              </div>
            </div>
            <div
              className="p-4"
              role="img"
              aria-label={`Chart of forecast and actual wind generation with absolute error for ${date}`}
            >
              <ResponsiveContainer width="100%" height={320}>
                <ComposedChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="start_local" tickFormatter={timeTick} interval={3} tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="mw" tick={{ fontSize: 11 }} width={54} />
                  <YAxis yAxisId="err" orientation="right" tick={{ fontSize: 11 }} width={44} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar yAxisId="err" dataKey="absolute_error_mw" name="Absolute error" fill="#b45309" fillOpacity={0.35} isAnimationActive={false} />
                  <Line yAxisId="mw" type="monotone" dataKey="forecast_mw" name="Forecast" stroke="#1c4a74" strokeWidth={1.8} dot={false} isAnimationActive={false} connectNulls={false} />
                  <Line yAxisId="mw" type="monotone" dataKey="actual_mw" name="Actual" stroke="#0f9d58" strokeWidth={1.8} dot={false} isAnimationActive={false} connectNulls={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h2 className="text-sm font-semibold text-ink-900">Interval detail</h2>
              <p className="text-xs text-muted">{rows.length} rows · missing values shown as “—”</p>
            </div>
            <div className="table-scroll">
              <table className="table-base">
                <caption className="sr-only">
                  Forecast and actual wind generation for each half-hourly delivery interval on {date}
                </caption>
                <thead>
                  <tr>
                    <SortHeader label="Delivery time" active={sort.key === 'start_local'} dir={sort.dir} onClick={() => toggleSort('start_local')} />
                    <SortHeader label="Forecast published" active={sort.key === 'publish_time'} dir={sort.dir} onClick={() => toggleSort('publish_time')} />
                    <SortHeader label="Forecast (MW)" align="right" active={sort.key === 'forecast_mw'} dir={sort.dir} onClick={() => toggleSort('forecast_mw')} />
                    <SortHeader label="Actual (MW)" align="right" active={sort.key === 'actual_mw'} dir={sort.dir} onClick={() => toggleSort('actual_mw')} />
                    <SortHeader label="Error (MW)" align="right" active={sort.key === 'error_mw'} dir={sort.dir} onClick={() => toggleSort('error_mw')} />
                    <SortHeader label="Abs error (MW)" align="right" active={sort.key === 'absolute_error_mw'} dir={sort.dir} onClick={() => toggleSort('absolute_error_mw')} />
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const meta = statusMeta(row.status);
                    const negative = (row.error_mw ?? 0) < 0;
                    return (
                      <tr key={row.start_utc} className={row.is_extreme_error ? 'bg-warn/5' : undefined}>
                        <td className="whitespace-nowrap font-mono text-xs">
                          {row.start_local.slice(11)}
                          <span className="ml-2 text-muted">{row.start_local.slice(0, 10)}</span>
                        </td>
                        <td className="whitespace-nowrap text-xs text-muted">
                          {row.publish_time ? formatTimestamp(row.publish_time) : '—'}
                        </td>
                        <td className="text-right tabular-nums">{formatNumber(row.forecast_mw)}</td>
                        <td className="text-right tabular-nums">{formatNumber(row.actual_mw)}</td>
                        <td className={`text-right tabular-nums ${row.error_mw === null ? 'text-muted' : negative ? 'text-accent-strong' : 'text-danger'}`}>
                          {row.error_mw === null ? '—' : formatNumber(row.error_mw)}
                        </td>
                        <td className="text-right tabular-nums">{formatNumber(row.absolute_error_mw)}</td>
                        <td>
                          <span
                            className={`inline-block rounded border px-2 py-0.5 text-xs ${meta.className}`}
                            title={meta.hint}
                          >
                            {meta.label}
                          </span>
                          {row.exclusion_reason ? (
                            <span className="ml-2 font-mono text-[11px] text-muted">{row.exclusion_reason}</span>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {data.notes.length ? (
            <section className="card p-5">
              <h2 className="text-sm font-semibold text-ink-900">Notes for this selection</h2>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
                {data.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}

      {!loading && !error && data && data.intervals.length === 0 ? (
        <EmptyState
          title="No intervals returned"
          description="The backend returned an empty interval list for this date."
        />
      ) : null}
    </div>
  );
}

function SortHeader({
  label,
  active,
  dir,
  onClick,
  align = 'left',
}: {
  label: string;
  active: boolean;
  dir: 'asc' | 'desc';
  onClick: () => void;
  align?: 'left' | 'right';
}) {
  return (
    <th
      scope="col"
      className={align === 'right' ? 'text-right' : 'text-left'}
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        onClick={onClick}
        className="label-caps inline-flex items-center gap-1 hover:text-ink-800"
      >
        {label}
        <ArrowUpDown className={`h-3 w-3 ${active ? 'text-ink-900' : 'text-muted/60'}`} aria-hidden="true" />
      </button>
    </th>
  );
}
