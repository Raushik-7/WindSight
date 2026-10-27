import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Explorer from '../pages/Explorer';
import { CutoffProvider } from '../context/CutoffContext';
import { FORECASTS } from './fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function renderExplorer() {
  return render(
    <MemoryRouter>
      <CutoffProvider>
        <Explorer />
      </CutoffProvider>
    </MemoryRouter>,
  );
}

describe('Forecast Explorer', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(FORECASTS)));
  });

  it('renders all 48 half-hourly intervals with the selected publication time', async () => {
    renderExplorer();
    await screen.findByText('Interval detail');
    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row');
    expect(rows).toHaveLength(49); // header + 48 intervals
    expect(screen.getAllByText(/14 Jan 2026, 11:30/).length).toBeGreaterThan(0);
    expect(screen.getAllByText('9,500').length).toBeGreaterThan(0);
  });

  it('shows missing values as missing rather than zero', async () => {
    renderExplorer();
    await screen.findByText('Interval detail');
    expect(screen.getByText('No actual')).toBeInTheDocument();
    expect(screen.getByText('No forecast')).toBeInTheDocument();
    expect(screen.getByText('all_forecasts_published_after_cutoff')).toBeInTheDocument();
    // The interval with no actual must not display 0 in the actual column.
    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    const missingActualRow = rows.find((row) => within(row).queryByText('No actual'));
    expect(missingActualRow).toBeDefined();
    const cells = within(missingActualRow as HTMLElement).getAllByRole('cell');
    expect(cells[3]).toHaveTextContent('—');
    expect(cells[3]).not.toHaveTextContent('0');
  });

  it('re-queries the backend when the delivery date changes', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    renderExplorer();
    await screen.findByText('Interval detail');
    expect(String(fetchMock.mock.calls[0][0])).toContain('date=2026-01-15');

    await userEvent.selectOptions(screen.getByLabelText('Delivery date'), '2026-01-20');
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(1));
    expect(String(fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0])).toContain(
      'date=2026-01-20',
    );
  });

  it('sorts intervals by absolute error when the column header is used', async () => {
    renderExplorer();
    await screen.findByText('Interval detail');
    await userEvent.click(screen.getByRole('button', { name: /abs error/i }));
    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    // Rows without an error sort last, so the first row must carry a value.
    const firstCells = within(rows[0]).getAllByRole('cell');
    expect(firstCells[5]).toHaveTextContent(/[0-9]/);
  });

  it('disables navigation at the edges of the evaluation period', async () => {
    renderExplorer();
    await screen.findByText('Interval detail');
    // Default date is mid-month, so both directions are available.
    expect(screen.getByRole('button', { name: /previous/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /next/i })).toBeEnabled();

    await userEvent.selectOptions(screen.getByLabelText('Delivery date'), '2026-01-31');
    await waitFor(
      () => expect(screen.getByRole('button', { name: /next/i })).toBeDisabled(),
      { timeout: 5000 },
    );
  });

  it('shows an error state when the backend fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ error: { code: 'source_unavailable', message: 'no data' } }, 503),
      ),
    );
    renderExplorer();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load data');
  });
});
