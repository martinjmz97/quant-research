"""
Day-based version of align.py, for longer-horizon (weeks-to-quarter) event
studies where minute bars aren't needed (or available far enough back).
Offsets are in TRADING DAYS (index position), not calendar days — cleaner
than calendar-day deltas since it skips weekends/holidays automatically,
and maps naturally onto option-expiry cycles (~21 trading days/month).
"""
import pandas as pd


def build_event_windows_daily(
    events: pd.DataFrame,
    bars: pd.DataFrame,
    pre_days: int = 5,
    post_days: int = 63,
) -> pd.DataFrame:
    """
    events: must have columns [post_id, event_date] (event_date: date-like,
        the day the confirmed news broke).
    bars: must have columns [date, close] (daily bars, single symbol).

    Returns long-format rows: one per (post_id, trading_day_offset), offset
    counted in trading days from the first bar ON OR AFTER event_date.
    """
    bars = bars.sort_values("date").reset_index(drop=True)
    dates = pd.to_datetime(bars["date"])
    price = bars["close"]

    rows = []
    for _, event in events.iterrows():
        event_date = pd.to_datetime(event["event_date"])
        pos = dates.searchsorted(event_date)
        if pos >= len(dates):
            continue
        base_price = price.iloc[max(pos - 1, 0)]

        lo, hi = max(pos - pre_days, 0), min(pos + post_days + 1, len(dates))
        for offset, p in zip(range(lo - pos, hi - pos), price.iloc[lo:hi]):
            rows.append({
                "post_id": event["post_id"],
                "event_date": event_date,
                "trading_day_offset": offset,
                "price": p,
                "return_from_event": p / base_price - 1,
            })

    columns = ["post_id", "event_date", "trading_day_offset", "price", "return_from_event"]
    return pd.DataFrame(rows, columns=columns)
