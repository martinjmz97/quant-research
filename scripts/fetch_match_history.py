"""Fetch full trade tape + price history for a set of single-match soccer
markets (picked from the catalog: top-N by volume among markets with
(end_date - start_date) < 48h, i.e. actual single games, not season
futures — see POLYMARKET_MM.md).

Saves one trades parquet + one price-history parquet per market under
data/raw/polymarket/matches/. Kickoff = catalog end_date (verified exact
against 3 real matches — see POLYMARKET_MM.md "Kickoff real vs. campos
del catálogo") — the price-history window is kickoff-24h to kickoff+8h,
not the market's full listing lifetime, since we only care about the
day-of ramp through resolution, not the multi-day-old listing.
"""

import re
import time
from pathlib import Path

import polars as pl
from polymarket.clients.public import PublicClient

from ingestion.polymarket.catalog import CATALOG_PATH
from ingestion.polymarket.history import fetch_all_trades, fetch_price_history

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "polymarket" / "matches"

# (label, condition_id prefix) — token ids/dates are looked up from the
# catalog at run time instead of hand-transcribed (the catalog print
# wraps long id columns, easy to mistranscribe a digit by hand — bit us
# once already: fetch_price_history silently returned 0 points for a
# mistyped token_id instead of erroring).
MATCHES = [
    ("barcelona_olympiacos_20251021", "0xffa740e3ea988ac69dcbffd101bd79e"),
    ("bilbao_arsenal_20250916", "0xc57c48ea08192107f7981b041ba1156"),
    ("realmadrid_marseille_20250916", "0x8c5927af2b98879999712a217d1ff65"),
]


def _slugify(event_title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", event_title.lower()).strip("_")


def matches_from_parquet(path: str) -> list[tuple[str, str]]:
    """Build (label, condition_id_prefix) pairs from a catalog-slice
    parquet (columns: event_title, end_date, condition_id) — label is
    slugified event_title + kickoff date, condition_id_prefix is the
    first 34 chars (enough to disambiguate, matches the hand-picked style
    above)."""
    df = pl.read_parquet(path)
    out = []
    for r in df.iter_rows(named=True):
        label = f"{_slugify(r['event_title'])}_{r['end_date'].strftime('%Y%m%d')}"
        out.append((label, r["condition_id"][:34]))
    return out


def trades_to_df(trades) -> pl.DataFrame:
    rows = [
        {
            "timestamp": t.timestamp,
            "side": t.side,
            "price": float(t.price) if t.price is not None else None,
            "size": float(t.size) if t.size is not None else None,
            "outcome": t.outcome,
            "outcome_index": t.outcome_index,
        }
        for t in trades
    ]
    return pl.DataFrame(rows, infer_schema_length=None).sort("timestamp")


def price_history_to_df(points) -> pl.DataFrame:
    rows = [{"t": p.t, "p": p.p} for p in points]
    return pl.DataFrame(rows).sort("t")


def main(matches: list[tuple[str, str]] | None = None) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = PublicClient()
    catalog = pl.read_parquet(CATALOG_PATH)

    for label, condition_id_prefix in matches or MATCHES:
        trades_path = OUT_DIR / f"{label}_trades.parquet"
        if trades_path.exists():
            print(f"{label}: already fetched, skipping", flush=True)
            continue

        row = catalog.filter(pl.col("condition_id").str.starts_with(condition_id_prefix))
        if row.height != 1:
            raise ValueError(f"{label}: expected 1 catalog row for prefix {condition_id_prefix}, got {row.height}")
        r = row.row(0, named=True)
        condition_id, yes_token_id = r["condition_id"], r["yes_token_id"]
        kickoff = r["end_date"]  # verified == kickoff, see POLYMARKET_MM.md
        start_ts = int(kickoff.timestamp()) - 24 * 3600
        end_ts = int(kickoff.timestamp()) + 8 * 3600

        t0 = time.time()
        trades = fetch_all_trades(client, condition_id=condition_id)
        trades_df = trades_to_df(trades)
        trades_df.write_parquet(trades_path)
        print(f"{label}: {len(trades)} trades -> {trades_path} ({time.time() - t0:.0f}s)", flush=True)

        t0 = time.time()
        points = fetch_price_history(client, token_id=yes_token_id, start_ts=start_ts, end_ts=end_ts, fidelity=1)
        ph_df = price_history_to_df(points)
        ph_path = OUT_DIR / f"{label}_price_history.parquet"
        ph_df.write_parquet(ph_path)
        print(f"{label}: {len(points)} price points -> {ph_path} ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        main(matches_from_parquet(sys.argv[1]))
    else:
        main()
