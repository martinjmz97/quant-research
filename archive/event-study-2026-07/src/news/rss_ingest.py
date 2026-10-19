"""
Free RSS ingestion for the continuous-monitoring terminal. Run this
periodically (see README for a cron/launchd example) — each run fetches
current feed items, keeps only ones not seen before (by link), and appends
them to data/news/articles.parquet.

No API key needed. Feed list is intentionally business/markets/geopolitics
focused, matching the industries in src/valuechain/registry.py.
"""
import hashlib
from datetime import datetime, timezone

import feedparser
import pandas as pd

FEEDS = {
    "reuters_business": "https://www.reutersagency.com/feed/?best-topics=business-finance",
    "reuters_world": "https://www.reutersagency.com/feed/?best-topics=world",
    "ap_business": "https://rss.app/feeds/ap-business.xml",  # placeholder-style aggregator; swap for a working AP RSS if this 404s
    "google_news_tariffs": "https://news.google.com/rss/search?q=tariff+OR+%22export+controls%22+OR+%22supply+chain%22&hl=en-US&gl=US&ceid=US:en",
    "google_news_fed": "https://news.google.com/rss/search?q=%22Federal+Reserve%22+OR+FOMC+OR+Powell&hl=en-US&gl=US&ceid=US:en",
    "google_news_trump_business": "https://news.google.com/rss/search?q=Trump+tariff+OR+Trump+China+OR+Trump+trade&hl=en-US&gl=US&ceid=US:en",
}

ARTICLES_PATH = "data/news/articles.parquet"


def _article_id(link: str) -> str:
    return hashlib.sha256(link.encode()).hexdigest()[:16]


def fetch_new_articles() -> pd.DataFrame:
    try:
        existing = pd.read_parquet(ARTICLES_PATH)
        seen_ids = set(existing["article_id"])
    except FileNotFoundError:
        existing = pd.DataFrame(columns=["article_id", "source", "published_utc", "title", "summary", "link"])
        seen_ids = set()

    rows = []
    for source, url in FEEDS.items():
        parsed = feedparser.parse(url)
        for entry in parsed.entries:
            link = entry.get("link", "")
            article_id = _article_id(link)
            if not link or article_id in seen_ids:
                continue
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_utc = (
                datetime(*published[:6], tzinfo=timezone.utc) if published else None
            )
            rows.append({
                "article_id": article_id,
                "source": source,
                "published_utc": published_utc,
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "link": link,
            })
            seen_ids.add(article_id)

    new_df = pd.DataFrame(rows)
    combined = pd.concat([existing, new_df], ignore_index=True) if not new_df.empty else existing
    import os
    os.makedirs("data/news", exist_ok=True)
    combined.to_parquet(ARTICLES_PATH, index=False)
    return new_df


if __name__ == "__main__":
    new = fetch_new_articles()
    print(f"Fetched {len(new)} new articles across {len(FEEDS)} feeds")
