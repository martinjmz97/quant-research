"""
Historical Trump tweets (X/Twitter), 2009-2018, from the free public archive
maintained by Brendan Brown: github.com/bpb27/trump_tweet_data_archive

This repo does not cover post-2018 tweets. For 2019-Jan 2021 (last tweets
before the account suspension), a supplementary source is needed — the repo
stopped receiving updates for those years. Truth Social (2022-present) is
covered separately by trump_truth_social.py.
"""
import io
import zipfile
from datetime import datetime, timezone

import pandas as pd
import requests

RAW_BASE = "https://raw.githubusercontent.com/bpb27/trump_tweet_data_archive/master"
YEARS = range(2009, 2019)


def _fetch_year(year: int) -> list[dict]:
    url = f"{RAW_BASE}/condensed_{year}.json.zip"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = zf.namelist()[0]
        df = pd.read_json(io.BytesIO(zf.read(name)), convert_dates=False, dtype={"id_str": str})
        return df.to_dict("records")


def fetch_all() -> pd.DataFrame:
    records = []
    for year in YEARS:
        records.extend(_fetch_year(year))

    df = pd.DataFrame(records)
    df["timestamp_utc"] = pd.to_datetime(df["created_at"], format="%a %b %d %H:%M:%S %z %Y", utc=True)
    df["author"] = "trump"
    df["platform"] = "x"
    df = df.rename(columns={"id_str": "post_id", "text": "content"})
    return df[["post_id", "author", "platform", "timestamp_utc", "content",
               "retweet_count", "favorite_count", "is_retweet"]]


if __name__ == "__main__":
    out = fetch_all()
    out.to_parquet("data/raw/trump_x_2009_2018.parquet", index=False)
    print(f"Saved {len(out)} tweets covering {out['timestamp_utc'].min()} to {out['timestamp_utc'].max()}")
