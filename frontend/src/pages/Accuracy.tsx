import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { FileWarning } from 'lucide-react';
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
  tooltipCount,
  tooltipMw,
  tooltipSignedMw,
} from '../lib/format';
import type { AccuracyResponse } from '../types';

function isoDay(day: number): string {
  return `2026-01-${String(day).padStart(2, '0')}`;
}

export default function Accuracy() {
  const cutoffParams = useCutoffParams();
  const [from, setFrom] = useState('2026-01-01');
  const [to, setTo] = useState('2026-01-31');

  const params = useMemo(
    () => ({ from, to, ...cutoffParams }),
    [from, to, cutoffParams],
  );
  const { data, error, loading, reload } = useApi<AccuracyResponse>('/api/accuracy', params);

  const rangeInvalid = from > to;

  return (
    <div className="space-y-6">
      <header className="card p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="label-caps">Accuracy analysis</p>
            <h1 className="mt-1 text-xl font-semibold text-ink-900 sm:text-2xl">
              Forecast accuracy over the evaluation period
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-muted">
              Every figure below is recomputed by the backend for the selected delivery-date range
              and decision cutoff.
            </p>
          </div>
          <div className="lg:w-96">
            <CutoffControl id="accuracy-cutoff" />
            <CutoffHint description={data?.cutoff.description} />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="range-from" className="label-caps">
              Delivery date from
            </label>
            <select id="range-from" className="input" value={from} onChange={(e) => setFrom(e.target.value)}>
              {Array.from({ length: 31 }, (_, i) => isoDay(i + 1)).map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="range-to" className="label-caps">
              Delivery date to
            </label>
            <select id="range-to" className="input" value={to} onChange={(e) => setTo(e.target.value)}>
              {Array.from({ length: 31 }, (_, i) => isoDay(i + 1)).map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>
          <div className="ml-auto">
            <ExportButton params={params} label="Export range" />
          </div>
        </div>

        {rangeInvalid ? (
          <p className="mt-3 text-sm text-danger" role="alert">
            The start date must not be after the end date.
          </p>
        ) : null}
      </header>

      {loading ? <LoadingState label="Recomputing metrics…" /> : null}
      {error ? <ErrorState message={error.message} code={error.code} onRetry={reload} /> : null}

      {!loading && !error && data && !rangeInvalid ? (
        <>
          {!data.metrics.available ? (
            <EmptyState
              title="No matched observations in this range"
              description="Nothing could be matched under the current cutoff, so metrics are unavailable rather than zero. Try widening the range or changing the cutoff."
            />
          ) : (
            <>
              <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <KpiCard
                  title="Mean absolute error"
                  value={formatNumber(data.metrics.mae_mw, 0)}
                  unit="MW"
                  detail={`n = ${formatCount(data.metrics.n)} matched intervals`}
                />
                <KpiCard
                  title="Root mean squared error"
                  value={formatNumber(data.metrics.rmse_mw, 0)}
                  unit="MW"
                  detail={`Max absolute error ${formatMw(data.metrics.max_ae_mw)}`}
                />
                <KpiCard
                  title="Forecast bias"
                  value={formatSignedMw(data.metrics.bias_mw)}
                  tone={(data.metrics.bias_mw ?? 0) > 0 ? 'negative' : 'positive'}
                  detail={`${formatCount(data.metrics.overforecast_n)} over · ${formatCount(data.metrics.underforecast_n)} under`}
                />
                <KpiCard
                  title="MAPE"
                  value={formatPct(data.metrics.mape_pct)}
                  detail={`${formatCount(data.metrics.mape_n)} non-zero-actual intervals used`}
                  hint="Excludes intervals where actual generation is zero."
                />
                <KpiCard
                  title="Median absolute error"
                  value={formatNumber(data.metrics.median_ae_mw, 0)}
                  unit="MW"
                  detail={`90th percentile ${formatMw(data.metrics.p90_ae_mw)}`}
                />
                <KpiCard
                  title="Coverage"
                  value={formatPct(data.coverage.coverage_pct)}
                  detail={`${formatCount(data.coverage.matched)} of ${formatCount(data.coverage.expected)} expected intervals`}
                />
              </section>

              <section className="grid grid-cols-1 gap-6 xl:grid-cols-2">
                <article className="card">
                  <div className="card-header">
                    <div>
                      <h2 className="text-sm font-semibold text-ink-900">Daily MAE</h2>
                      <p className="mt-1 text-xs text-muted">Mean absolute error per delivery date (MW)</p>
                    </div>
                  </div>
                  <div className="p-4" role="img" aria-label="Daily mean absolute error line chart">
                    <ResponsiveContainer width="100%" height={280}>
                      <ComposedChart data={data.daily} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(8)} minTickGap={12} tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} width={54} />
                        <Tooltip
                          formatter={tooltipMw}
                          labelFormatter={(label) => `Delivery date ${label}`}
                        />
                        <Line type="monotone" dataKey="mae_mw" name="MAE" stroke="#0b1f33" strokeWidth={1.8} dot={{ r: 2 }} isAnimationActive={false} connectNulls={false} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </article>

                <article className="card">
                  <div className="card-header">
                    <div>
                      <h2 className="text-sm font-semibold text-ink-900">Daily bias</h2>
                      <p className="mt-1 text-xs text-muted">
                        Mean signed error per delivery date (MW); positive = overforecast
                      </p>
                    </div>
                  </div>
                  <div className="p-4" role="img" aria-label="Daily forecast bias line chart">
                    <ResponsiveContainer width="100%" height={280}>
                      <ComposedChart data={data.daily} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(8)} minTickGap={12} tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} width={54} />
                        <Tooltip
                          formatter={tooltipSignedMw}
                          labelFormatter={(label) => `Delivery date ${label}`}
                        />
                        <Line type="monotone" dataKey="bias_mw" name="Bias" stroke="#b91c1c" strokeWidth={1.8} dot={false} isAnimationActive={false} connectNulls={false} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </article>
              </section>

              <section className="grid grid-cols-1 gap-6 xl:grid-cols-2">
                <article className="card">
                  <div className="card-header">
                    <div>
                      <h2 className="text-sm font-semibold text-ink-900">MAE by hour of day</h2>
                      <p className="mt-1 text-xs text-muted">UTC hour of the delivery interval</p>
                    </div>
                  </div>
                  <div className="p-4" role="img" aria-label="Bar chart of mean absolute error by hour of day">
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={data.by_hour} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="hour_utc" tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} width={54} />
                        <Tooltip
                          formatter={tooltipMw}
                          labelFormatter={(label) => `Hour ${label}:00 UTC`}
                        />
                        <Bar dataKey="mae_mw" name="MAE" fill="#1c4a74" isAnimationActive={false} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </article>

                <article className="card">
                  <div className="card-header">
                    <div>
                      <h2 className="text-sm font-semibold text-ink-900">Error distribution</h2>
                      <p className="mt-1 text-xs text-muted">
                        Signed error (forecast − actual) in MW; negative = underforecast
                      </p>
                    </div>
                  </div>
                  <div className="p-4" role="img" aria-label="Bar chart of signed forecast error distribution">
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={data.error_distribution} margin={{ top: 8, right: 8, left: 0, bottom: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="range" tick={{ fontSize: 9 }} angle={-35} textAnchor="end" height={70} />
                        <YAxis tick={{ fontSize: 11 }} width={44} />
                        <Tooltip formatter={tooltipCount} />
                        <Bar dataKey="count" name="Intervals" fill="#b45309" isAnimationActive={false} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </article>
              </section>
            </>
          )}

          <section className="card">
            <div className="card-header">
              <h2 className="text-sm font-semibold text-ink-900">Daily breakdown</h2>
              <p className="text-xs text-muted">Same selection rules as every other view</p>
            </div>
            <div className="table-scroll">
              <table className="table-base">
                <caption className="sr-only">Daily forecast accuracy metrics</caption>
                <thead>
                  <tr>
                    <th scope="col">Delivery date</th>
                    <th scope="col" className="text-right">Matched</th>
                    <th scope="col" className="text-right">Coverage</th>
                    <th scope="col" className="text-right">MAE (MW)</th>
                    <th scope="col" className="text-right">RMSE (MW)</th>
                    <th scope="col" className="text-right">Bias (MW)</th>
                    <th scope="col" className="text-right">MAPE</th>
                  </tr>
                </thead>
                <tbody>
                  {data.daily.map((row) => (
                    <tr key={row.date}>
                      <td className="whitespace-nowrap font-mono text-xs">{row.date}</td>
                      <td className="text-right tabular-nums">{row.matched}</td>
                      <td className="text-right tabular-nums">{formatPct(row.coverage_pct)}</td>
                      <td className="text-right tabular-nums">{formatNumber(row.mae_mw, 0)}</td>
                      <td className="text-right tabular-nums">{formatNumber(row.rmse_mw, 0)}</td>
                      <td className={`text-right tabular-nums ${(row.bias_mw ?? 0) > 0 ? 'text-danger' : 'text-accent-strong'}`}>
                        {row.bias_mw === null ? '—' : formatNumber(row.bias_mw, 0)}
                      </td>
                      <td className="text-right tabular-nums">{formatPct(row.mape_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {data.warnings.length ? (
            <section className="card border-warn/30 bg-warn/5 p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-warn">
                <FileWarning className="h-4 w-4" aria-hidden="true" /> Data-quality warnings
              </h2>
              <ul className="mt-2 space-y-1 text-sm text-ink-800">
                {data.warnings.map((warning, index) => (
                  <li key={index}>{warning.message}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
