"""First-pass shadow market-making backtest over historical trade tapes.

Explicitly simplified, matches what was asked: quote symmetrically around
the price_history reference (treated as fair value), re-fill whenever a
real trade in the tape crosses our quote — WITHOUT modeling queue
position (assumes we always get filled at our quote price when the market
trades through it, capped at a small per-fill size). This overstates our
real fill rate (we would not always be at the front of the queue), so
treat the P&L here as an optimistic upper bound, not a forecast — the
queue-position gap is exactly what's still missing (see POLYMARKET_MM.md).

Marks final P&L against the last observed price in the tape (matches
resolve near 0/1, so this approximates the true binary payoff without
needing the official resolution feed).
"""

from __future__ import annotations

import datetime as dt
import glob
from dataclasses import dataclass, field

import polars as pl

HALF_SPREAD = 0.01  # quote at fair_value +/- 1c, i.e. 2c total spread
MAX_FILL_USD = 2.0  # per-fill notional cap, consistent with ~$100 total capital across many markets
MATCH_DIR = "data/raw/polymarket/matches"


@dataclass
class SimResult:
    label: str
    n_trades_seen: int
    n_fills: int
    final_position: float
    final_cash: float
    final_price: float
    pnl: float
    max_abs_position: float
    worst_mark_to_market: float


def simulate(label: str) -> SimResult | None:
    trades = pl.read_parquet(f"{MATCH_DIR}/{label}_trades.parquet").filter(pl.col("outcome") == "Yes").sort("timestamp")
    ph = pl.read_parquet(f"{MATCH_DIR}/{label}_price_history.parquet").with_columns(
        pl.from_epoch("t", time_unit="s").dt.replace_time_zone("UTC").alias("ts")
    ).sort("t")
    if trades.height < 50 or ph.height < 10:
        return None

    ph_ts = ph["ts"].to_list()
    ph_p = ph["p"].to_list()

    def fair_value_at(ts: dt.datetime) -> float:
        # last price_history point at or before ts (nearest-left interpolation)
        lo, hi = 0, len(ph_ts) - 1
        if ts <= ph_ts[0]:
            return ph_p[0]
        if ts >= ph_ts[-1]:
            return ph_p[-1]
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if ph_ts[mid] <= ts:
                lo = mid
            else:
                hi = mid - 1
        return ph_p[lo]

    cash = 0.0
    position = 0.0  # in Yes tokens
    n_fills = 0
    max_abs_position = 0.0
    worst_mtm = 0.0

    for row in trades.iter_rows(named=True):
        ts, side, price = row["timestamp"], row["side"], row["price"]
        if price is None:
            continue
        fv = fair_value_at(ts)
        our_bid, our_ask = fv - HALF_SPREAD, fv + HALF_SPREAD

        # a market BUY at price >= our_ask means the taker crossed our resting ask -> we sell
        if side == "BUY" and price >= our_ask:
            fill_tokens = min(row["size"] or 0.0, MAX_FILL_USD / our_ask)
            cash += fill_tokens * our_ask
            position -= fill_tokens
            n_fills += 1
        # a market SELL at price <= our_bid means the taker crossed our resting bid -> we buy
        elif side == "SELL" and price <= our_bid:
            fill_tokens = min(row["size"] or 0.0, MAX_FILL_USD / our_bid)
            cash -= fill_tokens * our_bid
            position += fill_tokens
            n_fills += 1

        max_abs_position = max(max_abs_position, abs(position))
        mtm = cash + position * fv
        worst_mtm = min(worst_mtm, mtm)

    final_price = ph_p[-1]
    pnl = cash + position * final_price
    return SimResult(
        label=label,
        n_trades_seen=trades.height,
        n_fills=n_fills,
        final_position=position,
        final_cash=cash,
        final_price=final_price,
        pnl=pnl,
        max_abs_position=max_abs_position,
        worst_mark_to_market=worst_mtm,
    )


def main() -> None:
    labels = sorted(
        f.split("/")[-1].replace("_trades.parquet", "")
        for f in glob.glob(f"{MATCH_DIR}/*_trades.parquet")
    )
    results = [r for label in labels if (r := simulate(label)) is not None]

    print(f"{'match':<55} {'fills':>6} {'maxpos':>8} {'worstMTM':>10} {'PnL':>8}")
    for r in results:
        print(f"{r.label:<55} {r.n_fills:>6} {r.max_abs_position:>8.1f} {r.worst_mark_to_market:>10.3f} {r.pnl:>8.3f}")

    pnls = [r.pnl for r in results]
    import statistics
    print()
    print(f"n={len(pnls)}  mean PnL={statistics.mean(pnls):.4f}  std={statistics.stdev(pnls):.4f}  min={min(pnls):.4f}  max={max(pnls):.4f}")
    losers = [r for r in results if r.pnl < 0]
    print(f"partidos con PnL negativo: {len(losers)}/{len(results)}")


if __name__ == "__main__":
    main()
