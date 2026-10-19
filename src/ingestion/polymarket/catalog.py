"""Build the catalog of every Polymarket sports market, across all leagues.

One row per market (an event can bundle many binary markets — e.g. a
"Champion" event has one yes/no market per team). Columns include
per-market ``min_tick_size``/``min_order_size`` straight from the API,
resolving two of the three open questions logged in POLYMARKET_MM.md
(minimum order size; tick size varies per market — no separate call
needed, it rides along with the market listing).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from polymarket.clients.public import PublicClient
from polymarket.models.gamma.event import Event

from ingestion.polymarket.discovery import iter_sports_events

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "polymarket"
CATALOG_PATH = RAW_DIR / "sports_markets_catalog.parquet"


def event_to_rows(event: Event) -> list[dict]:
    """Flatten one event into one row per market. Pure function, no
    network — the piece worth unit-testing on its own."""
    sports = event.sports
    rows = []
    for market in event.markets:
        metrics = market.metrics
        resolution = market.resolution
        trading = market.trading
        rows.append(
            {
                "event_id": event.id,
                "event_title": event.title,
                "event_slug": event.slug,
                "sport": sports.sport.sport if sports.sport else None,
                "league": sports.series_slug,
                "home_team": sports.home_team_name,
                "away_team": sports.away_team_name,
                "score_at_snapshot": sports.score,
                "period_at_snapshot": sports.period,
                "market_id": market.id,
                "condition_id": market.condition_id,
                "question": market.question,
                "yes_token_id": market.outcomes.yes.token_id,
                "no_token_id": market.outcomes.no.token_id,
                "yes_price": float(market.outcomes.yes.price) if market.outcomes.yes.price is not None else None,
                "volume": float(metrics.volume) if metrics and metrics.volume is not None else None,
                "liquidity": float(metrics.liquidity) if metrics and metrics.liquidity is not None else None,
                "uma_resolution_status": (
                    resolution.uma_resolution_status.value
                    if resolution and resolution.uma_resolution_status
                    else None
                ),
                "min_tick_size": float(trading.minimum_tick_size) if trading and trading.minimum_tick_size is not None else None,
                "min_order_size": float(trading.minimum_order_size) if trading and trading.minimum_order_size is not None else None,
                "start_date": market.state.start_date if market.state else None,
                "end_date": market.state.end_date if market.state else None,
            }
        )
    return rows


def build_catalog(client: PublicClient, *, closed: bool = True, page_size: int = 100) -> pl.DataFrame:
    """Pull every sports market (all leagues) into a single polars
    DataFrame. Network-bound — see tests for the pure flatten logic."""
    rows: list[dict] = []
    for event in iter_sports_events(client, closed=closed, page_size=page_size):
        rows.extend(event_to_rows(event))
    # infer_schema_length=None: default (100 rows) misses type variation
    # that only shows up later — confirmed live, a string league code past
    # row 100 broke inference against an early-inferred null/int column.
    return pl.DataFrame(rows, infer_schema_length=None)


def save_catalog(df: pl.DataFrame, path: Path = CATALOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
