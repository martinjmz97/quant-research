"""Replay the recorded orderbook tape (live_book.jsonl) through the exact
same ShadowBook/process_message logic shadow_quote_live.py runs live, under
ONE HALF_SPREAD value — reused directly via import, not reimplemented, so
this can't drift from the live fill/skew/stop-quoting logic the way a
second hand-written detector already did once (see POLYMARKET_MM.md "El
dashboard no leía nada de lo nuevo").

HALF_SPREAD is read by shadow_quote_live.py from the SHADOW_HALF_SPREAD env
var at import time (several other constants — SKEW_MAX_SHIFT,
REQUOTE_DRIFT_THRESHOLD — derive from it at that same import time), so a
sweep over multiple spread values needs one subprocess per value, not a
loop within a single process. Run via scripts/run_spread_sweep.sh, or by
hand:

    SHADOW_HALF_SPREAD=0.03 .venv/bin/python3 scripts/spread_sweep_backtest.py

SHADOW_MARKET_VPIN_ENABLED and SHADOW_MARKET_FLOW_SKEW_ENABLED (both
default off) are read the same way and can be combined freely with any
spread value, e.g.:

    SHADOW_HALF_SPREAD=0.01 SHADOW_MARKET_FLOW_SKEW_ENABLED=1 .venv/bin/python3 scripts/spread_sweep_backtest.py

Prints one JSON line to stdout with round-trip stats for that spread,
grouped by EVENT (not token — many tokens are legs of the same underlying
game/event and aren't independent draws, same pseudo-replication caution
already documented for the spread-widening analysis in POLYMARKET_MM.md).

Known fidelity gap vs. live, applies EQUALLY to every spread in the sweep
(so the comparison BETWEEN spreads stays fair even though no single
spread's absolute numbers exactly reproduce what production saw):
- No REST calls happen during replay, so the game-status-based flatten
  (_game_confirmed_over, e.g. the WNBA case where price hadn't moved but
  the game had ended) never fires — only the price-based _near_resolution
  flatten and organic crossing can close a position during the replay
  itself.
- Terminal payouts for markets that DID resolve are taken from the real,
  already-recorded resolved_games.jsonl (ground truth, not re-derived) and
  applied once at the end of the tape, not at the exact interleaved instant
  the live REST poll would have caught it mid-tape. Once a market resolves
  the orderbook feed for that token stops sending ticks, so in practice
  this end-of-tape application closes each token at the same book state a
  live REST poll would have caught it in.
- Markets that hadn't resolved by the end of the tape are left with
  whatever position was open — excluded from round-trip stats entirely
  (unrealized, not a completed trip, no known terminal payout to score it
  against).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import shadow_quote_live as sql


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.open():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def run_replay() -> Path:
    """Runs the full tape through process_message under sql.HALF_SPREAD,
    sql.MARKET_VPIN_ENABLED and sql.MARKET_FLOW_SKEW_ENABLED (all already
    fixed by env vars at import time — see SHADOW_HALF_SPREAD /
    SHADOW_MARKET_VPIN_ENABLED / SHADOW_MARKET_FLOW_SKEW_ENABLED). Returns
    the sweep-isolated directory holding this run's round_trips.jsonl etc.
    Directory name includes all three so an A/B at the same spread value
    doesn't overwrite the same files."""
    vpin_tag = "vpin_on" if sql.MARKET_VPIN_ENABLED else "vpin_off"
    flow_tag = "flow_on" if sql.MARKET_FLOW_SKEW_ENABLED else "flow_off"
    sweep_dir = sql.DATA_DIR / f"sweep_{sql.HALF_SPREAD:.3f}_{vpin_tag}_{flow_tag}"
    sweep_dir.mkdir(parents=True, exist_ok=True)
    sql.FILLS_PATH = sweep_dir / "shadow_fills.jsonl"
    sql.ROUND_TRIPS_PATH = sweep_dir / "round_trips.jsonl"
    sql.RESOLVED_GAMES_PATH = sweep_dir / "resolved_games.jsonl"
    sql.STATE_PATH = sweep_dir / "shadow_state.json"
    for p in (sql.FILLS_PATH, sql.ROUND_TRIPS_PATH, sql.RESOLVED_GAMES_PATH):
        if p.exists():
            p.unlink()

    sql.refresh_tracked_tokens()

    real_resolved = _load_jsonl(sql.DATA_DIR / "resolved_games.jsonl")
    payout_by_label = {r["label"]: r["payout"] for r in real_resolved}

    books: dict[str, sql.ShadowBook] = {}
    with sql.IN_PATH.open("r") as in_f, sql.FILLS_PATH.open("a") as fills_f:
        for line in in_f:
            try:
                msg = json.loads(line)
                sql.process_message(msg["raw"], books, msg["recv_ts"], fills_f)
            except (json.JSONDecodeError, KeyError):
                continue

        ts_end = dt.datetime.now(dt.timezone.utc).isoformat()
        for book in books.values():
            payout = payout_by_label.get(book.label)
            if payout is not None:
                book.force_close_at_resolution(payout, ts_end, fills_f)

    return sweep_dir


def summarize(sweep_dir: Path) -> dict:
    round_trips = _load_jsonl(sweep_dir / "round_trips.jsonl")
    tracked = json.loads(sql.TRACKED_MARKETS_PATH.read_text())["tokens"]
    asset_to_event = {t["asset_id"]: t["event_id"] for t in tracked}

    by_reason: dict[str, list[float]] = {}
    by_event: dict[str, list[float]] = {}
    for rt in round_trips:
        by_reason.setdefault(rt.get("close_reason", "unknown"), []).append(rt["pnl"])
        event = asset_to_event.get(rt["asset_id"], f"UNMATCHED:{rt['label']}")
        by_event.setdefault(str(event), []).append(rt["pnl"])

    reason_stats = {
        reason: {"n": len(pnls), "pnl_sum": round(sum(pnls), 4), "pnl_mean": round(sum(pnls) / len(pnls), 4)}
        for reason, pnls in by_reason.items()
    }

    event_sums = [sum(pnls) for pnls in by_event.values()]
    n_events = len(event_sums)
    event_stats = {"n_events": n_events}
    if n_events > 0:
        mean = sum(event_sums) / n_events
        event_stats["mean_pnl_per_event"] = round(mean, 4)
        if n_events > 1:
            var = sum((x - mean) ** 2 for x in event_sums) / (n_events - 1)
            std = var ** 0.5
            se = std / (n_events ** 0.5)
            event_stats["std"] = round(std, 4)
            event_stats["se"] = round(se, 4)
            event_stats["t_stat"] = round(mean / se, 4) if se > 0 else None

    return {
        "half_spread": sql.HALF_SPREAD,
        "market_vpin_enabled": sql.MARKET_VPIN_ENABLED,
        "market_vpin_threshold": sql.MARKET_VPIN_RATE_THRESHOLD if sql.MARKET_VPIN_ENABLED else None,
        "market_flow_skew_enabled": sql.MARKET_FLOW_SKEW_ENABLED,
        "flow_skew_max_shift": sql.FLOW_SKEW_MAX_SHIFT if sql.MARKET_FLOW_SKEW_ENABLED else None,
        "n_round_trips": len(round_trips),
        "total_pnl": round(sum(rt["pnl"] for rt in round_trips), 4),
        "reason_stats": reason_stats,
        "event_stats": event_stats,
    }


def main() -> None:
    sweep_dir = run_replay()
    result = summarize(sweep_dir)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
