import pytest

from ingestion.polymarket.history import chunk_windows, fetch_all_trades, fetch_price_history
from polymarket.models.clob.price_history import PriceHistoryPoint


class TestChunkWindows:
    def test_splits_into_equal_chunks_when_evenly_divisible(self):
        assert list(chunk_windows(0, 30, 10)) == [(0, 10), (10, 20), (20, 30)]

    def test_last_chunk_is_shorter_when_not_evenly_divisible(self):
        assert list(chunk_windows(0, 25, 10)) == [(0, 10), (10, 20), (20, 25)]

    def test_single_chunk_when_range_smaller_than_chunk_size(self):
        assert list(chunk_windows(0, 5, 10)) == [(0, 5)]

    def test_empty_when_start_equals_end(self):
        assert list(chunk_windows(10, 10, 10)) == []

    def test_rejects_non_positive_chunk_seconds(self):
        with pytest.raises(ValueError):
            list(chunk_windows(0, 10, 0))


class _StubPublicClient:
    """Records each get_price_history call and returns canned per-window data."""

    def __init__(self, points_by_window):
        self.points_by_window = points_by_window
        self.calls = []

    def get_price_history(self, *, token_id, start_ts, end_ts, fidelity):
        self.calls.append((start_ts, end_ts))
        return self.points_by_window[(start_ts, end_ts)]

    def list_trades(self, *, market, page_size):
        raise NotImplementedError


class TestFetchPriceHistory:
    def test_stitches_chunks_together_in_order(self):
        client = _StubPublicClient(
            {
                (0, 10): [PriceHistoryPoint(t=2, p=0.5), PriceHistoryPoint(t=8, p=0.6)],
                (10, 20): [PriceHistoryPoint(t=12, p=0.7)],
            }
        )
        result = fetch_price_history(client, token_id="x", start_ts=0, end_ts=20, chunk_seconds=10)
        assert [p.t for p in result] == [2, 8, 12]
        assert client.calls == [(0, 10), (10, 20)]

    def test_dedupes_boundary_point_returned_by_both_adjacent_chunks(self):
        client = _StubPublicClient(
            {
                (0, 10): [PriceHistoryPoint(t=10, p=0.5)],
                (10, 20): [PriceHistoryPoint(t=10, p=0.5), PriceHistoryPoint(t=15, p=0.55)],
            }
        )
        result = fetch_price_history(client, token_id="x", start_ts=0, end_ts=20, chunk_seconds=10)
        assert [p.t for p in result] == [10, 15]

    def test_single_window_when_range_fits_default_chunk_size(self):
        client = _StubPublicClient({(0, 100): [PriceHistoryPoint(t=50, p=0.5)]})
        result = fetch_price_history(client, token_id="x", start_ts=0, end_ts=100)
        assert len(client.calls) == 1
        assert [p.t for p in result] == [50]


class TestFetchAllTrades:
    def test_flattens_paginator_items(self):
        class _FakePaginator:
            def iter_items(self):
                yield "trade-1"
                yield "trade-2"

        class _StubTradesClient:
            def list_trades(self, *, market, page_size):
                assert market == ["cond-1"]
                return _FakePaginator()

        result = fetch_all_trades(_StubTradesClient(), condition_id="cond-1")
        assert result == ["trade-1", "trade-2"]
