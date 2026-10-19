"""
Significance testing for average CAR at each minute offset: is the mean
abnormal return across events different from zero, more than noise?
"""
import numpy as np
import pandas as pd
from scipy import stats

from .abnormal_returns import compute_abnormal_returns, compute_abnormal_returns_daily


def ttest_car(abnormal: pd.DataFrame, offsets: list[int], offset_col: str = "minute_offset") -> pd.DataFrame:
    """One-sample t-test of abnormal_return against 0, at each requested offset."""
    rows = []
    for offset in offsets:
        sample = abnormal.loc[abnormal[offset_col] == offset, "abnormal_return"].dropna()
        if len(sample) < 2:
            continue
        t_stat, p_value = stats.ttest_1samp(sample, 0)
        rows.append({
            offset_col: offset,
            "mean_car": sample.mean(),
            "n": len(sample),
            "t_stat": t_stat,
            "p_value": p_value,
            "significant_5pct": p_value < 0.05,
        })
    return pd.DataFrame(rows)


def bootstrap_ci(abnormal: pd.DataFrame, offset: int, n_boot: int = 5000, ci: float = 0.95, seed: int = 0) -> dict:
    """Bootstrap confidence interval for the mean abnormal return at one offset."""
    sample = abnormal.loc[abnormal["minute_offset"] == offset, "abnormal_return"].dropna().to_numpy()
    if len(sample) < 2:
        return {"minute_offset": offset, "mean": np.nan, "ci_low": np.nan, "ci_high": np.nan, "n": len(sample)}

    rng = np.random.default_rng(seed)
    boot_means = np.array([
        rng.choice(sample, size=len(sample), replace=True).mean()
        for _ in range(n_boot)
    ])
    alpha = (1 - ci) / 2
    return {
        "minute_offset": offset,
        "mean": sample.mean(),
        "ci_low": np.quantile(boot_means, alpha),
        "ci_high": np.quantile(boot_means, 1 - alpha),
        "n": len(sample),
    }


def placebo_ttest(
    asset_bars: pd.DataFrame,
    benchmark_bars: pd.DataFrame,
    offsets: list[int],
    n_random: int,
    pre_minutes: int = 30,
    post_minutes: int = 1440,
    seed: int = 0,
) -> pd.DataFrame:
    """
    Run the same abnormal-return t-test on `n_random` timestamps drawn
    uniformly at random from the bars' date range — i.e. dates with no
    connection to any real event. ALWAYS run this alongside a real result
    before trusting it: with dense/overlapping event windows (many events
    close together in time), naive t-tests get inflated by autocorrelation,
    and broad market regime drift can produce "significant" results at
    random dates too. If the placebo shows similar magnitude/significance
    to the real result, the real result is not attributable to the events.
    """
    rng = np.random.default_rng(seed)
    t0, t1 = asset_bars["timestamp_utc"].min(), asset_bars["timestamp_utc"].max()
    random_ts = pd.to_datetime(rng.integers(t0.value, t1.value, n_random), utc=True)
    placebo_events = pd.DataFrame({
        "post_id": [f"placebo_{i}" for i in range(n_random)],
        "timestamp_utc": random_ts,
    })

    abn = compute_abnormal_returns(placebo_events, asset_bars, benchmark_bars, pre_minutes, post_minutes)
    return ttest_car(abn, offsets)


def placebo_ttest_daily(
    asset_bars: pd.DataFrame,
    benchmark_bars: pd.DataFrame,
    offsets: list[int],
    n_random: int,
    pre_days: int = 5,
    post_days: int = 63,
    seed: int = 0,
) -> pd.DataFrame:
    """Day-based counterpart of placebo_ttest — see its docstring."""
    rng = np.random.default_rng(seed)
    dates = pd.to_datetime(asset_bars["date"]).sort_values().reset_index(drop=True)
    random_dates = dates.iloc[rng.integers(0, len(dates), n_random)].reset_index(drop=True)
    placebo_events = pd.DataFrame({
        "post_id": [f"placebo_{i}" for i in range(n_random)],
        "event_date": random_dates,
    })

    abn = compute_abnormal_returns_daily(placebo_events, asset_bars, benchmark_bars, pre_days, post_days)
    return ttest_car(abn, offsets, offset_col="trading_day_offset")
