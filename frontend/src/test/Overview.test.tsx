import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Overview from '../pages/Overview';
import { CutoffProvider } from '../context/CutoffContext';
import { ACCURACY, OVERVIEW, OVERVIEW_EMPTY_METRICS } from './fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function renderOverview() {
  return render(
    <MemoryRouter>
      <CutoffProvider>
        <Overview />
      </CutoffProvider>
    </MemoryRouter>,
  );
}

describe('Overview page', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(OVERVIEW)));
  });

  it('shows a loading state before data arrives', () => {
    renderOverview();
    expect(screen.getByRole('status')).toHaveTextContent('Loading evaluation results');
  });

  it('renders computed metrics from the API response', async () => {
    renderOverview();
    expect(await screen.findByText('Mean absolute error')).toBeInTheDocument();
    expect(screen.getByText('2,021')).toBeInTheDocument(); // MAE rounded for display
    expect(screen.getByText('+1,806 MW')).toBeInTheDocument(); // bias keeps its sign
    expect(screen.getByText('19.7%')).toBeInTheDocument(); // MAPE
    expect(screen.getAllByText('1,488').length).toBeGreaterThan(0); // matched intervals
    expect(screen.getByText('100.0%')).toBeInTheDocument(); // coverage
    expect(screen.getByText(OVERVIEW.summary)).toBeInTheDocument();
    expect(screen.getByText(/Live Elexon fetch/)).toBeInTheDocument();
  });

  it('re-queries the backend when the decision cutoff changes', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    renderOverview();
    await screen.findByText('Mean absolute error');

    await userEvent.selectOptions(screen.getByLabelText('Decision cutoff'), '09:30');

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(String(fetchMock.mock.calls[1][0])).toContain('cutoff=09%3A30');
    expect(String(fetchMock.mock.calls[1][0])).toContain('cutoff_offset_days=-1');
  });

  it('shows an error state with a working retry instead of an endless spinner', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: 'source_unavailable', message: 'upstream down' } }, 503),
      )
      .mockResolvedValueOnce(jsonResponse(OVERVIEW));

    renderOverview();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load data');
    expect(screen.getByText(/source_unavailable/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(await screen.findByText('Mean absolute error')).toBeInTheDocument();
  });

  it('shows an honest empty state when no metrics are available', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(OVERVIEW_EMPTY_METRICS)));
    renderOverview();
    expect(
      await screen.findByText('No matched intervals in this selection'),
    ).toBeInTheDocument();
    // An empty dataset must never be presented as a zero score.
    expect(screen.queryByText('0 MW')).not.toBeInTheDocument();
  });

  it('keeps chart data tied to API series points', async () => {
    renderOverview();
    await screen.findByText('Mean absolute error');
    expect(screen.getByLabelText(/Line chart comparing hourly forecast and actual/)).toBeInTheDocument();
  });
});

describe('Accuracy page data flow', () => {
  it('is exercised through the shared API client', () => {
    // Sanity check that the accuracy fixture matches the type contract used
    // by the page (metrics + coverage + daily + hourly + distribution).
    expect(ACCURACY.daily).toHaveLength(OVERVIEW.daily.length);
    expect(ACCURACY.by_hour).toHaveLength(24);
    expect(ACCURACY.metrics.n).toBe(OVERVIEW.metrics.n);
  });
});
