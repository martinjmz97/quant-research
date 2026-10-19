"""
Trump's Truth Social posts, 2022-present, from CNN's free public mirror.
No auth required. Updates every ~5 minutes; each pull returns the full
archive (not incremental), so re-running is safe but re-downloads everything.
"""
import pandas as pd
import requests

ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"


def fetch_all() -> pd.DataFrame:
    resp = requests.get(ARCHIVE_URL, timeout=60)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())

    df["timestamp_utc"] = pd.to_datetime(df["created_at"], utc=True)
    df["author"] = "trump"
    df["platform"] = "truth_social"
    df = df.rename(columns={
        "id": "post_id", "content": "content",
        "replies_count": "reply_count", "reblogs_count": "reblog_count",
        "favourites_count": "favorite_count",
    })
    return df[["post_id", "author", "platform", "timestamp_utc", "content",
               "reply_count", "reblog_count", "favorite_count", "url"]]


if __name__ == "__main__":
    out = fetch_all()
    out.to_parquet("data/raw/trump_truth_social.parquet", index=False)
    print(f"Saved {len(out)} posts covering {out['timestamp_utc'].min()} to {out['timestamp_utc'].max()}")
