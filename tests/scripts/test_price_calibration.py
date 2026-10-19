import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import price_calibration as pc  # noqa: E402


def _df(pts):
    return pl.DataFrame({"t": [p[0] for p in pts], "p": [p[1] for p in pts]})


class TestInferOutcome:
    def test_decisive_yes(self):
        assert pc.infer_outcome(_df([(0, 0.5), (100, 0.995)])) == 1

    def test_decisive_no(self):
        assert pc.infer_outcome(_df([(0, 0.5), (100, 0.002)])) == 0

    def test_not_decisive_stays_none(self):
        assert pc.infer_outcome(_df([(0, 0.5), (100, 0.7)])) is None

    def test_empty_is_none(self):
        assert pc.infer_outcome(_df([])) is None

    def test_uses_last_by_time_not_row_order(self):
        # rows deliberately out of time order
        df = pl.DataFrame({"t": [100, 0, 50], "p": [0.99, 0.5, 0.6]})
        assert pc.infer_outcome(df) == 1


class TestPriceAtFraction:
    def test_start_and_end(self):
        df = _df([(0, 0.1), (100, 0.9)])
        assert pc.price_at_fraction(df, 0.0) == pytest.approx(0.1)
        assert pc.price_at_fraction(df, 1.0) == pytest.approx(0.9)

    def test_midpoint_picks_nearest_tick(self):
        df = _df([(0, 0.1), (40, 0.4), (100, 0.9)])
        # fraction 0.5 -> target t=50, nearest tick is t=40
        assert pc.price_at_fraction(df, 0.5) == pytest.approx(0.4)

    def test_empty_is_none(self):
        assert pc.price_at_fraction(_df([]), 0.5) is None


class TestBinCalibration:
    def test_perfectly_calibrated_gap_is_zero(self):
        # 10 points at price 0.7, exactly 7 resolve YES -> gap ~0 in that bin
        points = [{"price": 0.7, "outcome": 1} for _ in range(7)] + [{"price": 0.7, "outcome": 0} for _ in range(3)]
        bins = pc.bin_calibration(points, n_bins=10)
        bin_07 = next(b for b in bins if b["bin"] == "[0.7,0.8)")
        assert bin_07["n"] == 10
        assert bin_07["mean_price"] == pytest.approx(0.7)
        assert bin_07["mean_outcome"] == pytest.approx(0.7)
        assert bin_07["gap"] == pytest.approx(0.0)

    def test_overpriced_bin_has_negative_gap(self):
        # priced at 0.8 but only resolves YES half the time -> crowd overpaid
        points = [{"price": 0.8, "outcome": 1} for _ in range(5)] + [{"price": 0.8, "outcome": 0} for _ in range(5)]
        bins = pc.bin_calibration(points, n_bins=10)
        bin_08 = next(b for b in bins if b["bin"] == "[0.8,0.9)")
        assert bin_08["gap"] == pytest.approx(-0.3)

    def test_empty_bin_reports_none(self):
        bins = pc.bin_calibration([{"price": 0.05, "outcome": 0}], n_bins=5)
        empty_bins = [b for b in bins if b["n"] == 0]
        assert len(empty_bins) == 4
        assert all(b["mean_price"] is None and b["gap"] is None for b in empty_bins)

    def test_price_exactly_one_falls_in_last_bin(self):
        bins = pc.bin_calibration([{"price": 1.0, "outcome": 1}], n_bins=5)
        assert bins[-1]["n"] == 1


class TestPerMatchSummary:
    def test_one_row_per_match_using_latest_fraction(self):
        points = [
            {"label": "a", "fraction": 0.1, "price": 0.2, "outcome": 1},
            {"label": "a", "fraction": 0.9, "price": 0.95, "outcome": 1},
            {"label": "b", "fraction": 0.5, "price": 0.4, "outcome": 0},
        ]
        rows = pc.per_match_summary(points)
        assert len(rows) == 2
        row_a = next(r for r in rows if r["label"] == "a")
        assert row_a["price"] == pytest.approx(0.95)  # picked fraction=0.9, not 0.1
