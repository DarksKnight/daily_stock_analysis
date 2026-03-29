import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { marketReviewApi } from '../../api/marketReview';
import MarketReviewPage from '../MarketReviewPage';

vi.mock('../../api/marketReview', () => ({
  marketReviewApi: {
    getToday: vi.fn(),
    run: vi.fn(),
    getStatus: vi.fn(),
  },
}));

describe('MarketReviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('loads today review on first render and hides report when selected region has none', async () => {
    vi.mocked(marketReviewApi.getToday)
      .mockResolvedValueOnce({
        region: 'cn',
        tradeDate: '2026-03-29',
        report: '# 今日A股复盘',
        createdAt: '2026-03-29T15:00:00',
      })
      .mockResolvedValueOnce({
        region: 'hk',
        tradeDate: null,
        report: null,
        createdAt: null,
      });

    render(
      <MemoryRouter>
        <MarketReviewPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('今日A股复盘')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '美股' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'A股+美股' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '全部' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '港股' }));

    await waitFor(() => {
      expect(vi.mocked(marketReviewApi.getToday)).toHaveBeenLastCalledWith('hk');
      expect(screen.queryByText('今日A股复盘')).not.toBeInTheDocument();
    });
  });

  it('refreshes today review from database after a successful run', async () => {
    vi.useFakeTimers();
    vi.mocked(marketReviewApi.getToday)
      .mockResolvedValueOnce({
        region: 'cn',
        tradeDate: null,
        report: null,
        createdAt: null,
      })
      .mockResolvedValueOnce({
        region: 'cn',
        tradeDate: '2026-03-29',
        report: '# 新的A股复盘',
        createdAt: '2026-03-29T15:30:00',
      });
    vi.mocked(marketReviewApi.run).mockResolvedValue({
      taskId: 'task-1',
      status: 'pending',
      region: 'cn',
      createdAt: '2026-03-29T15:00:00',
    });
    vi.mocked(marketReviewApi.getStatus).mockResolvedValue({
      taskId: 'task-1',
      status: 'completed',
      region: 'cn',
      report: null,
      error: null,
      createdAt: '2026-03-29T15:00:00',
      completedAt: '2026-03-29T15:30:00',
    });

    render(
      <MemoryRouter>
        <MarketReviewPage />
      </MemoryRouter>,
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(vi.mocked(marketReviewApi.getToday)).toHaveBeenCalledWith('cn');

    fireEvent.click(screen.getByRole('button', { name: '开始复盘' }));

    await act(async () => {
      await Promise.resolve();
    });

    expect(vi.mocked(marketReviewApi.run)).toHaveBeenCalledWith('cn');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(vi.mocked(marketReviewApi.getStatus)).toHaveBeenCalledWith('task-1');
    expect(vi.mocked(marketReviewApi.getToday)).toHaveBeenLastCalledWith('cn');
    expect(screen.getByText('新的A股复盘')).toBeInTheDocument();
  });
});
