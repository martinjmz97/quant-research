"""
Align a table of events (posts with timestamps) to a table of 1-minute
market bars, producing one price path per event covering a window before
and after the post.
"""
import pandas as pd


def build_event_windows(
    events: pd.DataFrame,
    bars: pd.DataFrame,
    pre_minutes: int = 30,
    post_minutes: int = 1440,
) -> pd.DataFrame:
    """
    events: must have columns [post_id, timestamp_utc, ...]
    bars: must have columns [timestamp_utc, close] (1-minute bars, single symbol)

    Returns long-format rows: one per (post_id, minute_offset), with the bar
    price at that offset and the event's own timestamp/content columns
    carried through for later filtering (e.g. by sentiment or ticker).
    """
    bars = bars.sort_values("timestamp_utc").set_index("timestamp_utc")
    price = bars["close"]

    rows = []
    for _, event in events.iterrows():
        t0 = event["timestamp_utc"].floor("min")
        window = price.loc[t0 - pd.Timedelta(minutes=pre_minutes): t0 + pd.Timedelta(minutes=post_minutes)]
        if window.empty:
            continue

        base_price = price.asof(t0)
        if pd.isna(base_price):
            continue

        offsets = ((window.index - t0) / pd.Timedelta(minutes=1)).astype(int)
        for offset, p in zip(offsets, window.values):
            rows.append({
                "post_id": event["post_id"],
                "event_timestamp_utc": t0,
                "minute_offset": offset,
                "price": p,
                "return_from_event": p / base_price - 1,
            })

    columns = ["post_id", "event_timestamp_utc", "minute_offset", "price", "return_from_event"]
    return pd.DataFrame(rows, columns=columns)
