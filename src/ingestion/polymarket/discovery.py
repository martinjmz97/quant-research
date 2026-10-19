"""Discover Polymarket sports events across every league.

Tag id 1 is the "Sports" master tag (verified live against the Gamma API —
see POLYMARKET_MM.md) and covers every league returned by
``PublicClient.get_sports()``, so a single tag filter replaces looping over
hundreds of per-league tag ids.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime

from polymarket.clients.public import PublicClient
from polymarket.models.gamma.event import Event

SPORTS_TAG_ID = 1
SOCCER_TAG_ID = 100350  # verified live: client.get_tag(id='100350').label == 'Soccer'


def iter_sports_events(
    client: PublicClient,
    *,
    closed: bool = True,
    page_size: int = 100,
    volume_min: float | None = None,
    end_date_min: str | datetime | None = None,
    additional_tag_id: int | None = None,
    page_delay: float = 0.0,
) -> Iterator[Event]:
    """Yield every sports event matching the filters, across all leagues.

    ``closed=True`` (the default) returns settled events, which is what a
    historical/backtest ingestion wants. Pass ``closed=False`` for the
    currently open/live slate.

    ``volume_min``/``end_date_min`` are filtered server-side by the Gamma
    API — an unfiltered pull across every league is dominated by dead,
    near-zero-volume markets, and even filtered to >$100k volume and the
    last 13 months the space is still tens of thousands of events (props/
    lines multiply fast — one event per game, many markets per event).
    Filtering at the source is much cheaper than fetching everything and
    discarding it client-side, but it does not bound the problem to
    "fast" on its own — see POLYMARKET_MM.md.

    ``additional_tag_id`` narrows to one league/sport on top of the sports
    master tag (``tag_match='all'``) — e.g. ``SOCCER_TAG_ID`` to scope to
    soccer only, which is the first concrete sport this project targets.

    ``page_delay`` sleeps that many seconds after each page's worth of
    items (approximated by ``page_size`` items yielded, since the
    paginator only exposes item-level iteration) — the Gamma API rate-
    limits this endpoint (undocumented, empirically ~6 pages/s triggers
    ``RateLimitError``; ~2 pages/s sustained for 90s did not), unlike the
    documented CLOB limits in POLYMARKET_MM.md. Default 0 preserves the
    unthrottled behavior for tests/small pulls.
    """
    tag_ids = SPORTS_TAG_ID if additional_tag_id is None else [SPORTS_TAG_ID, additional_tag_id]
    paginator = client.list_events(
        tag_ids=tag_ids,
        tag_match="all" if additional_tag_id is not None else None,
        closed=closed,
        page_size=page_size,
        volume_min=volume_min,
        end_date_min=end_date_min,
    )
    for i, event in enumerate(paginator.iter_items(), start=1):
        yield event
        if page_delay and i % page_size == 0:
            time.sleep(page_delay)
