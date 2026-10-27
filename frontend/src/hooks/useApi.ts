import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, apiGet, type QueryParams } from '../lib/api';

interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
}

/**
 * Minimal data-fetching hook: loading state, structured error state, retry.
 * Re-runs whenever the path or parameters change (filters re-query the backend
 * rather than only relabelling charts).
 */
export function useApi<T>(path: string | null, params?: QueryParams): ApiState<T> & { reload: () => void } {
  const [state, setState] = useState<ApiState<T>>({ data: null, error: null, loading: path !== null });
  const [attempt, setAttempt] = useState(0);
  const controller = useRef<AbortController | null>(null);

  const key = useMemo(() => JSON.stringify([path, params ?? {}]), [path, params]);

  useEffect(() => {
    if (!path) {
      setState({ data: null, error: null, loading: false });
      return undefined;
    }
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    let active = true;

    setState((prev) => ({ ...prev, loading: true, error: null }));
    apiGet<T>(path, params, current.signal)
      .then((data) => {
        if (active) setState({ data, error: null, loading: false });
      })
      .catch((err: unknown) => {
        if (!active || current.signal.aborted) return;
        const apiError =
          err instanceof ApiError
            ? err
            : new ApiError(0, 'network_error', err instanceof Error ? err.message : 'Network request failed');
        setState({ data: null, error: apiError, loading: false });
      });

    return () => {
      active = false;
      current.abort();
    };
    // `key` captures path + params; `attempt` drives manual retries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, reload };
}
