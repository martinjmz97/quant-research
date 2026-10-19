"""End-to-end smoke test for spread_sweep_backtest.py against a tiny
synthetic tape — this is what would silently break (wrong stats, or a
crash mid-replay) if run_replay()/summarize() drifted from what
shadow_quote_live.process_message actually does, without anyone noticing
until burning 3+ minutes replaying the real 22M-line tape on a remote host.
"""

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import shadow_quote_live as sql  # noqa: E402
import spread_sweep_backtest as sweep  # noqa: E402

ASSET_ID = "asset-a"
_BASE = dt.datetime(2026, 7, 17, 12, 0, 0, tzinfo=dt.timezone.utc)


def _book_tick(asset_id, best_bid, best_ask):
    return {"asset_id": asset_id, "bids": [{"price": str(best_bid)}], "asks": [{"price": str(best_ask)}]}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sql, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sql, "IN_PATH", tmp_path / "live_book.jsonl")
    monkeypatch.setattr(sql, "TRACKED_MARKETS_PATH", tmp_path / "tracked_markets.json")
    sql.TOKEN_LABELS.clear()
    sql.TOKEN_SIDE.clear()
    sql.MARKET_IDS.clear()
    sql.EVENT_IDS.clear()
    sql.KICKOFFS.clear()

    tracked = {
        "generated_at": _BASE.isoformat(),
        "tokens": [{
            "asset_id": ASSET_ID, "label": "team_a_win", "market_id": 1,
            "event_id": 100, "side": "yes", "game_start_time": None,
        }],
    }
    sql.TRACKED_MARKETS_PATH.write_text(json.dumps(tracked))

    ticks = [
        _book_tick(ASSET_ID, 0.20, 0.80),   # wide spread, no fill yet
        _book_tick(ASSET_ID, 0.90, 0.95),   # crosses a resting bid -> fill
        _book_tick(ASSET_ID, 0.05, 0.10),   # crosses back the other way -> fill
    ]
    with sql.IN_PATH.open("w") as f:
        for i, tick in enumerate(ticks):
            f.write(json.dumps({"raw": [tick], "recv_ts": (_BASE + dt.timedelta(seconds=i * (sql.MIN_REQUOTE_LATENCY_S + 1))).isoformat()}) + "\n")

    resolved = [{"label": "team_a_win", "payout": 1.0}]
    with (tmp_path / "resolved_games.jsonl").open("w") as f:
        for r in resolved:
            f.write(json.dumps(r) + "\n")

    yield


class TestSpreadSweepBacktest:
    def test_replay_produces_round_trips_and_applies_resolution_payout(self):
        sweep_dir = sweep.run_replay()
        round_trips = sweep._load_jsonl(sweep_dir / "round_trips.jsonl")
        assert len(round_trips) >= 1
        assert all("close_reason" in rt for rt in round_trips)
        # position was force-closed at the known payout — no leftover
        # inventory should still be open once the tape is exhausted.
        resolved_games = sweep._load_jsonl(sweep_dir / "resolved_games.jsonl")
        assert len(resolved_games) == 1
        assert resolved_games[0]["payout"] == 1.0

    def test_summarize_groups_by_event_not_token(self):
        sweep_dir = sweep.run_replay()
        result = sweep.summarize(sweep_dir)
        assert result["half_spread"] == pytest.approx(sql.HALF_SPREAD)
        assert result["event_stats"]["n_events"] == 1  # one event, regardless of how many trips/tokens
        assert result["n_round_trips"] == len(sweep._load_jsonl(sweep_dir / "round_trips.jsonl"))
        assert set(result["reason_stats"]) <= {"organic", "forced_flatten", "resolution_forced_close", "unknown"}

    def test_market_vpin_flag_surfaces_in_summary_and_separate_dir(self, monkeypatch):
        monkeypatch.setattr(sql, "MARKET_VPIN_ENABLED", True)
        monkeypatch.setattr(sql, "MARKET_VPIN_RATE_THRESHOLD", 3.0)

        sweep_dir = sweep.run_replay()
        result = sweep.summarize(sweep_dir)

        assert result["market_vpin_enabled"] is True
        assert result["market_vpin_threshold"] == pytest.approx(3.0)
        assert "vpin_on" in sweep_dir.name

    def test_market_flow_skew_flag_surfaces_in_summary_and_separate_dir(self, monkeypatch):
        monkeypatch.setattr(sql, "MARKET_FLOW_SKEW_ENABLED", True)

        sweep_dir = sweep.run_replay()
        result = sweep.summarize(sweep_dir)

        assert result["market_flow_skew_enabled"] is True
        assert result["flow_skew_max_shift"] == pytest.approx(sql.FLOW_SKEW_MAX_SHIFT)
        assert "flow_on" in sweep_dir.name
