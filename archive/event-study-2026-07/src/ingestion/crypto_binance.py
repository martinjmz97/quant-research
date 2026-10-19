"""
Free historical 1-minute klines for crypto spot pairs from Binance's public
data repository (data.binance.vision). No auth, no rate limits.
"""
import io
import zipfile
from datetime import date

import pandas as pd
import requests

BASE_URL = "https://data.binance.vision/data/spot/daily/klines"
COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]
OUT_COLUMNS = ["symbol", "timestamp_utc", "open", "high", "low", "close", "volume", "trades"]

# Binance switched some daily kline files from millisecond to microsecond
# open_time at some point in 2025 (undocumented, discovered empirically —
# ms epoch for 2024-2026 is ~1.7e12; anything past ~1e14 is microseconds).
_MS_EPOCH_UPPER_BOUND = 10_000_000_000_000


def fetch_day(symbol: str, day: date, interval: str = "1m") -> pd.DataFrame:
    """symbol e.g. 'BTCUSDT', 'ETHUSDT', 'DOGEUSDT'."""
    fname = f"{symbol}-{interval}-{day.isoformat()}.zip"
    url = f"{BASE_URL}/{symbol}/{interval}/{fname}"
    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        return pd.DataFrame(columns=OUT_COLUMNS)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = zf.namelist()[0]
        df = pd.read_csv(zf.open(name), header=None, names=COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=OUT_COLUMNS)

    unit = "us" if df["open_time"].iloc[0] > _MS_EPOCH_UPPER_BOUND else "ms"
    df["timestamp_utc"] = pd.to_datetime(df["open_time"], unit=unit, utc=True)
    df["symbol"] = symbol
    return df[OUT_COLUMNS]


def fetch_range(symbol: str, start: date, end: date, interval: str = "1m") -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D")
    frames = [fetch_day(symbol, d.date(), interval) for d in days]
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    start = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2024, 1, 1)
    end = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date(2024, 1, 7)

    out = fetch_range(symbol, start, end)
    out.to_parquet(f"data/raw/{symbol}_1m_{start}_{end}.parquet", index=False)
    print(f"Saved {len(out)} rows for {symbol} {start}..{end}")
