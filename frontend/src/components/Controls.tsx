import { Download, Info } from 'lucide-react';
import { exportUrl } from '../lib/api';
import { useCutoff, useCutoffParams } from '../context/CutoffContext';
import type { QueryParams } from '../lib/api';

const CUTOFF_TIMES = [
  '07:30',
  '09:30',
  '11:30',
  '12:00',
  '13:00',
  '15:30',
  '18:30',
];

/**
 * Decision-cutoff control. Every change re-queries the backend so the
 * selection and all metrics are recomputed, not merely relabelled.
 */
export function CutoffControl({ id = 'cutoff' }: { id?: string }) {
  const { time, offsetDays, setTime, setOffsetDays } = useCutoff();

  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-time`} className="label-caps">
          Decision cutoff
        </label>
        <select
          id={`${id}-time`}
          className="input"
          value={time}
          onChange={(event) => setTime(event.target.value)}
        >
          {!CUTOFF_TIMES.includes(time) ? <option value={time}>{time}</option> : null}
          {CUTOFF_TIMES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-offset`} className="label-caps">
          Relative to delivery date
        </label>
        <select
          id={`${id}-offset`}
          className="input"
          value={offsetDays}
          onChange={(event) => setOffsetDays(Number(event.target.value) as -1 | 0)}
        >
          <option value={-1}>Day before (D-1)</option>
          <option value={0}>Same day (D)</option>
        </select>
      </div>
    </div>
  );
}

/** Explanatory line shown next to the cutoff control. */
export function CutoffHint({ description }: { description?: string }) {
  if (!description) return null;
  return (
    <p className="mt-2 flex items-start gap-2 text-xs text-muted">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{description}</span>
    </p>
  );
}

/** CSV export button bound to the current query parameters. */
export function ExportButton({ params, label = 'Export CSV' }: { params: QueryParams; label?: string }) {
  return (
    <a className="btn-secondary" href={exportUrl(params)} download>
      <Download className="h-4 w-4" aria-hidden="true" />
      {label}
    </a>
  );
}

/** Convenience hook returning both the control params and their labels. */
export function useCutoffQuery() {
  return useCutoffParams();
}
