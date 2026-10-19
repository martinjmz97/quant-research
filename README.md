# Quantitative research: prediction-market making and an event-study null result

Two research projects, both closed with documented negative results.

1. **Market making on Polymarket's order book (July 2026).** Can a quoting model adapted to a binary payoff earn
   a positive edge? Tested by simulated ("shadow") quoting against the live order book and against recorded tape.
2. **Event study of public information vs. market prices (closed 2026-07-08).** Do posts by public figures, or
   supply-chain theses, move markets in a capturable way? Archived in [`archive/event-study-2026-07`](archive/event-study-2026-07).

The research logs are written in Spanish. The code, comments and tests are in English.

## Market-making result

All figures come from simulated quoting; this repository contains no code that places orders.

| Test | Result |
|---|---|
| Shadow quoter with protections (stop-quoting, active flatten, per-event risk cap), 50 events, grouped by event to avoid pseudo-replication | Mean PnL per event was negative in every run, t ≈ −3.4 to −3.5 (df ≈ 45–49). The worst single event was about 10% of the total loss, so it is not an outlier effect. |
| Widening the half-spread from 0.01 to 0.08 | No cure. Organic fills improved, forced flattens worsened at the same rate, and the two cancelled. |
| Market-wide toxic-flow detector calibrated on 48,446 real trades | Order-flow imbalance is almost always saturated (median 0.97), so there are no discrete "toxic moments" to detect. A/B PnL change of about 1%, indistinguishable from noise. |
| Skewing quotes in the direction of persistent flow | Worse: PnL 32% lower and variance almost tripled. |
| Price calibration of traded prices vs. outcomes (29 decisive matches, 5 price bins) | No bin significant under a two-sided test (most suggestive p = 0.107). Small sample, so bias is neither confirmed nor ruled out. |

**Interpretation.** Four consistent null or negative results. In a binary market that converges monotonically to a known
outcome, inventory that is not closed before convergence pays the full move, and no spread, toxicity or skew adjustment
reduced that without also removing most of the volume that makes the strategy workable. This is the place where equity
market-making intuition stops transferring. Details, caveats and open questions are in [`POLYMARKET_MM.md`](POLYMARKET_MM.md).

## Repository layout

```
POLYMARKET_MM.md      research log: API/CLOB/fee research, model derivation, experiments, conclusions
src/ingestion/        Polymarket catalog, discovery, active markets and price-history ingestion
scripts/              order-book recorder, shadow quoter (live and backtest), spread sweep, calibration, dashboard
tests/                140 tests (pytest)
archive/              earlier event-study research with its own README and CONCLUSIONS.md
```

## Running the tests

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
```

The recorded data (order-book tape, price histories, market catalog) is not included because of its size; it is
git-ignored under `data/`. The ingestion scripts regenerate it from Polymarket's public APIs.

## Method

- Claims need a derivation, a citation or a test that can refute them.
- Every number states its data, window and the conditions that would break it.
- Results are grouped at the level of independent units (events), not individual tokens.
- A null result that is well demonstrated is preferred over an unverified positive one.
