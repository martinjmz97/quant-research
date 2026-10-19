"""
Abnormal returns = event-asset return minus a benchmark's return over the
same window (the standard event-study simplification of a market model with
beta=1 — reasonable for short intraday windows where beta drift barely
matters, and it's what the closest comparable papers, e.g. Born/Myers/Clark
2017, use).
"""
import pandas as pd

from .align import build_event_windows
from .align_daily import build_event_windows_daily


def compute_abnormal_returns(
    events: pd.DataFrame,
    asset_bars: pd.DataFrame,
    benchmark_bars: pd.DataFrame,
    pre_minutes: int = 30,
    post_minutes: int = 1440,
) -> pd.DataFrame:
    """
    asset_bars: 1-minute bars for the asset the event is expected to move
        (e.g. DOGEUSDT for a Musk Dogecoin tweet, TSLA for a Musk/Trump
        tweet naming Tesla).
    benchmark_bars: 1-minute bars for a benchmark unaffected by the specific
        event but capturing general market drift (e.g. BTCUSDT for other
        crypto events, SPY for equities).

    Returns one row per (post_id, minute_offset) with both raw and
    benchmark-adjusted (abnormal) returns.
    """
    asset = build_event_windows(events, asset_bars, pre_minutes, post_minutes)
    bench = build_event_windows(events, benchmark_bars, pre_minutes, post_minutes)

    merged = asset.merge(
        bench[["post_id", "minute_offset", "return_from_event"]],
        on=["post_id", "minute_offset"],
        suffixes=("", "_benchmark"),
    )
    merged["abnormal_return"] = merged["return_from_event"] - merged["return_from_event_benchmark"]
    return merged


def compute_abnormal_returns_daily(
    events: pd.DataFrame,
    asset_bars: pd.DataFrame,
    benchmark_bars: pd.DataFrame,
    pre_days: int = 5,
    post_days: int = 63,
) -> pd.DataFrame:
    """Day-based counterpart of compute_abnormal_returns — see align_daily.py."""
    asset = build_event_windows_daily(events, asset_bars, pre_days, post_days)
    bench = build_event_windows_daily(events, benchmark_bars, pre_days, post_days)

    merged = asset.merge(
        bench[["post_id", "trading_day_offset", "return_from_event"]],
        on=["post_id", "trading_day_offset"],
        suffixes=("", "_benchmark"),
    )
    merged["abnormal_return"] = merged["return_from_event"] - merged["return_from_event_benchmark"]
    return merged


def average_car(abnormal: pd.DataFrame) -> pd.DataFrame:
    """Mean cumulative abnormal return per minute offset, across all events."""
    return (
        abnormal.groupby("minute_offset")["abnormal_return"]
        .agg(mean_car="mean", std="std", n="count")
        .reset_index()
        .sort_values("minute_offset")
    )
