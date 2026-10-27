/** Display formatting. Values are rounded for display only. */

const MISSING = '—';

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING;
  return value.toLocaleString('en-GB', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatMw(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING;
  return `${formatNumber(value, digits)} MW`;
}

export function formatSignedMw(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING;
  const sign = value > 0 ? '+' : '';
  return `${sign}${formatNumber(value, digits)} MW`;
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING;
  return `${formatNumber(value, digits)}%`;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return MISSING;
  return formatNumber(value, 0);
}

/** Render an ISO instant as a readable local timestamp, falling back to UTC. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  }).format(date);
}

export function formatTimeOnly(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  }).format(date);
}

export function formatDayLabel(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return isoDate;
  return new Intl.DateTimeFormat('en-GB', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
  }).format(date);
}

export interface StatusMeta {
  label: string;
  className: string;
  hint: string;
}

const STATUS_META: Record<string, StatusMeta> = {
  matched: {
    label: 'Matched',
    className: 'bg-accent/10 text-accent-strong border-accent/30',
    hint: 'An eligible forecast and actual outturn are both present.',
  },
  missing_actual: {
    label: 'No actual',
    className: 'bg-warn/10 text-warn border-warn/30',
    hint: 'A forecast exists but actual outturn is missing for this interval.',
  },
  missing_eligible_forecast: {
    label: 'No forecast',
    className: 'bg-warn/10 text-warn border-warn/30',
    hint: 'No forecast was published before the decision cutoff.',
  },
  missing_forecast_and_actual: {
    label: 'No data',
    className: 'bg-danger/10 text-danger border-danger/30',
    hint: 'Neither an eligible forecast nor actual outturn is available.',
  },
};

export function statusMeta(status: string): StatusMeta {
  return (
    STATUS_META[status] ?? {
      label: status,
      className: 'bg-surface-alt text-muted border-line',
      hint: 'Unknown status.',
    }
  );
}

/** Human label for a data-origin value from the API. */
export function originLabel(origin: string | null | undefined): string {
  switch (origin) {
    case 'live':
      return 'Live Elexon fetch';
    case 'cache':
      return 'Cached fetch';
    case 'cache_stale':
      return 'Cached (stale)';
    case 'snapshot':
      return 'Stored snapshot';
    case 'mixed':
      return 'Mixed sources';
    default:
      return 'Unknown';
  }
}

/* Recharts tooltip formatters (typed loosely so they satisfy the library's
   generic Formatter signature while still rendering missing values as "—"). */
export function tooltipMw(value: unknown, name: unknown): [string, string] {
  return [formatMw(typeof value === 'number' ? value : null), String(name ?? '')];
}

export function tooltipSignedMw(value: unknown, name: unknown): [string, string] {
  return [formatSignedMw(typeof value === 'number' ? value : null), String(name ?? '')];
}

export function tooltipCount(value: unknown, name: unknown): [string, string] {
  return [formatCount(typeof value === 'number' ? value : null), String(name ?? '')];
}
