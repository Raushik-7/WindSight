import { Database, ExternalLink, ShieldAlert } from 'lucide-react';
import { CutoffControl, CutoffHint } from '../components/Controls';
import { ErrorState, LoadingState } from '../components/States';
import { useCutoffParams } from '../context/CutoffContext';
import { useApi } from '../hooks/useApi';
import { formatCount, formatPct, originLabel, statusMeta } from '../lib/format';
import type { DataQualityResponse } from '../types';

interface MethodologyResponse {
  cutoff: { time: string; day_offset: number; timezone: string; label: string; description: string };
  timezone: { business: string; canonical: string; note: string };
  definitions: { term: string; meaning: string }[];
  selection_rule: string;
  matching_rule: string;
  error_convention: string;
  metrics: Record<string, string>;
  mape_limitation: string;
  missing_data: string;
  datasets: { name: string; role: string; docs: string }[];
  assumptions: string[];
}

const STATUS_ORDER = [
  'matched',
  'missing_actual',
  'missing_eligible_forecast',
  'missing_forecast_and_actual',
];

export default function Methodology() {
  const cutoffParams = useCutoffParams();
  const methodology = useApi<MethodologyResponse>('/api/methodology');
  const quality = useApi<DataQualityResponse>('/api/data-quality', cutoffParams);

  return (
    <div className="space-y-6">
      <header className="card p-5">
        <p className="label-caps">Methodology &amp; data quality</p>
        <h1 className="mt-1 text-xl font-semibold text-ink-900 sm:text-2xl">
          How the numbers are produced
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-muted">
          Every rule below is implemented in the backend and covered by automated tests. Nothing on
          the dashboard is hand-written: metrics are computed from retrieved source records only.
        </p>
        <div className="mt-4 max-w-xl">
          <CutoffControl id="methodology-cutoff" />
          <CutoffHint description={methodology.data?.cutoff.description} />
        </div>
      </header>

      {methodology.loading ? <LoadingState label="Loading methodology…" /> : null}
      {methodology.error ? (
        <ErrorState message={methodology.error.message} code={methodology.error.code} onRetry={methodology.reload} />
      ) : null}

      {methodology.data ? (
        <>
          <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <article className="card">
              <div className="card-header">
                <h2 className="text-sm font-semibold text-ink-900">Source datasets</h2>
              </div>
              <div className="space-y-4 p-5">
                {methodology.data.datasets.map((dataset) => (
                  <div key={dataset.name} className="flex items-start gap-3">
                    <Database className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
                    <div>
                      <p className="text-sm font-semibold text-ink-900">{dataset.name}</p>
                      <p className="text-sm text-muted">{dataset.role}</p>
                      <a
                        href={dataset.docs}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 inline-flex items-center gap-1 text-xs text-info underline"
                      >
                        Official documentation <ExternalLink className="h-3 w-3" aria-hidden="true" />
                      </a>
                    </div>
                  </div>
                ))}
                <p className="text-xs text-muted">
                  Both endpoints are public and require no API key. Retrieval is windowed and cached;
                  the provenance panel on the overview shows when the data was fetched.
                </p>
              </div>
            </article>

            <article className="card">
              <div className="card-header">
                <h2 className="text-sm font-semibold text-ink-900">Key definitions</h2>
              </div>
              <div className="space-y-4 p-5">
                {methodology.data.definitions.map((definition) => (
                  <div key={definition.term}>
                    <p className="text-sm font-semibold text-ink-900">{definition.term}</p>
                    <p className="text-sm text-muted">{definition.meaning}</p>
                  </div>
                ))}
                <div>
                  <p className="text-sm font-semibold text-ink-900">Timezones</p>
                  <p className="text-sm text-muted">{methodology.data.timezone.note}</p>
                </div>
              </div>
            </article>
          </section>

          <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <article className="card">
              <div className="card-header">
                <h2 className="text-sm font-semibold text-ink-900">Forecast selection rule</h2>
              </div>
              <div className="space-y-3 p-5 text-sm text-ink-800">
                <p>{methodology.data.selection_rule}</p>
                <div className="rounded-md border border-line bg-surface-alt p-3 font-mono text-xs leading-relaxed text-ink-800">
                  eligible = [f for f in candidates if f.publishTime &lt;= cutoff]
                  <br />
                  selected = max(eligible, key=publishTime) if eligible else None
                </div>
                <p className="text-muted">{methodology.data.matching_rule}</p>
              </div>
            </article>

            <article className="card">
              <div className="card-header">
                <h2 className="text-sm font-semibold text-ink-900">Metrics &amp; conventions</h2>
              </div>
              <div className="space-y-3 p-5 text-sm text-ink-800">
                <p className="font-mono text-xs text-ink-800">{methodology.data.error_convention}</p>
                <dl className="space-y-2">
                  {Object.entries(methodology.data.metrics).map(([name, formula]) => (
                    <div key={name}>
                      <dt className="text-xs font-semibold uppercase tracking-wide text-muted">{name}</dt>
                      <dd className="font-mono text-xs text-ink-800">{formula}</dd>
                    </div>
                  ))}
                </dl>
                <div className="rounded-md border border-warn/30 bg-warn/5 p-3 text-xs text-warn">
                  <ShieldAlert className="mb-1 h-4 w-4" aria-hidden="true" />
                  {methodology.data.mape_limitation}
                </div>
              </div>
            </article>
          </section>

          <section className="card">
            <div className="card-header">
              <h2 className="text-sm font-semibold text-ink-900">Missing data treatment</h2>
            </div>
            <div className="p-5 text-sm text-ink-800">{methodology.data.missing_data}</div>
          </section>

          <section className="card">
            <div className="card-header">
              <h2 className="text-sm font-semibold text-ink-900">Documented assumptions</h2>
            </div>
            <ul className="list-disc space-y-2 p-5 pl-9 text-sm text-ink-800">
              {methodology.data.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </section>
        </>
      ) : null}

      <section className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-ink-900">Data quality</h2>
            <p className="text-sm text-muted">
              Coverage, exclusions and provenance for the current cutoff selection.
            </p>
          </div>
        </div>

        {quality.loading ? <LoadingState label="Loading data-quality report…" /> : null}
        {quality.error ? (
          <ErrorState message={quality.error.message} code={quality.error.code} onRetry={quality.reload} />
        ) : null}

        {quality.data ? (
          <div className="space-y-4">
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <QualityStat label="Expected intervals" value={formatCount(quality.data.coverage.expected)} />
              <QualityStat label="Matched intervals" value={formatCount(quality.data.coverage.matched)} />
              <QualityStat label="Coverage" value={formatPct(quality.data.coverage.coverage_pct)} />
              <QualityStat
                label="Excluded source records"
                value={formatCount(
                  Object.values(quality.data.record_exclusions).reduce((a, b) => a + b, 0),
                )}
              />
            </section>

            <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <article className="card">
                <div className="card-header">
                  <h3 className="text-sm font-semibold text-ink-900">Interval status</h3>
                  <span className="text-xs text-muted">{quality.data.cutoff.label}</span>
                </div>
                <div className="table-scroll">
                  <table className="table-base">
                    <thead>
                      <tr>
                        <th scope="col">Status</th>
                        <th scope="col" className="text-right">Intervals</th>
                      </tr>
                    </thead>
                    <tbody>
                      {STATUS_ORDER.map((status) => {
                        const meta = statusMeta(status);
                        const count = quality.data?.coverage.status_counts[status] ?? 0;
                        return (
                          <tr key={status}>
                            <td>
                              <span className={`inline-block rounded border px-2 py-0.5 text-xs ${meta.className}`}>
                                {meta.label}
                              </span>
                              <span className="ml-2 font-mono text-[11px] text-muted">{status}</span>
                            </td>
                            <td className="text-right tabular-nums">{formatCount(count)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </article>

              <article className="card">
                <div className="card-header">
                  <h3 className="text-sm font-semibold text-ink-900">Provenance</h3>
                  <span className="rounded-full border border-line px-2.5 py-1 text-xs text-muted">
                    {originLabel(quality.data.provenance.origin)}
                  </span>
                </div>
                <dl className="space-y-3 p-5 text-sm">
                  <Row label="Origin detail" value={quality.data.provenance.origin_detail ?? '—'} />
                  <Row label="Retrieved at" value={quality.data.provenance.retrieved_at ?? '—'} />
                  <Row label="Actual records" value={formatCount(quality.data.provenance.actual_records)} />
                  <Row label="Forecast records" value={formatCount(quality.data.provenance.forecast_records)} />
                  <Row label="Excluded records" value={formatCount(quality.data.provenance.excluded_records)} />
                  <Row
                    label="Forecast publications used"
                    value={formatCount(quality.data.distinct_selected_publish_times)}
                  />
                  <Row
                    label="Late-forecast exclusions"
                    value={formatCount(quality.data.late_forecast_excluded_intervals)}
                  />
                </dl>
              </article>
            </section>

            <article className="card">
              <div className="card-header">
                <h3 className="text-sm font-semibold text-ink-900">Rejection reasons</h3>
              </div>
              <div className="p-5 text-sm text-ink-800">
                {Object.keys(quality.data.record_exclusions).length === 0 ? (
                  <p className="text-muted">
                    No source records were rejected during normalisation for this dataset.
                  </p>
                ) : (
                  <ul className="list-disc space-y-1 pl-5">
                    {Object.entries(quality.data.record_exclusions).map(([reason, count]) => (
                      <li key={reason}>
                        <span className="font-mono text-xs">{reason}</span> — {formatCount(count)} record(s)
                      </li>
                    ))}
                  </ul>
                )}
                {Object.keys(quality.data.interval_reasons).length ? (
                  <div className="mt-4 border-t border-line pt-4">
                    <p className="label-caps">Intervals without a match</p>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                      {Object.entries(quality.data.interval_reasons).map(([reason, count]) => (
                        <li key={reason}>
                          <span className="font-mono text-xs">{reason}</span> — {formatCount(count)} interval(s)
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            </article>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function QualityStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card p-4">
      <p className="label-caps">{label}</p>
      <p className="mt-2 text-xl font-semibold text-ink-900">{value}</p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium text-ink-900">{value}</dd>
    </div>
  );
}
