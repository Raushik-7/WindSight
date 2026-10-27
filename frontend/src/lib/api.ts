import type { ApiErrorBody } from '../types';

/** Structured API error carrying the backend's stable error code. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export type QueryParams = Record<string, string | number | boolean | undefined | null>;

/**
 * Base URL of the WindSight API.
 *
 * Empty by default: in development Vite proxies `/api` to the backend and the
 * nginx container does the same, so relative URLs are correct. When the
 * frontend is hosted separately from the API (e.g. Vercel + Render), set
 * `VITE_API_BASE_URL` at build time to the backend origin.
 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');

export function apiPath(path: string): string {
  return `${API_BASE}${path}`;
}

export function buildQuery(params?: QueryParams): string {
  if (!params) return '';
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : '';
}

export async function apiGet<T>(
  path: string,
  params?: QueryParams,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${apiPath(path)}${buildQuery(params)}`, {
    signal,
    headers: { Accept: 'application/json' },
  });

  const contentType = response.headers.get('content-type') ?? '';
  if (!response.ok) {
    let code = 'request_failed';
    let message = `Request failed with status ${response.status}`;
    if (contentType.includes('application/json')) {
      try {
        const body = (await response.json()) as ApiErrorBody;
        if (body?.error) {
          code = body.error.code;
          message = body.error.message;
        }
      } catch {
        /* keep the generic message */
      }
    }
    throw new ApiError(response.status, code, message);
  }

  if (contentType.includes('application/json')) {
    return (await response.json()) as T;
  }
  throw new ApiError(response.status, 'unexpected_content_type', 'Unexpected response type');
}

/** URL for the CSV export of the current analytical selection. */
export function exportUrl(params?: QueryParams): string {
  return apiPath(`/api/export${buildQuery(params)}`);
}
