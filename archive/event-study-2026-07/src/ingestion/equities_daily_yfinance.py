"""
Free daily OHLCV via Yahoo Finance (yfinance), going back decades — used
for longer-horizon (weeks-to-quarter) event studies where Databento's
minute-level history (2023-03-28+ only) doesn't reach far enough back,
and where daily granularity is enough anyway (a 90-day options-horizon
thesis doesn't need minute bars).
"""
import pandas as pd
import yfinance as yf


def fetch_daily(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    raw = yf.download(symbols, start=start, end=end, progress=False, group_by="ticker")
    frames = []
    for symbol in symbols:
        df = raw[symbol].reset_index().rename(columns={"Date": "date", "Close": "close",
                                                         "Open": "open", "High": "high",
                                                         "Low": "low", "Volume": "volume"})
        df["symbol"] = symbol
        frames.append(df[["symbol", "date", "open", "high", "low", "close", "volume"]])
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    import sys
    symbols = sys.argv[1].split(",") if len(sys.argv) > 1 else ["F", "GM", "TM", "HMC", "STLA", "NXPI"]
    start = sys.argv[2] if len(sys.argv) > 2 else "2020-06-01"
    end = sys.argv[3] if len(sys.argv) > 3 else "2026-07-08"

    out = fetch_daily(symbols, start, end)
    out.to_parquet("data/raw/supply_chain_daily.parquet", index=False)
    print(f"Saved {len(out)} rows for {symbols} {start}..{end}")
