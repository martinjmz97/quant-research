"""
Historical/streaming tweets for accounts without a curated archive (e.g.
Elon Musk — @elonmusk has no equivalent to the Trump Twitter Archive) via
`twscrape`, unofficial scraping that logs in with a pool of real X accounts
instead of the paid API. No official SLA — X can and does break this
periodically; treat it as best-effort, not a production dependency.

One-time setup (you must do this yourself, it needs real X accounts you
control — this is not something that can be automated on your behalf):

    from twscrape import API
    api = API()  # creates accounts.db (SQLite) in the working directory
    await api.pool.add_account("username", "password", "email", "email_password")
    await api.pool.login_all()

After that, this module just queries through the same accounts.db.
"""
import asyncio

import pandas as pd
from twscrape import API, gather


async def _fetch_user_tweets(username: str, limit: int = 500) -> pd.DataFrame:
    api = API()  # reads ./accounts.db set up per the module docstring
    user = await api.user_by_login(username)
    if user is None:
        raise RuntimeError(f"Could not resolve @{username} — check your account pool is logged in.")

    tweets = await gather(api.user_tweets(user.id, limit=limit))
    rows = [{
        "post_id": str(t.id),
        "author": username,
        "platform": "x",
        "timestamp_utc": t.date,
        "content": t.rawContent,
        "retweet_count": t.retweetCount,
        "favorite_count": t.likeCount,
    } for t in tweets]
    return pd.DataFrame(rows)


def fetch_user_tweets(username: str = "elonmusk", limit: int = 500) -> pd.DataFrame:
    return asyncio.run(_fetch_user_tweets(username, limit))


if __name__ == "__main__":
    import sys
    username = sys.argv[1] if len(sys.argv) > 1 else "elonmusk"
    out = fetch_user_tweets(username)
    out.to_parquet(f"data/raw/{username}_x.parquet", index=False)
    print(f"Saved {len(out)} tweets for @{username}")
