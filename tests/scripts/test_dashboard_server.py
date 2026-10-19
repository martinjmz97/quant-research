"""Tests for the round-trip close-reason breakdown in dashboard_server.py.

Added alongside the close_reason field in shadow_quote_live.py: a live
claim ("half the fills ride to resolution") turned out to be
unverifiable from round_trips.jsonl alone, since nothing distinguished
an actively-closed trip from one that rode to the terminal payout. This
covers the aggregation that makes that distinction visible, plus the
"unknown" bucket for round trips logged before this field existed (and
the hand-backfilled MLB/WNBA entries, which predate it too).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import dashboard_server as ds  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "STATE_PATH", tmp_path / "shadow_state.json")
    monkeypatch.setattr(ds, "ROUND_TRIPS_PATH", tmp_path / "round_trips.jsonl")
    monkeypatch.setattr(ds, "RESOLVED_GAMES_PATH", tmp_path / "resolved_games.jsonl")
    monkeypatch.setattr(ds, "TRACKED_MARKETS_PATH", tmp_path / "tracked_markets.json")


def _write_round_trips(records):
    with ds.ROUND_TRIPS_PATH.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


class TestReasonStats:
    def test_empty_when_no_round_trips(self):
        payload = ds.build_payload()
        assert payload["reason_stats"] == {}

    def test_buckets_by_close_reason(self):
        _write_round_trips([
            {"pnl": 1.0, "close_reason": "organic"},
            {"pnl": -2.0, "close_reason": "organic"},
            {"pnl": -5.0, "close_reason": "resolution_forced_close"},
        ])
        stats = ds.build_payload()["reason_stats"]
        assert stats["organic"]["n"] == 2
        assert stats["organic"]["pnl_sum"] == pytest.approx(-1.0)
        assert stats["organic"]["pnl_mean"] == pytest.approx(-0.5)
        assert stats["resolution_forced_close"]["n"] == 1
        assert stats["resolution_forced_close"]["pnl_mean"] == pytest.approx(-5.0)

    def test_missing_close_reason_is_unknown(self):
        # round trips logged before this field existed, or hand-backfilled
        _write_round_trips([{"pnl": 0.02, "backfilled": True}])
        stats = ds.build_payload()["reason_stats"]
        assert stats["unknown"]["n"] == 1
        assert stats["unknown"]["pnl_sum"] == pytest.approx(0.02)
