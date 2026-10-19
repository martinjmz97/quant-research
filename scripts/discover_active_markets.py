"""Refresh the shared tracked-markets config that record_orderbook.py and
shadow_quote_live.py both read, by scanning every in-scope league
(soccer, NFL, MLB, NHL, NBA, WNBA) for currently-active single-game
moneyline markets.

Meant to run periodically (cron/launchd, every 15-30min is reasonable —
new games don't start more often than that) rather than continuously.
Each run MERGES this run's discovered tokens into the existing file
(union by asset_id) rather than overwriting it — see
merge_tracked_tokens() in active_markets.py for why: overwriting once
lost every previously-tracked token the moment discovery legitimately
found zero currently-active games, and a shadow_quote_live.py restart
landing at exactly that point came up completely empty. See
src/ingestion/polymarket/active_markets.py for the discovery/filtering/
merge logic itself (kept there, not here, so it's importable and
unit-tested without hitting the network).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from polymarket.clients.public import PublicClient

from ingestion.polymarket.active_markets import discover_tracked_tokens, merge_tracked_tokens

OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "polymarket" / "orderbook_live" / "tracked_markets.json"


def main() -> None:
    client = PublicClient()
    now = dt.datetime.now(dt.timezone.utc)
    tokens = discover_tracked_tokens(client, now)

    existing = json.loads(OUT_PATH.read_text())["tokens"] if OUT_PATH.exists() else []
    merged = merge_tracked_tokens(existing, tokens)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"generated_at": now.isoformat(), "tokens": merged}, indent=2))
    print(f"[{now.isoformat()}] discovered {len(tokens)} newly-active, {len(merged)} total tracked -> {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
