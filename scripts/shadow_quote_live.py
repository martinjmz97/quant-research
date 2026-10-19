"""Live shadow market-making — tails the order-book recording produced by
record_orderbook.py and simulates resting quotes against the REAL book
(best_bid/best_ask from the feed), not trade-print proxying like
scripts/shadow_quote_backtest.py.

Still simplified the same way that backtest was: no queue-position model
(a fill is recorded whenever the market's best_bid/best_ask reaches our
hypothetical quote — optimistic, we're not modeling whether we'd actually
be at the front of that price level). What's different from the
historical backtest is precision: this uses the CLOB's actual best_bid/
best_ask as reported live, not a trade-tape proxy — the gap this closes
is exactly the "no hay histórico de quotes" limitation flagged earlier
(see POLYMARKET_MM.md) — it only works going forward, for whatever we
record from here on.

Meant to run continuously (launchd on a remote host) against
data/raw/polymarket/orderbook_live/worldcup_semifinals.jsonl while
record_orderbook.py keeps appending to it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections import deque
from pathlib import Path

from polymarket.clients.public import PublicClient

# Overridable via env var so scripts/spread_sweep_backtest.py can replay the
# same recorded tape under different spreads in separate subprocesses (needed
# because SKEW_MAX_SHIFT/REQUOTE_DRIFT_THRESHOLD below are derived from this
# at import time — a single process can't hold two spread configurations at
# once). Default unchanged, so live/production behavior is untouched unless
# this is set explicitly.
HALF_SPREAD = float(os.environ.get("SHADOW_HALF_SPREAD", "0.01"))
# $5 is Polymarket's real minimum order size (verified: uniform across
# all 10,837 rows of the sports catalog, market.trading.minimum_order_size)
# — the earlier $2 was below the platform's actual floor, unrealistic.
MAX_FILL_USD = 5.0
RESOLUTION_CHECK_INTERVAL_S = 300

# --- live game status --- replaces trusting a guessed kickoff timestamp
# for widening decisions. Found live (2026-07-17): the WNBA kickoff
# (KICKOFFS below) was an unverified guess from catalog end_date, and it
# turned out liberty_win/wings_win kept trading at 0.45-0.55 12+ hours
# after that assumed kickoff — the real game had already finished
# (confirmed via `event.sports.period == "POST"`) while the book hadn't
# repriced and no static window ever covered the actual game. Fix: poll
# `PublicClient.get_event(id=...)` per EVENT (not per market — a 3-way
# soccer market has 3 tokens sharing one event/game) and read
# `event.sports.period`. Verified against 4 real events: `None` for two
# soccer matches that hadn't started, `"POST"` for the finished WNBA game,
# `"VFT"` for the finished MLB game — `period is None` reliably means
# "not started", any non-None value means the game has started or ended.
GAME_STATUS_CHECK_INTERVAL_S = 60

# empirically observed terminal `period` values — NOT an exhaustive enum
# (the field is a raw string from the Gamma API, no enum type exists in
# the SDK). Only these two are directly confirmed live so far. A sport
# whose terminal code isn't here yet still gets the existing price-based
# (_near_resolution) and REST (market.state.closed) protections as
# backstops — this doesn't replace those, it catches the gap between
# "game literally over" and "book has repriced / market officially
# resolved" that neither of those catches on its own.
GAME_OVER_PERIODS = {"POST", "VFT"}

# --- inventory skew (the core A-S reservation-price mechanism, missing
# until now) --- reservation = fair_value - position * skew_per_token,
# where skew_per_token is set so a FULLY-capped position shifts the
# reservation by SKEW_MAX_SHIFT. Long position -> reservation below fair
# value (more eager to sell, less eager to buy more); short -> above.
MAX_POSITION_USD = 20.0  # per-token cap — a slice of $100 across ~8 tracked tokens
SKEW_MAX_SHIFT = HALF_SPREAD * 3  # at 100% of the cap, reservation shifts 3c

# --- market-flow skew (leans the reservation into the persistent
# imbalance instead of trying to detect/avoid it, see MARKET_VPIN_ENABLED
# above for why avoiding it didn't work) --- signed order-flow imbalance
# from real trades (buy_vol-sell_vol)/(buy_vol+sell_vol) over the last
# MARKET_FLOW_SKEW_WINDOW_TRADES trades ADDS to the reservation (unlike
# the inventory skew above, which SUBTRACTS): positive (BUY-heavy) flow
# predicts near-term upward price drift (Cont/Kukanov/Stoikov-style OFI
# price impact), so both bid and ask should lead that drift rather than
# stay pinned to the stale mid — the same "stale quote gets picked off
# by informed flow" mechanism already identified as the reason
# forced_flatten losses grow with wider HALF_SPREAD (see "Barrido de
# HALF_SPREAD").
#
# Calibrated against the same 48,446-trade tape used for MARKET_VPIN:
# 80% of tokens with >=10 real trades have a signed imbalance > 0.5 over
# their WHOLE history, 0% have < -0.5 — this is a near-permanent
# structural BUY bias (matches the historical BUY:SELL~30-40:1 finding),
# not a signal that flips direction often. Checked at the rolling-window
# level too, on the 3 busiest tokens: sign changes in only 12-37 of
# ~1700-2200 rolling observations (~1-2%). Practical consequence: this
# mostly acts as a persistent upward bias on reservation, not a fast
# direction-following signal — flagged here so the backtest result isn't
# read as "the skew reacted to changing conditions" when the underlying
# signal barely changes sign.
MARKET_FLOW_SKEW_ENABLED = os.environ.get("SHADOW_MARKET_FLOW_SKEW_ENABLED", "0") == "1"
MARKET_FLOW_SKEW_WINDOW_TRADES = 20  # matches the calibration window
MARKET_FLOW_SKEW_MIN_TRADES = 10  # no skew applied below this — matches calibration's stability cutoff
# same magnitude as the inventory skew by default — untuned, first pass.
FLOW_SKEW_MAX_SHIFT = float(os.environ.get("SHADOW_FLOW_SKEW_MAX_SHIFT", str(SKEW_MAX_SHIFT)))

# --- hard inventory limit --- refuse fills that would push |position|
# further from zero past this notional; still allow fills that reduce it.
# This is the backstop — the skew above is meant to keep us away from it.

# --- event-level risk cap --- found live 2026-07-17: WNBA
# (liberty_win short + wings_win long — the yes/no of ONE market) and
# Rumania (voluntari/draw/botoșani — 3 legs of one 3-way split) each lost
# real money because every leg manages its own $20 budget with zero
# awareness that the other leg(s) are the SAME underlying event. A leg
# short "yes" and a leg long "no" of the same market aren't hedged
# against each other — they're the same directional bet twice, and two
# independent $20 caps let that combine to $40+ of real one-directional
# exposure. MAX_EVENT_LOSS_USD bounds the EVENT's combined
# worst-case-if-it-resolves-adversely-right-now (see event_worst_case
# below) — exactly one leg pays out its position at resolution, every
# other leg pays 0, so worst case = sum(cash across every leg) +
# min(position across every leg). Set equal to MAX_POSITION_USD (not
# smaller) — the point is capping the EVENT at what a single leg was
# already allowed alone, not restricting further.
MAX_EVENT_LOSS_USD = 20.0

# --- toxic-flow detector (VPIN-style proxy) --- crude by necessity: we
# use OUR OWN fill-arrival rate as the toxicity signal (no clean way to
# bucket true order-flow imbalance from this feed — see POLYMARKET_MM.md
# "no hay histórico de order book" limitations). If fills in the last
# TOXIC_SHORT_WINDOW_S come in faster than TOXIC_RATE_MULTIPLIER times the
# rate over TOXIC_LONG_WINDOW_S, widen sharply for a cooldown. This is
# reactive by construction (fires after the first toxic fill, not
# before) — same acknowledged limitation as the doc's VPIN section.
TOXIC_SHORT_WINDOW_S = 120
TOXIC_LONG_WINDOW_S = 1800
TOXIC_RATE_MULTIPLIER = 3.0
TOXIC_WIDEN_FACTOR = 4.0
TOXIC_COOLDOWN_S = 120

# --- market-wide flow detector (real VPIN attempt, not self-referential)
# --- the detector above only sees OUR OWN fills, so it can't fire until
# we've already been hit at least once. The CLOB feed's `last_trade_price`
# events (asset_id/side/size per real execution, ANY participant) were
# confirmed present in the recorded tape 2026-07-18 and were previously
# unused — process_message had no branch for that event_type at all.
#
# Two candidate signals were calibrated against the real tape (48,446
# last_trade_price events across 143 tokens) before picking one:
#
# 1. Genuine VPIN — directional imbalance |buy_vol-sell_vol|/total_vol
#    over a rolling window of real trades. REJECTED as a toxicity gate:
#    median imbalance over a 20-trade window is 0.97 (of 45,852
#    observations) — order flow in these markets is almost always
#    heavily one-sided, not intermittently one-sided (consistent with
#    the BUY:SELL~30-40:1 finding from the historical trade-tape
#    analysis, now confirmed at tick granularity too). A level threshold
#    can't distinguish "toxic now" from "normal for this market" when
#    normal already sits near the ceiling almost all the time — this
#    signal would be better used to SKEW quotes toward the imbalance's
#    direction than as an on/off gate. Not implemented (out of scope for
#    this pass — see POLYMARKET_MM.md "Barrido de VPIN" for the
#    calibration numbers).
# 2. Flow-RATE anomaly — same short/long window ratio shape as the
#    self-fill detector above, fed by ALL real trades instead of just
#    ours. This DOES have a usable distribution: p50=1.93, p90=7.05,
#    p95=9.44 (same TOXIC_SHORT_WINDOW_S/TOXIC_LONG_WINDOW_S windows).
#    Reusing TOXIC_RATE_MULTIPLIER=3.0 directly would flag toxic ~31% of
#    the time — that threshold was calibrated for OUR sparse fills, not
#    the much busier full market tape, so it doesn't transfer as-is.
#    MARKET_VPIN_RATE_THRESHOLD=7.0 (~p90) chosen as a first pass, an
#    empirical cutoff from this one tape, not a theoretically derived
#    number — needs revisiting once observed live, same caveat as every
#    other threshold in this file.
#
# Gated behind SHADOW_MARKET_VPIN_ENABLED (default off, unchanged
# production behavior) so it can be A/B'd via scripts/spread_sweep_backtest.py
# against the self-fill-only baseline before ever touching the live process.
MARKET_VPIN_ENABLED = os.environ.get("SHADOW_MARKET_VPIN_ENABLED", "0") == "1"
MARKET_VPIN_RATE_THRESHOLD = float(os.environ.get("SHADOW_MARKET_VPIN_THRESHOLD", "7.0"))

# --- match-clock widening --- deterministic, doesn't wait for the
# detector to confirm anything — widen through the known high-risk window
# regardless. Window matches the "ventana de juego" already used for the
# dashboard's in-game shading: kickoff-15min to kickoff+130min.
MATCH_CLOCK_WIDEN_FACTOR = 2.5
MATCH_WINDOW_PRE_MIN = 15
MATCH_WINDOW_POST_MIN = 130

# --- requote policy --- THE fix for "recentering every single tick means
# only single-tick jumps can ever cross us, gradual drift never does"
# (verified empirically: a real 0.453->0.459 drift over 1h produced zero
# fills). Real market makers don't have zero-latency requoting either —
# there's always some gap between observing a price change and actually
# canceling/replacing the resting order, and during that gap the market
# CAN move past a quote that hasn't been updated yet. Modeling that gap
# explicitly (instead of implicitly assuming it's zero) is what lets
# accumulated drift — not just discrete jumps — actually cross us.
# Requote triggers on whichever comes first: fair value has drifted more
# than REQUOTE_DRIFT_THRESHOLD since the quote was last set, or
# REQUOTE_MAX_INTERVAL_S has elapsed, or a fill just happened.
REQUOTE_DRIFT_THRESHOLD = HALF_SPREAD * 0.5
REQUOTE_MAX_INTERVAL_S = 30

# --- minimum requote latency --- we don't model queue position, but we
# also can't assume a freshly (re)computed quote is instantly resting in
# the book — canceling the old order and posting the new one is a real
# HTTP round trip (sign + submit), not zero-latency. Without this, a fill
# immediately recenters the quote (just_filled=True forces it) and the
# very next tick — which can arrive within milliseconds — crosses the
# brand-new quote again, before a real replacement order would even be
# live. This is exactly what happened live: mets_win/phillies_win show 3-4
# fills in under 1 second around 2026-07-16 22:44:33-34 UTC (gaps of
# ~180-490ms), position flipping +19.5->+9.7->-1.9 tokens — a real MM
# can't cancel/replace/get-filled-again that fast. 1s is a conservative
# placeholder, not measured against Polymarket's actual order-placement
# latency — chosen only to comfortably exceed the observed gaps.
MIN_REQUOTE_LATENCY_S = 1.0

# --- active flatten near resolution --- stop-quoting (above) only
# withdraws OUR quote — it does nothing about inventory already open when
# fv gets near-certain. That inventory would otherwise just ride,
# unprotected, until the 5-minute REST resolution poll force-closes it
# (RESOLUTION_CHECK_INTERVAL_S). Found live: t1_win sat short 10.497
# tokens marked at fv=0.999 (near-total loss already priced in) and
# hanwha_win sat long 32.186 marked at fv≈0.001, both just watching the
# clock with no way to act sooner than the next poll. This does NOT
# rescue the mark-to-market — by the time fv is this extreme, the
# position is already worth ~what it'll pay out. What it DOES do: turn
# an open position (exposed to a last-second reversal for however long
# it takes the slow REST poll to notice) into realized cash immediately,
# via a taker cross against the live best_bid/best_ask instead of our own
# resting quote. Taker pays the fee (unlike every other fill in this
# model, which assumes we're the 0%-fee maker side) — same formula as
# POLYMARKET_MM.md's "Fees" section, `fee = tokens × feeRate × p × (1−p)`,
# sports feeRate=0.05 as documented there as of 2026-07-15 (verify live
# before real money — Polymarket changes this).
TAKER_FEE_RATE_SPORTS = 0.05

# --- stop-quoting (withdraw entirely, not just widen) --- already called
# for in POLYMARKET_MM.md ("cerca de T conviene un límite duro / stop-
# quoting explícito, no confiar en la fórmula") but never actually built
# — until now only widening existed, never a full withdrawal. Two
# triggers:
# (1) fair value near-certain (within RESOLUTION_PROXIMITY_STOP of 0 or
#     1) — the p(1-p) variance budget has essentially run out, so there's
#     ~nothing left to compensate spread-capture for, but a last-second
#     reversal jump risk remains disproportionate to the remaining edge.
# (2) toxic-flow detector fires AGAIN while still inside the widening
#     cooldown from the previous trigger — one trigger widens (maybe just
#     noise), a second one back-to-back means the whole regime shifted,
#     not a one-off — escalate to a full stop, not just wider quotes.
RESOLUTION_PROXIMITY_STOP = 0.03
STOP_QUOTING_DURATION_S = 600

# --- resolution-stop hysteresis --- found live 2026-07-17: fv bouncing
# right at the RESOLUTION_PROXIMITY_STOP boundary (Rumania,
# fc_voluntari_win/fc_botoșani_win) made the single-threshold check flap
# — stop, resume the instant fv ticks back above 0.03, get picked off
# again seconds later on the way back down, flatten again — 4 cycles in
# ~25min, each realizing a fresh loss near price~0/1 (the worst possible
# fill price). Reuses the existing `stopped_until` field (same one the
# toxic-flow escalation uses, see STOP_QUOTING_DURATION_S) so a fresh
# touch of the near-resolution zone keeps quoting withdrawn for at least
# this long AFTER THE LAST touch, not just until fv barely crosses back
# over 0.03. Same value as STOP_QUOTING_DURATION_S today (600s) — kept
# as its own named constant since the two are conceptually independent
# and may need to diverge later. This reduces but doesn't fully
# eliminate the pattern for a market that keeps genuinely re-touching
# the boundary across many minutes, not just seconds.
RESOLUTION_STOP_COOLDOWN_S = 600

# --- no-real-market stop --- found live: some thinner markets (esports)
# report best_bid=0.0/best_ask=1.0 — the platform's placeholder for "no
# real resting liquidity", not an actual 2-sided market. Quoting fv=0.5
# around that is meaningless (there's no real reference price at all).
# Any real market's spread should be a small fraction of the price range;
# a spread this wide is the tell.
MAX_SANE_SPREAD = 0.3

# Token metadata (KICKOFFS/TOKEN_LABELS/TOKEN_SIDE/MARKET_IDS/EVENT_IDS)
# used to be hand-maintained dicts, one match hardcoded at a time —
# replaced 2026-07-17 with a dynamic load from
# scripts/discover_active_markets.py's output (TRACKED_MARKETS_PATH
# below), refreshed periodically by refresh_tracked_tokens() (see
# TOKEN_REFRESH_INTERVAL_S). These dicts only ever grow (refresh adds new
# tokens, never removes existing ones) — a token that falls out of the
# discovery script's active-now window must keep its metadata for as long
# as this process runs, or check_resolutions/check_game_status would
# silently stop tracking a market with an still-open position (same bug
# class already found and fixed once in process_message, see
# TestProcessMessageScopeFilter).
KICKOFFS: dict[str, dt.datetime] = {}
TOKEN_LABELS: dict[str, str] = {}
TOKEN_SIDE: dict[str, str] = {}
MARKET_IDS: dict[str, int] = {}
EVENT_IDS: dict[str, int] = {}

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "polymarket" / "orderbook_live"
IN_PATH = DATA_DIR / "live_book.jsonl"
FILLS_PATH = DATA_DIR / "shadow_fills.jsonl"
STATE_PATH = DATA_DIR / "shadow_state.json"
TRACKED_MARKETS_PATH = DATA_DIR / "tracked_markets.json"
# durable, append-only, never renamed/reset — see force_close_at_resolution.
RESOLVED_GAMES_PATH = DATA_DIR / "resolved_games.jsonl"
# durable, append-only — see ShadowBook._maybe_close_round_trip.
ROUND_TRIPS_PATH = DATA_DIR / "round_trips.jsonl"
ROUND_TRIP_EPS = 0.5  # tokens; matches the threshold used in prior manual analysis
TOKEN_REFRESH_INTERVAL_S = 300


def refresh_tracked_tokens() -> None:
    """Re-read TRACKED_MARKETS_PATH (written by
    scripts/discover_active_markets.py) and merge any new tokens into the
    module-level dicts above. Additive only, by design — see the comment
    above KICKOFFS for why a token is never removed once known."""
    if not TRACKED_MARKETS_PATH.exists():
        return
    data = json.loads(TRACKED_MARKETS_PATH.read_text())
    for token in data["tokens"]:
        asset_id = token["asset_id"]
        TOKEN_LABELS[asset_id] = token["label"]
        TOKEN_SIDE[asset_id] = token["side"]
        MARKET_IDS[asset_id] = token["market_id"]
        EVENT_IDS[asset_id] = token["event_id"]
        if token["game_start_time"] is not None:
            KICKOFFS[asset_id] = dt.datetime.fromisoformat(token["game_start_time"])


def event_worst_case(cash_total: float, positions: list[float]) -> float:
    """Combined payout if the event resolves adversely RIGHT NOW, across
    every tracked leg: exactly one leg's position pays out at 1 (whichever
    outcome actually happens), every other leg's position pays 0 — so the
    worst case is whichever leg has the smallest (most negative, if
    short) position. See MAX_EVENT_LOSS_USD for why this needs to be
    checked across legs, not per-token."""
    return cash_total + min(positions)


class ShadowBook:
    def __init__(self, asset_id: str):
        self.asset_id = asset_id
        self.label = TOKEN_LABELS.get(asset_id, asset_id[:12])
        self.best_bid: float | None = None
        self.best_ask: float | None = None
        self.cash = 0.0
        self.position = 0.0
        self.n_fills = 0
        self.max_abs_position = 0.0
        self.worst_mtm = 0.0
        self.resolved = False
        self.our_bid: float | None = None
        self.our_ask: float | None = None
        self.quote_active_at: dt.datetime | None = None
        self.last_requote_fv: float | None = None
        self.last_requote_ts: dt.datetime | None = None
        self.fill_times: deque[dt.datetime] = deque()
        self.market_trade_times: deque[dt.datetime] = deque()
        self.market_trade_flow: deque[tuple[str, float]] = deque()  # (side, size), count-windowed
        self.toxic_until: dt.datetime | None = None
        self.n_blocked_by_inventory_cap = 0
        self.n_toxic_widenings = 0
        self.n_requotes = 0
        self.stopped_until: dt.datetime | None = None
        self.n_stops = 0
        self.n_forced_flattens = 0
        self.game_period: str | None = None
        self.round_trip_epoch_cash = 0.0
        self.n_round_trips = 0
        self.round_trip_pnls: list[float] = []

    def update_game_period(self, period: str | None) -> None:
        """Set from the periodic live game-status poll (check_game_status,
        called from main()) — not from the order-book tick stream."""
        self.game_period = period

    def _maybe_close_round_trip(self, position_before: float, ts: str, reason: str) -> None:
        """A round trip closes when position crosses through zero (sign
        change) or lands within ROUND_TRIP_EPS of it — same sign-flip
        proxy already used for manual round-trip analysis earlier this
        session (fill sizes are token-quantized, so exact 0.0 is rare
        outside a forced flatten/resolution close). Realized PnL for the
        trip = cash now minus cash the last time we were at/through
        flat. Logged to ROUND_TRIPS_PATH — durable and append-only,
        unlike shadow_fills.jsonl (which duplicates on a mid-tape
        restart unless manually archived first; this has the exact same
        limitation today, same discipline required — see
        POLYMARKET_MM.md). Found live: without this tracked as it
        happens, the "distribución de RT" (round-trip distribution) had
        to be reconstructed by hand from archived fills after the fact
        every time — not something to keep redoing manually.

        `reason` records WHICH of the three call sites closed this trip
        ("organic" | "forced_flatten" | "resolution_forced_close") —
        added after a live claim that "half the fills ride to
        resolution" turned out to be unverifiable from this log alone
        (no field distinguished an active close from one that rode to
        the terminal payout). Without this, "we're losing because
        inventory rides to resolution" can't be told apart from "we're
        losing on trips we actively closed" — the fix for one is faster
        flattening, the fix for the other is different (spread/sizing)."""
        sign_before = 1 if position_before > ROUND_TRIP_EPS else (-1 if position_before < -ROUND_TRIP_EPS else 0)
        sign_after = 1 if self.position > ROUND_TRIP_EPS else (-1 if self.position < -ROUND_TRIP_EPS else 0)
        if sign_before == 0 or sign_after == sign_before:
            return
        pnl = self.cash - self.round_trip_epoch_cash
        self.n_round_trips += 1
        self.round_trip_pnls.append(pnl)
        with ROUND_TRIPS_PATH.open("a") as f:
            f.write(json.dumps({
                "ts": ts, "asset_id": self.asset_id, "label": self.label,
                "pnl": round(pnl, 4), "n_round_trips_so_far": self.n_round_trips,
                "close_reason": reason,
            }) + "\n")
        self.round_trip_epoch_cash = self.cash

    def _game_confirmed_over(self) -> bool:
        return self.game_period in GAME_OVER_PERIODS

    def _in_match_window(self, now: dt.datetime) -> bool:
        kickoff = KICKOFFS.get(self.asset_id)
        if kickoff is None:
            return False
        rel_min = (now - kickoff).total_seconds() / 60
        return -MATCH_WINDOW_PRE_MIN <= rel_min <= MATCH_WINDOW_POST_MIN

    def _should_requote(self, fv: float, now: dt.datetime, just_filled: bool) -> bool:
        # NOTE: this used to also trigger on `self.our_bid is None`, meant
        # to cover "never quoted yet" — but our_bid is ALSO None while
        # stop-quoting is active, which made every single incoming tick
        # re-evaluate (and re-extend) the toxic/stop state for as long as
        # the book stayed stopped. Confirmed live: mets_win accumulated
        # 39,962 toxic-widening triggers / 39,960 stop-escalations against
        # only 18 real fills — the token's feed sent ~56 msg/s (582,497
        # messages over its ~2h53m lifetime), so a single stuck episode of
        # a few hundred seconds was enough to produce that count. Gating
        # purely on last_requote_ts (set on every requote, including
        # stop transitions) restores the normal drift/interval throttle
        # while stopped instead of firing every message.
        if self.last_requote_ts is None:
            return True
        if just_filled:
            return True
        if abs(fv - self.last_requote_fv) > REQUOTE_DRIFT_THRESHOLD:
            return True
        if (now - self.last_requote_ts).total_seconds() > REQUOTE_MAX_INTERVAL_S:
            return True
        return False

    def record_market_trade(self, ts: str, side: str, size: float) -> None:
        """A real trade from ANY participant on this token (last_trade_price
        feed event) — unlike fill_times (only OUR fills), this sees the
        whole market's flow. Feeds two independent, differently-windowed
        signals: market_trade_times (time-windowed arrival timestamps,
        for the rate-anomaly toxic-flow check — see MARKET_VPIN_ENABLED)
        and market_trade_flow (count-windowed side+size, for the
        directional skew — see MARKET_FLOW_SKEW_ENABLED). A level-based
        imbalance was calibrated as non-discriminative for TOXICITY
        (almost always near-maximally one-sided, not intermittently so)
        but that same persistent bias is exactly what the flow skew
        leans into instead of trying to detect."""
        now = dt.datetime.fromisoformat(ts)
        self.market_trade_times.append(now)
        while self.market_trade_times and (now - self.market_trade_times[0]).total_seconds() > TOXIC_LONG_WINDOW_S:
            self.market_trade_times.popleft()

        self.market_trade_flow.append((side, size))
        while len(self.market_trade_flow) > MARKET_FLOW_SKEW_WINDOW_TRADES:
            self.market_trade_flow.popleft()

    def market_flow_skew(self) -> float:
        """Signed order-flow imbalance over the last
        MARKET_FLOW_SKEW_WINDOW_TRADES real trades, in [-1, 1]: +1 = all
        BUY, -1 = all SELL. Returns 0.0 (neutral, no skew applied) below
        MARKET_FLOW_SKEW_MIN_TRADES — not enough data yet to trust the
        ratio, same reasoning as the long_count>=5 floor in
        _check_toxic_flow."""
        if len(self.market_trade_flow) < MARKET_FLOW_SKEW_MIN_TRADES:
            return 0.0
        buy = sum(size for side, size in self.market_trade_flow if side == "BUY")
        sell = sum(size for side, size in self.market_trade_flow if side == "SELL")
        total = buy + sell
        if total <= 0:
            return 0.0
        return (buy - sell) / total

    def _check_toxic_flow(self, now: dt.datetime) -> bool:
        """VPIN-style proxy using our own fill-arrival rate (see module
        docstring for why: no clean order-flow-imbalance bucketing
        available from this feed). Reactive, not predictive — same
        limitation as the doc's VPIN section. Escalates to a full stop
        (not just a widen) if it fires again while still inside the
        cooldown from the previous trigger — one trigger might be noise,
        back-to-back triggers mean the regime actually shifted.

        When MARKET_VPIN_ENABLED, a second independent condition (real
        market-wide trade-rate anomaly, see module docstring) can ALSO
        trigger the same widen/escalate state machine — reuses
        toxic_until/stopped_until/n_toxic_widenings/n_stops so nothing
        downstream (_should_stop_quoting, widening factor) needs to know
        which signal fired. Default off, so production behavior is
        unchanged unless explicitly enabled for a backtest A/B."""
        while self.fill_times and (now - self.fill_times[0]).total_seconds() > TOXIC_LONG_WINDOW_S:
            self.fill_times.popleft()
        short_count = sum(1 for t in self.fill_times if (now - t).total_seconds() <= TOXIC_SHORT_WINDOW_S)
        long_count = len(self.fill_times)
        short_rate = short_count / TOXIC_SHORT_WINDOW_S
        long_rate = long_count / TOXIC_LONG_WINDOW_S
        self_fill_toxic = long_count >= 5 and short_rate > TOXIC_RATE_MULTIPLIER * long_rate and short_count >= 3

        market_toxic = False
        if MARKET_VPIN_ENABLED:
            while self.market_trade_times and (now - self.market_trade_times[0]).total_seconds() > TOXIC_LONG_WINDOW_S:
                self.market_trade_times.popleft()
            m_short = sum(1 for t in self.market_trade_times if (now - t).total_seconds() <= TOXIC_SHORT_WINDOW_S)
            m_long = len(self.market_trade_times)
            if m_long >= 5:
                m_long_rate = m_long / TOXIC_LONG_WINDOW_S
                m_short_rate = m_short / TOXIC_SHORT_WINDOW_S
                market_toxic = m_long_rate > 0 and (m_short_rate / m_long_rate) > MARKET_VPIN_RATE_THRESHOLD

        if self_fill_toxic or market_toxic:
            if self.toxic_until is not None and now <= self.toxic_until:
                self.stopped_until = now + dt.timedelta(seconds=STOP_QUOTING_DURATION_S)
                self.n_stops += 1
            self.toxic_until = now + dt.timedelta(seconds=TOXIC_COOLDOWN_S)
            self.n_toxic_widenings += 1
        return self.toxic_until is not None and now <= self.toxic_until

    def _near_resolution(self, fv: float) -> bool:
        return fv < RESOLUTION_PROXIMITY_STOP or fv > 1 - RESOLUTION_PROXIMITY_STOP

    def _should_stop_quoting(self, fv: float, now: dt.datetime) -> bool:
        if self._near_resolution(fv) or self._game_confirmed_over():
            return True
        if self.best_bid is not None and self.best_ask is not None and (self.best_ask - self.best_bid) > MAX_SANE_SPREAD:
            return True
        return self.stopped_until is not None and now <= self.stopped_until

    def _should_flatten(self, fv: float) -> bool:
        """Near-resolution (price-based) OR the live game-status poll
        confirmed the game is over (see GAME_OVER_PERIODS) — added after
        finding live that liberty_win/wings_win kept trading at 0.45-0.55
        well after the real WNBA game had already finished per
        `event.sports.period == "POST"`: price alone never entered the
        near-resolution zone, so that check alone would have missed it.
        Unlike `_near_resolution`, `_game_confirmed_over` says nothing
        about the spread, so it needs its own explicit guard against the
        no-real-market placeholder (best_bid=0/best_ask=1) here."""
        if self.best_bid is None or self.best_ask is None:
            return False
        if (self.best_ask - self.best_bid) > MAX_SANE_SPREAD:
            return False
        return self._near_resolution(fv) or self._game_confirmed_over()

    def _flatten_at_market(self, ts: str, fills_f) -> None:
        """Actively cross the live book to close out any open position,
        instead of leaving it to ride to resolution. Called once
        _should_flatten is true (see TAKER_FEE_RATE_SPORTS docstring for
        why). A no-op once position is already flat, so it's safe to call
        on every tick this zone is active. Same "no market impact" caveat
        as the rest of this model: assumes the whole position fills at
        the current top-of-book price, no slippage from walking the book."""
        if abs(self.position) < 1e-9 or self.best_bid is None or self.best_ask is None:
            return
        position_before = self.position
        tokens = abs(self.position)
        if self.position > 0:
            side, price = "SELL", self.best_bid
        else:
            side, price = "BUY", self.best_ask
        fee = tokens * TAKER_FEE_RATE_SPORTS * price * (1 - price)
        cash_delta = tokens * price - fee if side == "SELL" else -(tokens * price + fee)
        self.cash += cash_delta
        self.position = 0.0
        self.n_fills += 1
        self.n_forced_flattens += 1
        fills_f.write(json.dumps({
            "ts": ts, "asset_id": self.asset_id, "label": self.label,
            "side": side, "price": price, "tokens": tokens, "fee": fee,
            "position_after": 0.0, "cash_after": self.cash,
            "forced_flatten": True,
        }) + "\n")
        fills_f.flush()
        self._maybe_close_round_trip(position_before, ts, "forced_flatten")

    def force_close_at_resolution(self, payout: float, ts: str, fills_f) -> None:
        """Called once, when REST confirms this market resolved. Flattens
        whatever position is open at the terminal payout (0 or 1) instead
        of leaving it silently unrecorded — this is the fix for round
        trips that never close on their own before resolution.

        Also appends a summary line to RESOLVED_GAMES_PATH — a separate,
        append-only, never-renamed file. Found live 2026-07-17: renaming
        the tick-tape file (worldcup_semifinals.jsonl -> live_book.jsonl,
        see POLYMARKET_MM.md "Descubrimiento automático") silently
        erased mets_win/phillies_win/liberty_win/wings_win from the LIVE
        shadow_state.json, because state is entirely reconstructed by
        replaying that tape from the top on every restart — it wasn't
        deleted (still in the archived pre-rename state snapshots), just
        no longer visible without digging through an archive folder. A
        finished game's summary shouldn't depend on the tape's filename
        or on the process never restarting again."""
        if self.resolved:
            return
        self.resolved = True
        if abs(self.position) > 1e-9:
            position_before = self.position
            side = "SELL" if self.position > 0 else "BUY"
            tokens = abs(self.position)
            cash_delta = tokens * payout if side == "SELL" else -tokens * payout
            self.cash += cash_delta
            fills_f.write(json.dumps({
                "ts": ts, "asset_id": self.asset_id, "label": self.label,
                "side": side, "price": payout, "tokens": tokens,
                "position_after": 0.0, "cash_after": self.cash,
                "resolution_forced_close": True,
            }) + "\n")
            fills_f.flush()
            self.position = 0.0
            self.n_fills += 1
            self._maybe_close_round_trip(position_before, ts, "resolution_forced_close")
        self.worst_mtm = min(self.worst_mtm, self.cash)
        with RESOLVED_GAMES_PATH.open("a") as f:
            f.write(json.dumps({
                "resolved_at": ts, "asset_id": self.asset_id, "label": self.label,
                "payout": payout, "final_cash": round(self.cash, 3),
                "n_fills": self.n_fills, "max_abs_position": round(self.max_abs_position, 3),
                "worst_mark_to_market": round(self.worst_mtm, 3),
                "n_forced_flattens": self.n_forced_flattens, "game_period": self.game_period,
            }) + "\n")

    def update(self, best_bid: float, best_ask: float, ts: str, fills_f, siblings: list["ShadowBook"] | None = None) -> None:
        """IMPORTANT FIX: the previous version recomputed our_bid/our_ask
        from THIS SAME tick's (best_bid, best_ask) and then checked
        whether THIS SAME tick's best_bid/best_ask crossed it — that
        condition is mathematically impossible (our_ask = midpoint + H is
        always > best_bid whenever ask >= bid, which is always). Zero
        fills this whole time wasn't "market too quiet", it was a bug —
        no market condition could ever have triggered a fill. Fix: our
        quote is now STATE that persists between calls. Each new market
        update is checked against the PREVIOUS resting quote first, THEN
        we recenter for the next call.

        `siblings`: the OTHER ShadowBook legs of the same event (see
        MAX_EVENT_LOSS_USD), NOT including self. None (the default) skips
        the event-level cap entirely — used when no sibling has been
        discovered yet (single-leg case), matching prior behavior
        exactly; process_message is what wires this up for real."""
        if self.resolved:
            return
        now = dt.datetime.fromisoformat(ts)

        # check the incoming market state against our EXISTING resting
        # quote (set on the previous call) before touching anything.
        # Gated on quote_active_at too: a quote just (re)computed —
        # notably one just recentered by a fill, via just_filled=True —
        # isn't actually live in the book yet (see MIN_REQUOTE_LATENCY_S).
        if (
            self.our_bid is not None
            and self.our_ask is not None
            and self.quote_active_at is not None
            and now >= self.quote_active_at
        ):
            position_before = self.position
            position_notional = self.position * ((self.best_bid + self.best_ask) / 2 if self.best_bid else self.our_bid)
            would_grow_short = best_bid >= self.our_ask and position_notional - MAX_FILL_USD < -MAX_POSITION_USD
            would_grow_long = best_ask <= self.our_bid and position_notional + MAX_FILL_USD > MAX_POSITION_USD

            # event-level cap: exact (not notional-approximated) prospective
            # worst-case, since we need real fill_tokens for this — computed
            # for whichever side is actually being crossed.
            event_would_breach_short = False
            event_would_breach_long = False
            if siblings:
                sibling_cash = sum(b.cash for b in siblings)
                sibling_positions = [b.position for b in siblings]
                if best_bid >= self.our_ask:
                    prospective_tokens = MAX_FILL_USD / self.our_ask
                    prospective_cash = self.cash + prospective_tokens * self.our_ask
                    prospective_position = self.position - prospective_tokens
                    worst_case = event_worst_case(sibling_cash + prospective_cash, sibling_positions + [prospective_position])
                    event_would_breach_short = worst_case < -MAX_EVENT_LOSS_USD
                if best_ask <= self.our_bid:
                    prospective_tokens = MAX_FILL_USD / self.our_bid
                    prospective_cash = self.cash - prospective_tokens * self.our_bid
                    prospective_position = self.position + prospective_tokens
                    worst_case = event_worst_case(sibling_cash + prospective_cash, sibling_positions + [prospective_position])
                    event_would_breach_long = worst_case < -MAX_EVENT_LOSS_USD

            fill = None
            if best_bid >= self.our_ask and not would_grow_short and not event_would_breach_short:
                fill_tokens = MAX_FILL_USD / self.our_ask
                self.cash += fill_tokens * self.our_ask
                self.position -= fill_tokens
                fill = ("SELL", self.our_ask, fill_tokens)
            elif best_ask <= self.our_bid and not would_grow_long and not event_would_breach_long:
                fill_tokens = MAX_FILL_USD / self.our_bid
                self.cash -= fill_tokens * self.our_bid
                self.position += fill_tokens
                fill = ("BUY", self.our_bid, fill_tokens)
            elif would_grow_short or would_grow_long or event_would_breach_short or event_would_breach_long:
                self.n_blocked_by_inventory_cap += 1

            just_filled = fill is not None
            if fill:
                self.n_fills += 1
                self.fill_times.append(now)
                side, price, tokens = fill
                fills_f.write(json.dumps({
                    "ts": ts, "asset_id": self.asset_id, "label": self.label,
                    "side": side, "price": price, "tokens": tokens,
                    "position_after": self.position, "cash_after": self.cash,
                }) + "\n")
                fills_f.flush()
                self._maybe_close_round_trip(position_before, ts, "organic")
        else:
            just_filled = False

        self.best_bid, self.best_ask = best_bid, best_ask
        fv = (best_bid + best_ask) / 2

        # requote ONLY on drift past threshold / max interval / a fill —
        # NOT on every message. This is the actual fix for "recentering
        # every tick means gradual drift never crosses us": between
        # requotes our resting price is genuinely stale, on purpose,
        # modeling the real gap between seeing a price move and acting on
        # it. A big enough accumulated drift during that gap now crosses
        # a quote we haven't gotten around to updating yet — same as a
        # real MM's resting order would.
        if self._should_requote(fv, now, just_filled):
            is_toxic = self._check_toxic_flow(now)  # always evaluate — updates toxic/stop state even if we end up stopping

            if self._should_stop_quoting(fv, now):
                # withdraw entirely — no resting quote at all, not just a
                # wider one. Next call's fill-check block is skipped
                # (guarded on our_bid/our_ask is not None), so nothing can
                # cross a quote that isn't there.
                self.our_bid = None
                self.our_ask = None
                self.quote_active_at = None
                if self._near_resolution(fv):
                    # hysteresis (see RESOLUTION_STOP_COOLDOWN_S): only
                    # count a fresh stop episode if we weren't already
                    # inside one — extends the cooldown every touch, but
                    # n_stops tracks distinct episodes, not renewals.
                    if self.stopped_until is None or now > self.stopped_until:
                        self.n_stops += 1
                    self.stopped_until = now + dt.timedelta(seconds=RESOLUTION_STOP_COOLDOWN_S)
                if self._should_flatten(fv):
                    self._flatten_at_market(ts, fills_f)
            else:
                position_notional = self.position * fv
                skew_frac = max(-1.0, min(1.0, position_notional / MAX_POSITION_USD))
                reservation = fv - skew_frac * SKEW_MAX_SHIFT
                if MARKET_FLOW_SKEW_ENABLED:
                    # ADDS (not subtracts, unlike the inventory skew above)
                    # — positive (BUY-heavy) flow predicts near-term upward
                    # drift, so both quotes lead it instead of lagging the
                    # stale mid. See MARKET_FLOW_SKEW_ENABLED module doc.
                    reservation += self.market_flow_skew() * FLOW_SKEW_MAX_SHIFT

                effective_half_spread = HALF_SPREAD
                # OR, not replace: the static kickoff-window estimate is
                # kept as a pre-kickoff safety margin (widen 15min before
                # the guessed kickoff, in case it's roughly right) even
                # though it's been wrong by hours before (see EVENT_IDS
                # comment) — live confirmation can only ADD widening, an
                # API hiccup on the live poll can't silently remove it.
                if self._in_match_window(now) or self.game_period is not None:
                    effective_half_spread *= MATCH_CLOCK_WIDEN_FACTOR
                if is_toxic:
                    effective_half_spread *= TOXIC_WIDEN_FACTOR

                self.our_bid = reservation - effective_half_spread
                self.our_ask = reservation + effective_half_spread
                self.quote_active_at = now + dt.timedelta(seconds=MIN_REQUOTE_LATENCY_S)

            self.last_requote_fv = fv
            self.last_requote_ts = now
            self.n_requotes += 1

        self.max_abs_position = max(self.max_abs_position, abs(self.position))
        mtm = self.cash + self.position * fv
        self.worst_mtm = min(self.worst_mtm, mtm)

    def snapshot(self) -> dict:
        fv = (self.best_bid + self.best_ask) / 2 if self.best_bid and self.best_ask else None
        mtm = self.cash + self.position * fv if fv is not None else self.cash
        return {
            "label": self.label, "best_bid": self.best_bid, "best_ask": self.best_ask,
            "n_fills": self.n_fills, "position": round(self.position, 3),
            "cash": round(self.cash, 3), "mark_to_market": round(mtm, 3),
            "max_abs_position": round(self.max_abs_position, 3),
            "worst_mark_to_market": round(self.worst_mtm, 3),
            "n_blocked_by_inventory_cap": self.n_blocked_by_inventory_cap,
            "n_toxic_widenings": self.n_toxic_widenings,
            "in_toxic_cooldown": self.toxic_until is not None and dt.datetime.now(dt.timezone.utc) <= self.toxic_until,
            "n_requotes": self.n_requotes,
            "our_bid": self.our_bid, "our_ask": self.our_ask,
            "n_stops": self.n_stops,
            "n_forced_flattens": self.n_forced_flattens,
            "is_stopped": self.our_bid is None and self.our_ask is None and self.last_requote_ts is not None,
            "game_period": self.game_period,
            "n_round_trips": self.n_round_trips,
            "round_trip_pnl_sum": round(sum(self.round_trip_pnls), 4) if self.round_trip_pnls else 0.0,
            "round_trip_pnl_mean": round(sum(self.round_trip_pnls) / len(self.round_trip_pnls), 4) if self.round_trip_pnls else None,
        }


def event_sibling_books(books: dict[str, ShadowBook], asset_id: str) -> list[ShadowBook]:
    """The OTHER legs of the same event as `asset_id` that already have a
    ShadowBook (a sibling with no ticks yet simply isn't in `books`) — see
    MAX_EVENT_LOSS_USD. Empty if this token's event isn't known yet or has
    no other discovered legs, which is a normal, common state early on
    (siblings tick in one at a time, not simultaneously)."""
    event_id = EVENT_IDS.get(asset_id)
    if event_id is None:
        return []
    return [b for aid, b in books.items() if aid != asset_id and EVENT_IDS.get(aid) == event_id]


def process_message(raw, books: dict[str, ShadowBook], ts: str, fills_f) -> None:
    # only tokens in TOKEN_LABELS are in scope — this is also how esports
    # got excluded (2026-07-17, see POLYMARKET_MM.md "Decisiones tomadas"):
    # removing a token from TOKEN_LABELS/KICKOFFS/MARKET_IDS alone does
    # NOT stop tracking it, since this function used to create a
    # ShadowBook for ANY asset_id seen in the feed. Confirmed live: after
    # that removal the restarted process kept quoting the esports tokens
    # under their raw (truncated) asset_id, just without a friendly label.
    if isinstance(raw, list):
        for entry in raw:
            asset_id = entry.get("asset_id")
            bids, asks = entry.get("bids"), entry.get("asks")
            if not asset_id or asset_id not in TOKEN_LABELS or not bids or not asks:
                continue
            best_bid = max(float(b["price"]) for b in bids)
            best_ask = min(float(a["price"]) for a in asks)
            book = books.setdefault(asset_id, ShadowBook(asset_id))
            book.update(best_bid, best_ask, ts, fills_f, siblings=event_sibling_books(books, asset_id) or None)
    elif isinstance(raw, dict) and raw.get("event_type") == "price_change":
        for change in raw.get("price_changes", []):
            asset_id = change.get("asset_id")
            bb, ba = change.get("best_bid"), change.get("best_ask")
            if not asset_id or asset_id not in TOKEN_LABELS or bb is None or ba is None:
                continue
            book = books.setdefault(asset_id, ShadowBook(asset_id))
            book.update(float(bb), float(ba), ts, fills_f, siblings=event_sibling_books(books, asset_id) or None)
    elif isinstance(raw, dict) and raw.get("event_type") == "last_trade_price":
        # a real execution from ANY participant (not a book/price update) —
        # previously silently ignored entirely, see MARKET_VPIN_ENABLED.
        asset_id = raw.get("asset_id")
        side, size = raw.get("side"), raw.get("size")
        if not asset_id or asset_id not in TOKEN_LABELS or not side or size is None:
            return
        books.setdefault(asset_id, ShadowBook(asset_id)).record_market_trade(ts, side, float(size))


def check_resolutions(client: PublicClient, books: dict[str, ShadowBook], fills_f) -> None:
    """Poll REST for every tracked market not yet marked resolved. Cheap
    and infrequent (RESOLUTION_CHECK_INTERVAL_S) — this is a correctness
    check, not something that needs sub-second latency."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    for asset_id, market_id in MARKET_IDS.items():
        book = books.get(asset_id)
        if book is not None and book.resolved:
            continue
        try:
            market = client.get_market(id=str(market_id))
        except Exception as exc:
            print(f"[{ts}] resolution check failed for market {market_id}: {exc!r}", flush=True)
            continue
        closed = bool(market.state and market.state.closed)
        if not closed:
            continue
        yes_payout = float(market.outcomes.yes.price) if market.outcomes and market.outcomes.yes.price is not None else None
        if yes_payout is None:
            continue
        payout = yes_payout if TOKEN_SIDE.get(asset_id, "yes") == "yes" else 1.0 - yes_payout
        print(f"[{ts}] market {market_id} ({TOKEN_LABELS.get(asset_id, asset_id[:12])}) resolved, payout={payout}", flush=True)
        books.setdefault(asset_id, ShadowBook(asset_id)).force_close_at_resolution(payout, ts, fills_f)


def check_game_status(client: PublicClient, books: dict[str, ShadowBook], event_ids: dict[str, int]) -> None:
    """Poll REST for live game period per EVENT (not per market — a 3-way
    soccer market has 3 tokens sharing one event/game, no need to fetch
    it 3 times). This is the actual fix for the kickoff-timing problem:
    instead of trusting a guessed kickoff timestamp (see EVENT_IDS/
    GAME_STATUS_CHECK_INTERVAL_S comments — wrong by hours for esports and
    for WNBA), ask Polymarket's own sports metadata whether the game has
    started. Cheap and infrequent by design, same pattern as
    check_resolutions."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    period_by_event: dict[int, str | None] = {}
    for event_id in set(event_ids.values()):
        try:
            event = client.get_event(id=str(event_id))
        except Exception as exc:
            print(f"[{ts}] game-status check failed for event {event_id}: {exc!r}", flush=True)
            continue
        period_by_event[event_id] = event.sports.period if event.sports else None
    for asset_id, event_id in event_ids.items():
        if event_id in period_by_event:
            books.setdefault(asset_id, ShadowBook(asset_id)).update_game_period(period_by_event[event_id])


def reset_regenerable_log(path: Path, *, keep_backfilled: bool = False) -> None:
    """Truncate a durable log before the full-tape replay that always
    happens on every restart (main() rebuilds all in-memory state by
    reprocessing live_book.jsonl from byte 0 every time) — otherwise that
    replay re-appends every entry it already wrote in EVERY prior run,
    duplicating them. Confirmed live 2026-07-17: round_trips.jsonl had
    141 lines, only 49 actually unique; shadow_fills.jsonl had 335, only
    165 unique — restarting 2-3 times without clearing these multiplied
    every real entry that many times over, badly distorting a win-rate/
    loss-size analysis before this was caught.

    Entries marked `"backfilled": true` predate live_book.jsonl (from
    before the worldcup_semifinals.jsonl -> live_book.jsonl rename) and
    can't be regenerated by replaying it, so those are preserved —
    everything else gets rebuilt fresh and safely by the replay that's
    about to run, since that replay is fully deterministic given the
    same tape + code."""
    if not path.exists():
        return
    kept = []
    if keep_backfilled:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("backfilled"):
                    kept.append(line)
    with path.open("w") as f:
        for line in kept:
            f.write(line + "\n")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    books: dict[str, ShadowBook] = {}
    client = PublicClient()
    last_state_write = 0.0
    last_resolution_check = 0.0
    last_game_status_check = 0.0
    last_token_refresh = 0.0

    refresh_tracked_tokens()
    while not IN_PATH.exists():
        time.sleep(5)

    reset_regenerable_log(FILLS_PATH)
    reset_regenerable_log(ROUND_TRIPS_PATH, keep_backfilled=True)
    reset_regenerable_log(RESOLVED_GAMES_PATH, keep_backfilled=True)

    with IN_PATH.open("r") as in_f, FILLS_PATH.open("a") as fills_f:
        while True:
            line = in_f.readline()
            if not line:
                now = time.time()
                if now - last_state_write > 30:
                    STATE_PATH.write_text(json.dumps({
                        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "books": {b.label: b.snapshot() for b in books.values()},
                    }, indent=2))
                    last_state_write = now
                if now - last_resolution_check > RESOLUTION_CHECK_INTERVAL_S:
                    check_resolutions(client, books, fills_f)
                    last_resolution_check = now
                if now - last_game_status_check > GAME_STATUS_CHECK_INTERVAL_S:
                    check_game_status(client, books, EVENT_IDS)
                    last_game_status_check = now
                if now - last_token_refresh > TOKEN_REFRESH_INTERVAL_S:
                    refresh_tracked_tokens()
                    last_token_refresh = now
                time.sleep(1)
                continue
            try:
                msg = json.loads(line)
                process_message(msg["raw"], books, msg["recv_ts"], fills_f)
            except (json.JSONDecodeError, KeyError):
                continue


if __name__ == "__main__":
    main()
