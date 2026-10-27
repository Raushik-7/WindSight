import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { ACCURACY, FORECASTS, OVERVIEW } from './fixtures';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

describe('Application shell', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('/api/forecasts')) return Promise.resolve(jsonResponse(FORECASTS));
        if (url.includes('/api/accuracy')) return Promise.resolve(jsonResponse(ACCURACY));
        return Promise.resolve(jsonResponse(OVERVIEW));
      }),
    );
  });

  it('identifies the product, period and primary navigation', async () => {
    render(<App />);
    expect(screen.getByText('WindSight')).toBeInTheDocument();
    expect(screen.getByText('01–31 January 2026')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /overview/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /forecast explorer/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /accuracy analysis/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /methodology/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /about the developer/i })).toBeInTheDocument();
    expect(await screen.findByText('Mean absolute error')).toBeInTheDocument();
  });

  it('navigates to the forecast explorer', async () => {
    render(<App />);
    await screen.findByText('Mean absolute error');
    await userEvent.click(screen.getByRole('link', { name: /forecast explorer/i }));
    expect(await screen.findByText('Interval detail')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/explorer');
  });

  it('keeps the evaluation period visible while navigating', async () => {
    render(<App />);
    await userEvent.click(screen.getByRole('link', { name: /about the developer/i }));
    expect(await screen.findByText('Raushik Gupta')).toBeInTheDocument();
    expect(screen.getAllByText('01–31 January 2026').length).toBeGreaterThan(0);
  });
});
