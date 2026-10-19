"""Calibration check: does Polymarket's traded price predict the eventual
outcome correctly, or is there a systematic bias (favorite-longshot bias,
crowd overpaying for the leader, etc.)?

Answers a DIFFERENT question than every other backtest in this project so
far — those all tested QUOTING MECHANISM (spread width, toxic-flow
detection, flow-skew direction) holding the crowd's price as given. This
tests whether the crowd's price itself is worth betting against, in
EITHER direction, independent of any market-making mechanism.

Uses the 43 historical single-match price histories already fetched by
scripts/fetch_match_history.py under data/raw/polymarket/matches/ — no
new network calls. Each file covers kickoff-24h to kickoff+8h at ~roughly
constant sampling (see fetch_match_history.py), one row (t, p) per tick.

Ground truth outcome: the file's OWN last recorded price, rounded — NOT
looked up from the catalog. The catalog join is ambiguous for 3-way
(soccer) events (home/away/draw share one event_title, so a slug-based
label matches multiple catalog rows and there's no saved token_id to
disambiguate which specific leg was actually fetched) but is safe to use
for kickoff/window timing (all legs of one event share the same kickoff).
Using each file's own terminal price sidesteps the outcome-ambiguity
entirely, at the cost of discarding matches whose price hadn't decisively
converged by kickoff+8h (see DECISIVE_THRESHOLD).

Run: .venv/bin/python3 scripts/price_calibration.py
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

MATCH_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "polymarket" / "matches"

# a match's last recorded price must be this close to 0 or 1 to trust it
# as ground truth — anything in between means the price hadn't resolved
# by kickoff+8h (the fetch window's end), not that the market was
# genuinely uncertain forever. Excluded, not guessed.
DECISIVE_THRESHOLD = 0.9

# checkpoints as a FRACTION of each file's own (kickoff-24h, kickoff+8h)
# window — avoids needing to re-derive each match's exact kickoff
# timestamp (which the ambiguous catalog join can't safely give per-leg
# anyway). Kickoff itself sits at 24/32=0.75 of the window by construction
# of the fetch script. Spread across pre-game and in-game on purpose: a
# calibration bias could plausibly differ by how much of the game has
# been priced in.
CHECKPOINT_FRACTIONS = (0.1, 0.5, 0.75, 0.85, 0.95)

N_BINS = 5


def infer_outcome(df: pl.DataFrame) -> int | None:
    """1/0 from the file's own last recorded price; None if not decisive
    (see DECISIVE_THRESHOLD) — a market that hadn't converged by
    kickoff+8h isn't usable ground truth, not assumed either way."""
    if df.height == 0:
        return None
    last_p = df.sort("t")["p"][-1]
    if last_p >= DECISIVE_THRESHOLD:
        return 1
    if last_p <= 1 - DECISIVE_THRESHOLD:
        return 0
    return None


def price_at_fraction(df: pl.DataFrame, fraction: float) -> float | None:
    """Price at the tick nearest `fraction` of the way through this
    file's own recorded time range. None if the file is empty."""
    if df.height == 0:
        return None
    df = df.sort("t")
    t0, t1 = df["t"][0], df["t"][-1]
    target = t0 + fraction * (t1 - t0)
    idx = (df["t"] - target).abs().arg_min()
    return df["p"][idx]


def collect_calibration_points(match_dir: Path = MATCH_DIR, fractions=CHECKPOINT_FRACTIONS) -> list[dict]:
    """One row per (match, checkpoint) with a decisive outcome. Points
    from the same match are correlated (same underlying game) — see
    module docstring and the per-match / per-checkpoint breakdowns in
    POLYMARKET_MM.md for how this is accounted for, not just pooled
    blindly into one N."""
    points = []
    for path in sorted(match_dir.glob("*_price_history.parquet")):
        label = path.stem.removesuffix("_price_history")
        df = pl.read_parquet(path)
        outcome = infer_outcome(df)
        if outcome is None:
            continue
        for frac in fractions:
            price = price_at_fraction(df, frac)
            if price is None:
                continue
            points.append({"label": label, "fraction": frac, "price": price, "outcome": outcome})
    return points


def bin_calibration(points: list[dict], n_bins: int = N_BINS) -> list[dict]:
    """Bins points by price into n_bins equal-width [0,1] buckets and
    reports mean_price vs. mean_outcome per bin — a calibrated market has
    mean_outcome ≈ mean_price in every bin (the y=x line of a reliability
    diagram). `gap` = mean_outcome - mean_price: positive means the
    market UNDERpriced this price range (outcome happened more often than
    the price implied — buying looks good), negative means OVERpriced
    (selling looks good)."""
    bins = [[] for _ in range(n_bins)]
    for p in points:
        idx = min(int(p["price"] * n_bins), n_bins - 1)
        bins[idx].append(p)

    out = []
    for i, bucket in enumerate(bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        if not bucket:
            out.append({"bin": f"[{lo:.1f},{hi:.1f})", "n": 0, "mean_price": None, "mean_outcome": None, "gap": None})
            continue
        mean_price = sum(p["price"] for p in bucket) / len(bucket)
        mean_outcome = sum(p["outcome"] for p in bucket) / len(bucket)
        out.append({
            "bin": f"[{lo:.1f},{hi:.1f})", "n": len(bucket),
            "mean_price": round(mean_price, 4), "mean_outcome": round(mean_outcome, 4),
            "gap": round(mean_outcome - mean_price, 4),
        })
    return out


def per_match_summary(points: list[dict]) -> list[dict]:
    """One row per DISTINCT match (not per checkpoint) — the closest
    thing to an independence-respecting view, using each match's LAST
    checkpoint only (closest to resolution, so the most-informed single
    snapshot) instead of pooling every fraction. Small-N caveat applies
    just as hard here as it did for the spread-widening analysis
    elsewhere in this project — don't read a handful of matches as a
    calibrated estimate of anything."""
    by_label: dict[str, list[dict]] = {}
    for p in points:
        by_label.setdefault(p["label"], []).append(p)
    rows = []
    for label, pts in by_label.items():
        last = max(pts, key=lambda p: p["fraction"])
        rows.append({"label": label, "price": last["price"], "outcome": last["outcome"]})
    return rows


def main() -> None:
    points = collect_calibration_points()
    n_matches = len(per_match_summary(points))
    print(f"{n_matches} partidos decisivos, {len(points)} puntos (match x checkpoint)")
    print()
    print("--- calibración pooled (todos los checkpoints, NO independientes entre si dentro de un partido) ---")
    for row in bin_calibration(points):
        print(row)
    print()
    print("--- calibración solo con el ultimo checkpoint por partido (mas cerca de independiente) ---")
    match_points = [{"label": r["label"], "fraction": 1.0, "price": r["price"], "outcome": r["outcome"]} for r in per_match_summary(points)]
    for row in bin_calibration(match_points, n_bins=N_BINS):
        print(row)


if __name__ == "__main__":
    main()
