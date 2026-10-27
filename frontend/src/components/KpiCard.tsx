import type { ReactNode } from 'react';

interface Props {
  title: string;
  value: string;
  unit?: string;
  detail?: string;
  hint?: string;
  tone?: 'neutral' | 'positive' | 'negative' | 'warning';
  children?: ReactNode;
}

const TONE_CLASS: Record<string, string> = {
  neutral: 'text-ink-900',
  positive: 'text-accent-strong',
  negative: 'text-danger',
  warning: 'text-warn',
};

/**
 * KPI card: name, value, unit, a definition hint, and the observation count
 * or coverage the number was computed from.
 */
export default function KpiCard({
  title,
  value,
  unit,
  detail,
  hint,
  tone = 'neutral',
  children,
}: Props) {
  return (
    <article className="card flex flex-col p-4 sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <h3 className="label-caps">{title}</h3>
        {hint ? (
          <span
            className="grid h-4 w-4 shrink-0 place-items-center rounded-full border border-line-strong text-[10px] text-muted"
            title={hint}
            aria-label={hint}
          >
            ?
          </span>
        ) : null}
      </div>

      <p className={`mt-3 text-2xl font-semibold tracking-tight sm:text-3xl ${TONE_CLASS[tone]}`}>
        {value}
        {unit ? <span className="ml-1 text-sm font-normal text-muted">{unit}</span> : null}
      </p>

      {detail ? <p className="mt-2 text-xs text-muted">{detail}</p> : null}
      {children}
    </article>
  );
}
