import { describe, expect, it, vi } from 'vitest';
import { ApiError, apiGet, buildQuery, exportUrl } from '../lib/api';
import {
  formatMw,
  formatPct,
  formatSignedMw,
  originLabel,
  statusMeta,
  tooltipMw,
} from '../lib/format';

describe('buildQuery', () => {
  it('drops empty values and encodes the rest', () => {
    expect(buildQuery({ from: '2026-01-01', to: undefined, cutoff: '', n: 2 })).toBe(
      '?from=2026-01-01&n=2',
    );
    expect(buildQuery()).toBe('');
  });

  it('builds the CSV export URL', () => {
    expect(exportUrl({ from: '2026-01-01', to: '2026-01-02' })).toBe(
      '/api/export?from=2026-01-01&to=2026-01-02',
    );
  });
});

describe('apiGet', () => {
  it('returns the parsed JSON payload on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    );
    await expect(apiGet('/api/health')).resolves.toEqual({ ok: true });
  });

  it('surfaces the backend error code and message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: 'source_unavailable', message: 'Live Elexon data unavailable' },
          }),
          { status: 503, headers: { 'content-type': 'application/json' } },
        ),
      ),
    );
    const failure = await apiGet('/api/overview').catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).code).toBe('source_unavailable');
    expect((failure as ApiError).status).toBe(503);
    expect((failure as ApiError).message).toContain('Live Elexon data unavailable');
  });

  it('rejects non-JSON success bodies', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('<html></html>', { status: 200, headers: { 'content-type': 'text/html' } }),
      ),
    );
    await expect(apiGet('/api/health')).rejects.toMatchObject({
      code: 'unexpected_content_type',
    });
  });
});

describe('display formatting', () => {
  it('renders missing values as an em dash, never as zero', () => {
    expect(formatMw(null)).toBe('—');
    expect(formatMw(undefined)).toBe('—');
    expect(formatPct(null)).toBe('—');
    expect(formatSignedMw(null)).toBe('—');
    expect(tooltipMw(undefined, 'Actual')).toEqual(['—', 'Actual']);
  });

  it('keeps signs on signed values', () => {
    expect(formatSignedMw(1500)).toBe('+1,500 MW');
    expect(formatSignedMw(-2500)).toBe('-2,500 MW');
    expect(formatMw(9500)).toBe('9,500 MW');
    expect(formatPct(19.74)).toBe('19.7%');
  });

  it('labels interval statuses with accessible text', () => {
    expect(statusMeta('matched').label).toBe('Matched');
    expect(statusMeta('missing_actual').label).toBe('No actual');
    expect(statusMeta('missing_eligible_forecast').label).toBe('No forecast');
    expect(statusMeta('matched').hint).toBeTruthy();
  });

  it('names data origins honestly', () => {
    expect(originLabel('live')).toBe('Live Elexon fetch');
    expect(originLabel('snapshot')).toBe('Stored snapshot');
    expect(originLabel(null)).toBe('Unknown');
  });
});
