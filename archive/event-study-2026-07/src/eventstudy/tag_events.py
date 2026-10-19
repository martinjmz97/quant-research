"""
Tags each post with the asset(s) it plausibly moves, so the event study
runs on a curated subset instead of treating every post as market-moving
(the academic precedent — Born/Myers/Clark 2017, Brans & Scholtens 2020 —
consistently warns that testing "all posts" against "all returns" washes
out the signal; effects concentrate in posts that name a company or a
clear macro trigger).

Scope matches the project's asset classes: individual stocks + crypto +
broad-index proxies (SPY/QQQ) for macro-level posts (tariffs, Fed, trade).
Extend TICKER_KEYWORDS / MACRO_KEYWORDS as new companies/topics come up —
this is a starting list, not exhaustive.
"""
import re

import pandas as pd

# symbol -> keywords/aliases that, if present in a post, tag it for that symbol.
# Keys match what the ingestion modules expect: Binance symbols (BTCUSDT etc.)
# and Databento raw_symbol tickers (TSLA, SPY, ...).
TICKER_KEYWORDS = {
    "TSLA": ["tesla", "elon musk", r"\belon\b"],
    "BTCUSDT": ["bitcoin", r"\bbtc\b"],
    "ETHUSDT": ["ethereum", r"\beth\b"],
    "DOGEUSDT": ["dogecoin", r"\bdoge\b"],
    "BA": ["boeing"],
    "LMT": ["lockheed martin", "lockheed"],
    # bare "ford" excludes "Henry Ford" (his frequent motivational-quote
    # attribution, unrelated to Ford Motor Co. — ~50% of naive "ford" matches).
    "F": [r"\bford motor\b", r"(?<!henry )\bford\b"],
    "GM": ["general motors", r"\bgm\b"],
    "AAPL": ["apple inc", r"\bapple\b", "tim cook"],
    "AMZN": ["amazon", "jeff bezos", "bezos"],
    "META": ["meta platforms", "zuckerberg", "facebook inc"],
}

# Macro/geopolitical triggers that move the broad market rather than one
# company — tagged against index proxies instead of a single ticker.
MACRO_KEYWORDS = {
    "SPY": ["tariff", "trade war", "trade deal", r"\bfed\b", "federal reserve",
            "interest rate", "inflation", r"\bchina\b", "stock market", r"\bdow\b",
            r"\bs&p\b", "recession", "government shutdown"],
    "QQQ": ["tariff", "trade war", r"\bfed\b", "federal reserve", "interest rate",
            "inflation", "big tech", "antitrust"],
}

ALL_KEYWORDS = {**TICKER_KEYWORDS, **MACRO_KEYWORDS}
_COMPILED = {
    symbol: re.compile("|".join(patterns), re.IGNORECASE)
    for symbol, patterns in ALL_KEYWORDS.items()
}


def tag_posts(posts: pd.DataFrame, content_col: str = "content") -> pd.DataFrame:
    """
    posts: any of the ingestion modules' output (must have `content_col`).
    Returns posts with an added `matched_symbols` column (list[str], empty
    if the post doesn't match anything in the keyword map) and
    `is_market_relevant` (bool).
    """
    def match(text: str) -> list[str]:
        if not isinstance(text, str) or not text:
            return []
        return [symbol for symbol, pattern in _COMPILED.items() if pattern.search(text)]

    out = posts.copy()
    out["matched_symbols"] = out[content_col].map(match)
    out["is_market_relevant"] = out["matched_symbols"].map(len) > 0
    return out


def curated_events(posts: pd.DataFrame, content_col: str = "content") -> pd.DataFrame:
    """Long format: one row per (post_id, matched symbol) — ready to feed
    into eventstudy.align/abnormal_returns per symbol."""
    tagged = tag_posts(posts, content_col)
    relevant = tagged[tagged["is_market_relevant"]]
    return relevant.explode("matched_symbols").rename(columns={"matched_symbols": "symbol"})


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/trump_truth_social.parquet"
    posts = pd.read_parquet(path)
    events = curated_events(posts)
    print(events["symbol"].value_counts())
    print(f"\n{len(events)} curated events out of {len(posts)} raw posts "
          f"({len(events) / len(posts):.1%})")
