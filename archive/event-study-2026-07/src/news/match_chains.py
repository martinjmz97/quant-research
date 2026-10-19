"""
Matches news article text against the value-chain registry (keywords per
chokepoint), surfacing which companies might be affected — direct,
indirect, or beneficiary — before the market fully connects the dots.
"""
import re

import pandas as pd

from valuechain.registry import REGISTRY, thesis_for


def _compile_patterns():
    patterns = []
    for industry, entries in REGISTRY.items():
        for entry in entries:
            if not entry["keywords"]:
                continue
            pattern = re.compile("|".join(re.escape(kw) for kw in entry["keywords"]), re.IGNORECASE)
            patterns.append((industry, entry["chokepoint"], pattern, entry["companies"]))
    return patterns


_PATTERNS = _compile_patterns()


def match_article(title: str, summary: str = "") -> list[dict]:
    """Returns a list of matches: one per chokepoint theme found in the text."""
    text = f"{title} {summary}"
    matches = []
    for industry, chokepoint, pattern, companies in _PATTERNS:
        if pattern.search(text):
            matches.append({
                "industry": industry,
                "chokepoint": chokepoint,
                "companies": companies,
                "thesis_90d": thesis_for(industry, chokepoint),
            })
    return matches


def match_articles(articles: pd.DataFrame) -> pd.DataFrame:
    """
    articles: DataFrame with columns [article_id, published_utc, title, summary, link]
    Returns long format: one row per (article_id, chokepoint match).
    """
    rows = []
    for _, article in articles.iterrows():
        matches = match_article(article.get("title", ""), article.get("summary", ""))
        for m in matches:
            rows.append({
                "article_id": article["article_id"],
                "published_utc": article["published_utc"],
                "title": article["title"],
                "link": article.get("link", ""),
                "industry": m["industry"],
                "chokepoint": m["chokepoint"],
                "companies": m["companies"],
                "thesis_90d": m["thesis_90d"],
            })
    columns = ["article_id", "published_utc", "title", "link", "industry", "chokepoint", "companies", "thesis_90d"]
    return pd.DataFrame(rows, columns=columns)
