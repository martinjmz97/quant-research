"""
Minute-level historical OHLCV for US equities/ETFs (e.g. TSLA, SPY, QQQ as
S&P500/Nasdaq proxies) via Databento's pay-per-use Historical API.

Requires DATABENTO_API_KEY in the environment (see .env.example). Sign up
at https://databento.com — historical queries for a handful of symbols
around specific event timestamps (this project's use case) are priced in
the tens of USD, not a monthly subscription.

Uses the EQUS.MINI dataset (consolidated US equities/ETFs, low-cost tier).
There is no direct "S&P 500 index" or "Nasdaq index" tick feed on Databento
(those are index values computed by the exchanges, not traded instruments)
— the standard proxy is SPY (S&P 500 ETF) and QQQ (Nasdaq-100 ETF), or ES/NQ
futures via the GLBX.MDP3 dataset if futures are preferred over ETFs.
"""
import os
from datetime import date, datetime

import databento as db
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DATASET = db.Dataset.EQUS_MINI


def _client() -> db.Historical:
    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        raise RuntimeError("Set DATABENTO_API_KEY in your environment or .env file.")
    return db.Historical(key=key)


def fetch_1m(symbols: list[str], start: date | datetime, end: date | datetime) -> pd.DataFrame:
    """1-minute OHLCV bars for one or more symbols, e.g. ['SPY', 'QQQ', 'TSLA']."""
    client = _client()
    store = client.timeseries.get_range(
        dataset=DATASET,
        schema=db.Schema.OHLCV_1M,
        symbols=symbols,
        stype_in="raw_symbol",
        start=start,
        end=end,
    )
    df = store.to_df()
    df = df.reset_index().rename(columns={"ts_event": "timestamp_utc"})
    return df[["symbol", "timestamp_utc", "open", "high", "low", "close", "volume"]]


if __name__ == "__main__":
    import sys
    symbols = sys.argv[1].split(",") if len(sys.argv) > 1 else ["SPY", "QQQ", "TSLA"]
    start = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2024, 1, 2)
    end = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date(2024, 1, 3)

    out = fetch_1m(symbols, start, end)
    out.to_parquet(f"data/raw/equities_1m_{start}_{end}.parquet", index=False)
    print(f"Saved {len(out)} rows for {symbols} {start}..{end}")
