# Market Sentiment: Public-Figure Posts vs Market Reaction

Event-study research project: do posts from Trump, Musk (and later, other
figures) on X/Truth Social produce a **statistically significant and
persistent** market reaction — drift or reversion over minutes-to-hours,
not an instantaneous reaction (see caveats below on why direction/latency
was ruled out as the target).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DATABENTO_API_KEY
```

## Data sources

| Source | Module | Cost | Coverage |
|---|---|---|---|
| Trump tweets (X) | `src/ingestion/trump_x_archive.py` | Free | 2009–2018 only ([bpb27/trump_tweet_data_archive](https://github.com/bpb27/trump_tweet_data_archive)) |
| Trump posts (Truth Social) | `src/ingestion/trump_truth_social.py` | Free | 2022–present, updates every ~5min (CNN mirror) |
| Musk tweets (X) | `src/ingestion/musk_x_twscrape.py` | Free, unofficial | Needs your own X account pool — see module docstring. No SLA, X breaks scrapers periodically. |
| Crypto (BTC/ETH/DOGE) | `src/ingestion/crypto_binance.py` | Free | 1-minute klines since Aug 2017 |
| US equities/ETFs/indices (SPY, QQQ, TSLA...) | `src/ingestion/equities_databento.py` | Pay-per-use, ~tens of USD for event-study volumes | Minute OHLCV via `EQUS.MINI` dataset |
| US stock options | not built yet | Pay-per-use (Databento `OPRA.PILLAR`) | Deferred until the underlying-asset event study is validated |

**Gap**: no confirmed free source yet for other tech CEOs, non-US world
leaders, or central bank officials — figures are currently limited to
Trump + Musk. There's also no direct S&P500/Nasdaq index feed; SPY/QQQ are
used as tradeable proxies.

## Event study pipeline (`src/eventstudy/`)

1. `align.py` — aligns each post's timestamp to a price window (default
   -30min to +24h) on a chosen asset's 1-minute bars.
2. `abnormal_returns.py` — computes returns relative to a benchmark asset
   over the same window (market-model simplification with beta=1 — the
   standard approach in short intraday event studies), producing the
   abnormal return per event per minute offset.
3. `stats.py` — t-tests and bootstrap confidence intervals on the average
   cumulative abnormal return (CAR) at each offset, to tell signal from
   noise.

See the docstrings for a worked example (Trump tweets vs BTC/ETH is used
as a pipeline smoke test in development — not a real hypothesis, since
those tweets weren't crypto-related).

## Why this shape

- **Not chasing instantaneous reaction.** Without colocated infrastructure,
  competing on the first seconds after a post is a losing race against
  desks that already do this systematically (e.g. JPMorgan's "Volfefe"
  index). The target is drift/reversion over minutes-to-hours, which is
  tradeable with ordinary REST-API latency.
- **Academic precedent is directionally positive but modest.** Event
  studies on Trump tweets (Born, Myers & Clark 2017; Brans & Scholtens
  2020) and Musk crypto tweets (Ante 2023) find real abnormal returns
  concentrated in strongly-sentiment-charged posts, often losing
  significance within days and NOT significant in aggregate without
  sentiment conditioning — a warning against naively testing "all posts"
  and expecting a clean signal.

## Scope

Asset classes: **stocks, indices (via SPY/QQQ proxies), and crypto.**
Forex/commodities/CFDs were considered (Dukascopy, free) but dropped to
keep scope focused. Stock options are a likely next step once the
underlying-asset event study shows signal — deferred for now since they
add real complexity (implied vol, greeks, expiries) on top of an
unvalidated hypothesis.

## Task backlog

- Curate events (filter posts by mentioned ticker/topic, not just author)
  instead of treating every post as a market-moving event.
- Extend figure coverage once a viable source is found for CEOs/world
  leaders/central bankers.
- Once there's signal on the underlying, add US stock options ingestion
  (Databento `OPRA.PILLAR`).
