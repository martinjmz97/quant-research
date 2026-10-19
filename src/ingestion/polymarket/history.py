"""Fetch historical price and trade data for a single Polymarket market.

``get_price_history`` rejects windows above an undocumented max size (an
error, not a truncation) — empirically confirmed to reject 30 days but
accept 7 days at ``fidelity=60`` (minute granularity, hourly points). We
chunk under that limit with margin and stitch the pieces back together.
"""

from __future__ import annotations

from collections.abc import Iterator

from polymarket.clients.public import PublicClient
from polymarket.models.clob.price_history import PriceHistoryPoint
from polymarket.models.data.activity import Trade

DEFAULT_CHUNK_SECONDS = 5 * 24 * 60 * 60  # 5 days — margin under the ~7-day empirical limit at fidelity=60


def chunk_windows(start_ts: int, end_ts: int, chunk_seconds: int) -> Iterator[tuple[int, int]]:
    """Split [start_ts, end_ts) into consecutive (start, end) windows of at
    most chunk_seconds each. Pure function, no network — the piece worth
    unit-testing on its own."""
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be positive")
    window_start = start_ts
    while window_start < end_ts:
        window_end = min(window_start + chunk_seconds, end_ts)
        yield window_start, window_end
        window_start = window_end


def fetch_price_history(
    client: PublicClient,
    *,
    token_id: str,
    start_ts: int,
    end_ts: int,
    fidelity: int = 60,
    chunk_seconds: int = DEFAULT_CHUNK_SECONDS,
) -> list[PriceHistoryPoint]:
    """Fetch the full price history over [start_ts, end_ts], chunked to
    respect the API's per-request window limit, deduped and sorted by
    timestamp (adjacent chunks can both return the boundary point)."""
    points: dict[int, PriceHistoryPoint] = {}
    for window_start, window_end in chunk_windows(start_ts, end_ts, chunk_seconds):
        chunk = client.get_price_history(
            token_id=token_id,
            start_ts=window_start,
            end_ts=window_end,
            fidelity=fidelity,
        )
        for point in chunk:
            points[point.t] = point
    return [points[t] for t in sorted(points)]


def fetch_all_trades(
    client: PublicClient,
    *,
    condition_id: str,
    page_size: int = 500,
) -> list[Trade]:
    """Fetch the full trade history for a market."""
    paginator = client.list_trades(market=[condition_id], page_size=page_size)
    return list(paginator.iter_items())
