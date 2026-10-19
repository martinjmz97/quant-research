"""Discover currently-active single-game moneyline markets across our
in-scope leagues and flatten them into the token-tracking config shared
by scripts/record_orderbook.py and scripts/shadow_quote_live.py.

Replaces hand-maintained per-token dicts (TOKEN_LABELS/KICKOFFS/
MARKET_IDS/EVENT_IDS in shadow_quote_live.py) — confirmed live
2026-07-17 that hand-picking one match at a time doesn't produce enough
games to calibrate the spread (see POLYMARKET_MM.md "necesitamos más
juegos"). Scope: soccer, NFL, MLB, NHL, NBA, WNBA — esports excluded
(see POLYMARKET_MM.md "Decisiones tomadas", 2026-07-17).

Two API facts this relies on, both verified live against real events
(not assumed — see POLYMARKET_MM.md "Game-status en vivo"):
  - `event.sports.game_id is not None` reliably distinguishes an actual
    single-game event from a season-long futures/props event (World
    Series Champion, MVP awards, etc., which have `game_id=None` and
    dozens of markets) — confirmed against real MLB events of both kinds.
  - `market.sports.game_start_time` is the real scheduled kickoff,
    independent of and more reliable than the event's `end_date` (which
    was wrong by up to a day) or even the event's own slug date (also
    seen wrong by weeks-to-months against a real MLB event).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from polymarket.clients.public import PublicClient
from polymarket.models.gamma.event import Event
from polymarket.models.gamma.market import Market

from ingestion.polymarket.discovery import iter_sports_events

LEAGUE_TAG_IDS = {
    "soccer": 100350,
    "nfl": 450,
    "mlb": 100381,
    "nhl": 899,
    "nba": 745,
    "wnba": 100254,
}

# how far into the future a game can still be to start tracking it now.
# How far in the past it can have started is bounded by typical game
# length across our leagues (soccer ~2h, NBA/NHL/WNBA ~2.5h, MLB/NFL up
# to ~3.5h with extra innings/overtime) plus a little slack for a game
# running long — NOT by how long resolution can lag afterward (that's a
# separate, correct reason to KEEP tracking a game once known, but not a
# reason to newly onboard one that's obviously already over). Found live
# 2026-07-17: an 8h lookback onboarded 4 Chinese Super League matches
# that had already finished 2-3h earlier — all 12 tokens showed
# `game_period="VFT"` (confirmed via check_game_status) and price already
# at the 0/1 extreme the instant they were first tracked, so they gave
# zero calibration value, immediately flattened. See the price check in
# is_in_scope_game below for the more direct fix — this window alone
# can't fully prevent that (resolution can lag well past typical game
# length either way), so both matter.
DEFAULT_MAX_LOOKAHEAD = dt.timedelta(hours=2)
DEFAULT_MAX_LOOKBACK = dt.timedelta(hours=4)

# only the win/lose moneyline market per game — not spreads/totals/nrfi
# props, which aren't the binary payoff this project's model is built
# around.
MONEYLINE_MARKET_TYPE = "moneyline"

# skip a market whose current price already shows the outcome is
# basically decided — same threshold as shadow_quote_live.py's
# RESOLUTION_PROXIMITY_STOP (kept as a separate constant: src/ has no
# import dependency on scripts/, the two layers don't share code today).
# This is the direct fix for the Chinese Super League case above — a
# time-window heuristic alone can't catch "game ended early" or
# "resolution is slow", checking the price we already have in hand can.
RESOLUTION_PROXIMITY = 0.03

# per-MARKET liquidity floor (order-book depth in USD, market.metrics.
# liquidity — already fetched during discovery, no extra API call).
# The server-side volume_min passed to iter_sports_events is applied at
# the EVENT level (Gamma API semantics) — an event bundling several
# markets (moneyline + draw for a 3-way soccer split) can pass that bar
# on aggregate while one of its markets is individually thin (found live
# 2026-07-17: a Romanian league draw market had only $223 in `volume`
# vs. $3.6k-$5.4k for its moneyline siblings in the same event — still
# comfortably liquid at $32.6k here, but this is the general gap this
# filter closes). Liquidity (resting depth), not volume (historical
# turnover), is what actually predicts whether the real market will ever
# cross a resting quote — a market can have modest volume and be fine,
# or real volume and a paper-thin book. Not calibrated against real
# fill-rate data yet — a placeholder floor, revisit once there's enough
# N to check whether markets below/above it actually fill differently.
MIN_MARKET_LIQUIDITY = 10_000


@dataclass(frozen=True)
class TrackedToken:
    asset_id: str
    label: str
    market_id: int
    event_id: int
    side: str  # "yes" or "no"
    game_start_time: dt.datetime | None


def _slug_label(team_name: str) -> str:
    """"New York Liberty" -> "new_york_liberty" — same _win-suffixed
    label style already used for the hand-picked tokens (mets_win,
    france_win, ...)."""
    return "_".join(team_name.lower().split())


def is_in_scope_game(
    event: Event,
    market: Market,
    now: dt.datetime,
    *,
    max_lookahead: dt.timedelta = DEFAULT_MAX_LOOKAHEAD,
    max_lookback: dt.timedelta = DEFAULT_MAX_LOOKBACK,
) -> bool:
    """True if `market` is a moneyline market for an actual single game
    (not a season-long futures/props event) whose scheduled start falls
    within [now - max_lookback, now + max_lookahead], whose current price
    doesn't already show the outcome as decided (see RESOLUTION_PROXIMITY
    above — a time window alone can't catch a game that ended early or a
    market that just hasn't repriced/resolved yet), and whose order-book
    depth clears MIN_MARKET_LIQUIDITY (a market within an otherwise
    high-volume event can still be individually thin)."""
    if event.sports is None or event.sports.game_id is None:
        return False
    if market.sports is None or market.sports.sports_market_type != MONEYLINE_MARKET_TYPE:
        return False
    start = market.sports.game_start_time
    if start is None:
        return False
    if not (now - max_lookback <= start <= now + max_lookahead):
        return False
    price = market.outcomes.yes.price
    if price is not None and not (RESOLUTION_PROXIMITY <= float(price) <= 1 - RESOLUTION_PROXIMITY):
        return False
    liquidity = market.metrics.liquidity if market.metrics else None
    if liquidity is not None and float(liquidity) < MIN_MARKET_LIQUIDITY:
        return False
    return True


_GENERIC_OUTCOME_LABELS = {"yes", "no"}


def tokens_from_market(market: Market, event_id: int) -> list[TrackedToken]:
    """Two market shapes exist, confirmed against real markets:
    (1) true 2-team moneyline (MLB/NBA/NHL/WNBA style) — outcomes.yes/no
        are labeled with the actual team names, both sides tracked.
    (2) "Will {team} win?" per-outcome splits (soccer 3-way: one binary
        market per outcome, e.g. france_win/england_win/draw) — outcomes
        are literally labeled "Yes"/"No", carrying no team info; the real
        team name is on `market.group_item_title`. "No" here doesn't mean
        "the other team" (could be a draw, or nothing at all for a
        genuine 2-outcome split modeled this way) — matches this
        project's existing hand-picked convention of tracking only the
        "yes" side for these (see TOKEN_LABELS: france_win, england_win,
        france_england_draw are each their own market's "yes" token, no
        complementary "no" side tracked for any of them).
    """
    start = market.sports.game_start_time if market.sports else None
    market_id = int(market.id)
    yes, no = market.outcomes.yes, market.outcomes.no

    if yes.label.lower() in _GENERIC_OUTCOME_LABELS or no.label.lower() in _GENERIC_OUTCOME_LABELS:
        if yes.token_id is None:
            return []
        team = market.group_item_title or market.question or f"market_{market_id}"
        return [TrackedToken(
            asset_id=yes.token_id,
            label=f"{_slug_label(team)}_win",
            market_id=market_id,
            event_id=event_id,
            side="yes",
            game_start_time=start,
        )]

    tokens = []
    for side, outcome in (("yes", yes), ("no", no)):
        if outcome.token_id is None:
            continue
        tokens.append(TrackedToken(
            asset_id=outcome.token_id,
            label=f"{_slug_label(outcome.label)}_win",
            market_id=market_id,
            event_id=event_id,
            side=side,
            game_start_time=start,
        ))
    return tokens


def _token_to_dict(token: TrackedToken) -> dict:
    return {
        "asset_id": token.asset_id,
        "label": token.label,
        "market_id": token.market_id,
        "event_id": token.event_id,
        "side": token.side,
        "game_start_time": token.game_start_time.isoformat() if token.game_start_time else None,
    }


def merge_tracked_tokens(existing: list[dict], discovered: list[TrackedToken]) -> list[dict]:
    """Union by asset_id, existing entries take priority over a
    re-discovery of the same token (keeps whatever was recorded first).

    Confirmed live 2026-07-17: scripts/discover_active_markets.py used to
    overwrite the tracked-markets file with just this run's snapshot —
    once every previously-tracked game aged out of the active-now window
    (correctly excluded, see the RESOLUTION_PROXIMITY fix above) the file
    went to 0 tokens, and shadow_quote_live.py rebuilds its TOKEN_LABELS/
    etc. from scratch on every restart — so a restart landing right then
    came up completely empty, even though dozens of tokens were
    legitimately known moments earlier. This union is what
    shadow_quote_live.py's own "additive only, never drop" dicts assumed
    was already happening one layer down.

    Not yet addressed: this makes the file (and therefore
    record_orderbook.py's websocket subscription) grow without bound —
    fine at today's scale (tens of tokens), a real problem once this has
    run for weeks. Deliberately not solved here — pruning needs to be
    careful not to reintroduce this exact bug (e.g. dropping a token
    that's resolved from record_orderbook's subscription is safe, but
    shadow_quote_live's metadata dicts must never lose one)."""
    by_asset_id = {t["asset_id"]: t for t in existing}
    for token in discovered:
        by_asset_id.setdefault(token.asset_id, _token_to_dict(token))
    return list(by_asset_id.values())


def discover_tracked_tokens(
    client: PublicClient,
    now: dt.datetime,
    *,
    leagues: dict[str, int] = LEAGUE_TAG_IDS,
    volume_min: float | None = 5_000,
    max_lookahead: dt.timedelta = DEFAULT_MAX_LOOKAHEAD,
    max_lookback: dt.timedelta = DEFAULT_MAX_LOOKBACK,
    page_delay: float = 0.5,
) -> list[TrackedToken]:
    """Scan every in-scope league for currently-active single-game
    moneyline markets and flatten them into TrackedToken entries. Live,
    hits the network — see discover_active_tokens() in
    scripts/discover_active_markets.py for the runnable entry point."""
    tokens: list[TrackedToken] = []
    seen_asset_ids: set[str] = set()
    for tag_id in leagues.values():
        for event in iter_sports_events(
            client, closed=False, additional_tag_id=tag_id, volume_min=volume_min, page_delay=page_delay,
        ):
            for market in event.markets:
                if not is_in_scope_game(event, market, now, max_lookahead=max_lookahead, max_lookback=max_lookback):
                    continue
                for token in tokens_from_market(market, int(event.id)):
                    if token.asset_id in seen_asset_ids:
                        continue
                    seen_asset_ids.add(token.asset_id)
                    tokens.append(token)
    return tokens
