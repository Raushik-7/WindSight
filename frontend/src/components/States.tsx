import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react';
import type { ReactNode } from 'react';

export function LoadingState({ label = 'Loading data…' }: { label?: string }) {
  return (
    <div
      className="card flex items-center justify-center gap-3 px-6 py-12 text-muted"
      role="status"
      aria-live="polite"
    >
      <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  code,
}: {
  message: string;
  onRetry?: () => void;
  code?: string;
}) {
  return (
    <div
      className="card border-danger/30 bg-danger/5 px-6 py-8"
      role="alert"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-danger" aria-hidden="true" />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-danger">Could not load data</h2>
          <p className="mt-1 break-words text-sm text-ink-800">{message}</p>
          {code ? <p className="mt-1 font-mono text-xs text-muted">Error code: {code}</p> : null}
          {onRetry ? (
            <button type="button" className="btn-secondary mt-4" onClick={onRetry}>
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Retry
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="card px-6 py-10 text-center">
      <Inbox className="mx-auto h-6 w-6 text-muted" aria-hidden="true" />
      <h2 className="mt-3 text-sm font-semibold text-ink-900">{title}</h2>
      <p className="mx-auto mt-1 max-w-2xl text-sm text-muted">{description}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
