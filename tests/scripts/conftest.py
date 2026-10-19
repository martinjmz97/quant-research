"""Isolate every durable-log path shadow_quote_live.py writes to, for
every test in this directory — autouse so a test doesn't need to know
these paths exist to avoid polluting real project data. Found live:
running the suite once wrote 5 garbage lines into the real
data/raw/polymarket/orderbook_live/round_trips.jsonl, because ordinary
fill-processing tests (TestRequoteLatency etc.) trigger round-trip
closes without being about round trips at all.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import shadow_quote_live as sql  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_durable_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(sql, "ROUND_TRIPS_PATH", tmp_path / "round_trips.jsonl")
    monkeypatch.setattr(sql, "RESOLVED_GAMES_PATH", tmp_path / "resolved_games.jsonl")
    monkeypatch.setattr(sql, "TRACKED_MARKETS_PATH", tmp_path / "tracked_markets.json")
