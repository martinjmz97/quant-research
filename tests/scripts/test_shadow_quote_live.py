"""Regression tests for two bugs found analyzing the first live shadow
run (2026-07-16/17):

1. The requote-latency gap that let a fill's immediate recenter be
   crossed again within milliseconds — mets_win/phillies_win showed 3-4
   fills in under 1 second (gaps of ~180-490ms), position flipping
   +19.5->+9.7->-1.9 tokens, which no real MM (cancel/replace isn't
   instant) could actually do.
2. `_should_requote` treating `our_bid is None` as "always requote",
   which is also true while stop-quoting is active — every incoming tick
   re-evaluated (and re-extended) the toxic/stop state instead of
   respecting the normal drift/interval throttle. Confirmed live:
   mets_win accumulated 39,962 toxic-widening triggers / 39,960 stop
   escalations against only 18 real fills, at a feed rate of ~56 msg/s.

`scripts/` isn't a package, so it's added to sys.path directly rather
than imported through pythonpath (which only covers src/).
"""

import datetime as dt
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import shadow_quote_live as sql  # noqa: E402

_BASE = dt.datetime(2026, 7, 17, 12, 0, 0, tzinfo=dt.timezone.utc)


def _ts(seconds_offset: float) -> str:
    return (_BASE + dt.timedelta(seconds=seconds_offset)).isoformat()


class TestRequoteLatency:
    """MIN_REQUOTE_LATENCY_S: a quote isn't crossable until it has been
    "resting" for at least that long — modeling that canceling/replacing
    an order is a real round trip, not instant."""

    def test_fresh_quote_not_crossable_before_latency_elapses(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.49, 0.51, _ts(0), fills)  # fv=0.5 -> our_bid=0.49/our_ask=0.51
        book.update(0.30, 0.40, _ts(0.5), fills)  # crosses, but latency not elapsed
        assert book.n_fills == 0
        assert fills.getvalue() == ""

    def test_crossable_once_latency_elapses(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.49, 0.51, _ts(0), fills)
        book.update(0.30, 0.40, _ts(sql.MIN_REQUOTE_LATENCY_S + 0.01), fills)
        assert book.n_fills == 1

    def test_post_fill_recenter_blocks_immediate_second_fill(self):
        """Direct regression for the observed live pattern: a fill forces
        an immediate recenter; a second crossing tick arriving a few
        hundred ms later (matching the ~180-490ms gaps in
        shadow_fills.jsonl) must not fill again."""
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.49, 0.51, _ts(0), fills)
        book.update(0.30, 0.40, _ts(2.0), fills)
        assert book.n_fills == 1
        book.update(0.10, 0.20, _ts(2.3), fills)  # +0.3s, still crosses the recentered quote
        assert book.n_fills == 1

    def test_second_fill_allowed_once_latency_elapses_again(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.49, 0.51, _ts(0), fills)
        book.update(0.30, 0.40, _ts(2.0), fills)
        assert book.n_fills == 1
        book.update(0.10, 0.20, _ts(2.0 + sql.MIN_REQUOTE_LATENCY_S + 0.01), fills)
        assert book.n_fills == 2


class TestStoppedBookDoesNotReevaluateEveryTick:
    """`our_bid is None` used to force `_should_requote` to always return
    True, which is also the state while stop-quoting is active — so every
    single tick re-ran the toxic/stop escalation logic instead of
    respecting the normal drift/max-interval throttle."""

    def test_requote_not_reevaluated_on_every_tick_while_stopped(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        # fv=0.01 is inside RESOLUTION_PROXIMITY_STOP -> stops immediately
        book.update(0.005, 0.015, _ts(0), fills)
        assert book.our_bid is None and book.our_ask is None
        n_requotes_after_stop = book.n_requotes

        # many rapid ticks, same fv, all well within REQUOTE_MAX_INTERVAL_S
        for i in range(1, 51):
            book.update(0.005, 0.015, _ts(i * 0.1), fills)
        assert book.n_requotes == n_requotes_after_stop

    def test_requote_resumes_after_max_interval_even_while_stopped(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.005, 0.015, _ts(0), fills)
        n0 = book.n_requotes
        book.update(0.005, 0.015, _ts(sql.REQUOTE_MAX_INTERVAL_S + 1), fills)
        assert book.n_requotes == n0 + 1


class TestActiveFlattenNearResolution:
    """Stop-quoting alone only withdraws our own quote — it does nothing
    about inventory already open. Found live: t1_win sat short 10.497
    tokens marked at fv=0.999, hanwha_win sat long 32.186 marked at
    fv~0.001, both just waiting up to 5 minutes for the REST resolution
    poll with no way to act sooner. _flatten_at_market closes that
    exposure immediately via a taker cross, paying TAKER_FEE_RATE_SPORTS.

    Position/cash are seeded directly (bypassing update()) so each test
    isolates the flatten logic — driving a large position through update()
    with a live crossing book would also pick off the stale resting quote
    on the way to the extreme, adding an unrelated ordinary fill."""

    def test_long_position_flattened_via_taker_sell_near_zero(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.position = 10.0
        book.cash = -3.0
        book.last_requote_ts = None  # forces _should_requote to fire

        book.update(0.001, 0.002, _ts(0), fills)

        assert book.position == 0.0
        assert book.n_forced_flattens == 1
        assert book.n_fills == 1
        expected_fee = 10.0 * sql.TAKER_FEE_RATE_SPORTS * 0.001 * (1 - 0.001)
        expected_cash = -3.0 + 10.0 * 0.001 - expected_fee
        assert book.cash == pytest.approx(expected_cash)

    def test_short_position_flattened_via_taker_buy_near_one(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.position = -10.0
        book.cash = 3.0
        book.last_requote_ts = None

        book.update(0.998, 0.999, _ts(0), fills)

        assert book.position == 0.0
        assert book.n_forced_flattens == 1
        assert book.n_fills == 1
        expected_fee = 10.0 * sql.TAKER_FEE_RATE_SPORTS * 0.999 * (1 - 0.999)
        expected_cash = 3.0 - (10.0 * 0.999 + expected_fee)
        assert book.cash == pytest.approx(expected_cash)

    def test_no_flatten_when_already_flat(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.001, 0.002, _ts(0), fills)  # never quoted, no position
        assert book.n_forced_flattens == 0
        assert book.n_fills == 0

    def test_no_flatten_when_fv_not_near_resolution(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.position = 10.0
        book.cash = -3.0
        book.last_requote_ts = None

        book.update(0.49, 0.51, _ts(0), fills)  # fv=0.5, nowhere near an edge

        assert book.n_forced_flattens == 0
        assert book.position == 10.0


class TestResolutionStopHysteresis:
    """Regression for the exact pattern found live 2026-07-17: fv
    bouncing right at RESOLUTION_PROXIMITY_STOP (Rumania,
    fc_voluntari_win/fc_botoșani_win) made the old single-threshold check
    flap — stop, resume the instant fv ticked back above 0.03, get
    picked off seconds later, flatten again — 4 cycles in ~25min, each
    realizing a fresh loss near price~0/1. Fix reuses `stopped_until`
    (same field the toxic-flow escalation uses) so a touch of the
    near-resolution zone keeps quoting withdrawn for at least
    RESOLUTION_STOP_COOLDOWN_S after the LAST touch."""

    def test_does_not_resume_quoting_shortly_after_bouncing_back(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.005, 0.015, _ts(0), fills)  # fv=0.01, near-resolution -> stop
        assert book.our_bid is None
        n_stops_after_first_stop = book.n_stops

        # fv bounces back above the threshold shortly after (matches the
        # observed ~9s / ~2s gaps) — must NOT resume quoting yet
        book.update(0.49, 0.51, _ts(5), fills)
        assert book.our_bid is None
        assert book.n_stops == n_stops_after_first_stop  # still the same episode, not a new one

    def test_resumes_after_cooldown_elapses_from_last_touch(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.005, 0.015, _ts(0), fills)
        book.update(0.49, 0.51, _ts(sql.RESOLUTION_STOP_COOLDOWN_S + 1), fills)
        assert book.our_bid is not None

    def test_retouching_zone_extends_the_cooldown(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.005, 0.015, _ts(0), fills)  # first touch
        # a second touch shortly after should push the cooldown further
        # into the future, not leave it anchored to the first touch —
        # past REQUOTE_MAX_INTERVAL_S so _should_requote actually
        # re-evaluates this tick instead of throttling it out.
        book.update(0.005, 0.015, _ts(sql.REQUOTE_MAX_INTERVAL_S + 1), fills)
        # right after the ORIGINAL cooldown would have expired (from the
        # first touch alone), quoting should still be withheld because
        # the second touch renewed it
        book.update(0.49, 0.51, _ts(sql.RESOLUTION_STOP_COOLDOWN_S + 5), fills)
        assert book.our_bid is None

    def test_n_stops_counts_episodes_not_every_renewal(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.005, 0.015, _ts(0), fills)
        n0 = book.n_stops
        # many rapid re-touches within the same cooldown episode
        for i in range(1, 6):
            book.update(0.005, 0.015, _ts(i * 2), fills)
        assert book.n_stops == n0  # one episode, not one per touch

    def test_new_episode_after_a_full_recovery_counts_again(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.005, 0.015, _ts(0), fills)
        n0 = book.n_stops
        book.update(0.49, 0.51, _ts(sql.RESOLUTION_STOP_COOLDOWN_S + 1), fills)  # fully recovers
        book.update(0.005, 0.015, _ts(sql.RESOLUTION_STOP_COOLDOWN_S + 2), fills)  # touches again
        assert book.n_stops == n0 + 1


class TestProcessMessageScopeFilter:
    """process_message used to create a ShadowBook for ANY asset_id seen
    in the feed, regardless of TOKEN_LABELS. Confirmed live (2026-07-17):
    excluding esports meant removing its tokens from TOKEN_LABELS/
    KICKOFFS/MARKET_IDS, but that alone didn't stop tracking them — the
    restarted process kept quoting them under their raw (truncated)
    asset_id, just without a friendly label. Now gated on
    `asset_id in TOKEN_LABELS`."""

    UNTRACKED = "not-a-tracked-token"
    KNOWN = "a-tracked-token"

    def setup_method(self):
        sql.TOKEN_LABELS[self.KNOWN] = "known_win"

    def teardown_method(self):
        sql.TOKEN_LABELS.pop(self.KNOWN, None)

    def test_list_format_skips_untracked_asset_id(self):
        books = {}
        fills = io.StringIO()
        raw = [{"asset_id": self.UNTRACKED, "bids": [{"price": "0.49"}], "asks": [{"price": "0.51"}]}]
        sql.process_message(raw, books, _ts(0), fills)
        assert self.UNTRACKED not in books

    def test_list_format_tracks_known_asset_id(self):
        books = {}
        fills = io.StringIO()
        raw = [{"asset_id": self.KNOWN, "bids": [{"price": "0.49"}], "asks": [{"price": "0.51"}]}]
        sql.process_message(raw, books, _ts(0), fills)
        assert self.KNOWN in books

    def test_price_change_format_skips_untracked_asset_id(self):
        books = {}
        fills = io.StringIO()
        raw = {
            "event_type": "price_change",
            "price_changes": [{"asset_id": self.UNTRACKED, "best_bid": 0.49, "best_ask": 0.51}],
        }
        sql.process_message(raw, books, _ts(0), fills)
        assert self.UNTRACKED not in books

    def test_price_change_format_tracks_known_asset_id(self):
        books = {}
        fills = io.StringIO()
        known = self.KNOWN
        raw = {
            "event_type": "price_change",
            "price_changes": [{"asset_id": known, "best_bid": 0.49, "best_ask": 0.51}],
        }
        sql.process_message(raw, books, _ts(0), fills)
        assert known in books


class TestLiveGameStatus:
    """Replaces trusting a guessed kickoff timestamp with the live
    `event.sports.period` field. Found live (2026-07-17): liberty_win/
    wings_win kept trading at 0.45-0.55 for 12+ hours after their assumed
    (unverified) WNBA kickoff — the real game had already finished
    (`period == "POST"`, confirmed via client.get_event) while the book
    never repriced near 0/1, so price-based `_near_resolution` alone never
    caught it. `period is None` reliably means "not started" — verified
    against 4 real events (2 not-started soccer matches -> None, finished
    WNBA -> "POST", finished MLB -> "VFT")."""

    def test_game_confirmed_over_for_known_terminal_periods(self):
        book = sql.ShadowBook("tok")
        for period in sql.GAME_OVER_PERIODS:
            book.game_period = period
            assert book._game_confirmed_over()

    def test_not_confirmed_over_for_not_started_or_in_progress(self):
        book = sql.ShadowBook("tok")
        for period in [None, "2nd", "Q3", "HT"]:
            book.game_period = period
            assert not book._game_confirmed_over()

    def test_flattens_on_terminal_period_even_when_price_far_from_resolution(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.position = 10.0
        book.cash = -3.0
        book.last_requote_ts = None
        book.game_period = "POST"

        book.update(0.45, 0.55, _ts(0), fills)  # fv=0.5, nowhere near an edge

        assert book.position == 0.0
        assert book.n_forced_flattens == 1

    def test_no_flatten_on_terminal_period_if_spread_is_placeholder(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.position = 10.0
        book.cash = -3.0
        book.last_requote_ts = None
        book.game_period = "POST"

        book.update(0.0, 1.0, _ts(0), fills)  # placeholder spread, not a tradeable price

        assert book.n_forced_flattens == 0
        assert book.position == 10.0

    def test_widening_applies_when_game_period_set_even_outside_static_window(self):
        book = sql.ShadowBook("tok")  # "tok" isn't in KICKOFFS -> _in_match_window always False
        fills = io.StringIO()
        book.game_period = "2nd"  # any non-None value means the game has started

        book.update(0.49, 0.51, _ts(0), fills)

        expected_spread = 2 * sql.HALF_SPREAD * sql.MATCH_CLOCK_WIDEN_FACTOR
        assert book.our_ask - book.our_bid == pytest.approx(expected_spread)

    def test_no_widening_when_game_period_none_and_outside_static_window(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()

        book.update(0.49, 0.51, _ts(0), fills)

        assert book.our_ask - book.our_bid == pytest.approx(2 * sql.HALF_SPREAD)


class TestCheckGameStatus:
    class _StubClient:
        def __init__(self, period_by_event_id):
            self.period_by_event_id = period_by_event_id
            self.calls = []

        def get_event(self, *, id):
            self.calls.append(id)
            event_id = int(id)
            if event_id not in self.period_by_event_id:
                raise RuntimeError(f"unknown event {event_id}")
            period = self.period_by_event_id[event_id]
            sports = type("Sports", (), {"period": period})()
            return type("Event", (), {"sports": sports})()

    def test_updates_game_period_for_all_tokens_sharing_an_event(self):
        books = {}
        client = self._StubClient({100: "POST"})
        sql.check_game_status(client, books, {"tokA": 100, "tokB": 100})
        assert books["tokA"].game_period == "POST"
        assert books["tokB"].game_period == "POST"

    def test_fetches_each_unique_event_only_once(self):
        books = {}
        client = self._StubClient({100: "POST", 200: None})
        sql.check_game_status(client, books, {"tokA": 100, "tokB": 100, "tokC": 200})
        assert sorted(client.calls) == ["100", "200"]

    def test_skips_gracefully_on_fetch_error(self):
        books = {}
        client = self._StubClient({})  # every event_id raises
        sql.check_game_status(client, books, {"tokA": 999})  # must not raise
        assert "tokA" not in books


class TestRefreshTrackedTokens:
    """KICKOFFS/TOKEN_LABELS/TOKEN_SIDE/MARKET_IDS/EVENT_IDS used to be
    hand-maintained dicts, one match hardcoded at a time — replaced
    2026-07-17 with a load from TRACKED_MARKETS_PATH (written by
    scripts/discover_active_markets.py), refreshed periodically. Additive
    only: a token already known must never be dropped just because a
    later discovery run doesn't list it (it may have aged out of the
    active-now window while still holding an open position — same bug
    class as the process_message scope filter above)."""

    TOK_A = "refresh-test-token-a"
    TOK_B = "refresh-test-token-b"

    def teardown_method(self):
        for d in (sql.TOKEN_LABELS, sql.TOKEN_SIDE, sql.MARKET_IDS, sql.EVENT_IDS, sql.KICKOFFS):
            d.pop(self.TOK_A, None)
            d.pop(self.TOK_B, None)

    def _write_config(self, tmp_path, tokens):
        path = tmp_path / "tracked_markets.json"
        path.write_text(json.dumps({"generated_at": _ts(0), "tokens": tokens}))
        return path

    def test_loads_all_fields_for_a_new_token(self, tmp_path, monkeypatch):
        config = self._write_config(tmp_path, [{
            "asset_id": self.TOK_A, "label": "team_a_win", "market_id": 111,
            "event_id": 222, "side": "yes", "game_start_time": "2026-07-18T21:00:00+00:00",
        }])
        monkeypatch.setattr(sql, "TRACKED_MARKETS_PATH", config)

        sql.refresh_tracked_tokens()

        assert sql.TOKEN_LABELS[self.TOK_A] == "team_a_win"
        assert sql.TOKEN_SIDE[self.TOK_A] == "yes"
        assert sql.MARKET_IDS[self.TOK_A] == 111
        assert sql.EVENT_IDS[self.TOK_A] == 222
        assert sql.KICKOFFS[self.TOK_A] == dt.datetime(2026, 7, 18, 21, 0, tzinfo=dt.timezone.utc)

    def test_token_with_no_game_start_time_gets_no_kickoff_entry(self, tmp_path, monkeypatch):
        config = self._write_config(tmp_path, [{
            "asset_id": self.TOK_A, "label": "team_a_win", "market_id": 111,
            "event_id": 222, "side": "yes", "game_start_time": None,
        }])
        monkeypatch.setattr(sql, "TRACKED_MARKETS_PATH", config)

        sql.refresh_tracked_tokens()

        assert self.TOK_A not in sql.KICKOFFS

    def test_a_token_missing_from_a_later_refresh_is_not_dropped(self, tmp_path, monkeypatch):
        config = self._write_config(tmp_path, [{
            "asset_id": self.TOK_A, "label": "team_a_win", "market_id": 111,
            "event_id": 222, "side": "yes", "game_start_time": None,
        }])
        monkeypatch.setattr(sql, "TRACKED_MARKETS_PATH", config)
        sql.refresh_tracked_tokens()

        # a later discovery run no longer lists TOK_A (aged out of the
        # active-now window) but lists a new TOK_B instead
        config.write_text(json.dumps({"generated_at": _ts(1), "tokens": [{
            "asset_id": self.TOK_B, "label": "team_b_win", "market_id": 333,
            "event_id": 444, "side": "no", "game_start_time": None,
        }]}))
        sql.refresh_tracked_tokens()

        assert self.TOK_A in sql.TOKEN_LABELS  # still known, not dropped
        assert self.TOK_B in sql.TOKEN_LABELS  # newly added

    def test_no_op_when_config_file_does_not_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sql, "TRACKED_MARKETS_PATH", tmp_path / "does-not-exist.json")
        sql.refresh_tracked_tokens()  # must not raise


class TestResolvedGamesLog:
    """A finished game's summary shouldn't depend on the tick-tape
    file's name or on the process never restarting — confirmed live
    2026-07-17: renaming worldcup_semifinals.jsonl -> live_book.jsonl
    (see POLYMARKET_MM.md "Descubrimiento automático") silently dropped
    mets_win/phillies_win/liberty_win/wings_win from the live
    shadow_state.json, since that state is fully reconstructed by
    replaying the tape from the top on every restart."""

    def test_writes_a_summary_line_on_resolution(self, tmp_path, monkeypatch):
        log_path = tmp_path / "resolved_games.jsonl"
        monkeypatch.setattr(sql, "RESOLVED_GAMES_PATH", log_path)
        book = sql.ShadowBook("tok")
        book.position = 10.0
        book.n_fills = 3
        fills = io.StringIO()

        book.force_close_at_resolution(1.0, _ts(0), fills)

        lines = log_path.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["label"] == "tok"
        assert record["payout"] == 1.0
        assert record["final_cash"] == 10.0
        assert record["n_fills"] == 4  # 3 existing + the forced-close fill

    def test_writes_a_summary_line_even_if_already_flat(self, tmp_path, monkeypatch):
        log_path = tmp_path / "resolved_games.jsonl"
        monkeypatch.setattr(sql, "RESOLVED_GAMES_PATH", log_path)
        book = sql.ShadowBook("tok")  # position already 0
        fills = io.StringIO()

        book.force_close_at_resolution(0.0, _ts(0), fills)

        assert len(log_path.read_text().splitlines()) == 1

    def test_no_second_line_on_repeated_resolution_call(self, tmp_path, monkeypatch):
        log_path = tmp_path / "resolved_games.jsonl"
        monkeypatch.setattr(sql, "RESOLVED_GAMES_PATH", log_path)
        book = sql.ShadowBook("tok")
        book.position = 5.0
        fills = io.StringIO()

        book.force_close_at_resolution(1.0, _ts(0), fills)
        book.force_close_at_resolution(1.0, _ts(1), fills)  # already resolved, no-op

        assert len(log_path.read_text().splitlines()) == 1


class TestRoundTripTracking:
    """Round-trip PnL used to only be reconstructable by hand from
    archived fills after the fact — tracked live now, and logged
    durably to ROUND_TRIPS_PATH as it happens, so "how's the system
    doing" doesn't require re-deriving it every time."""

    def test_no_round_trip_while_position_only_grows(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.update(0.49, 0.51, _ts(0), fills)
        book.update(0.30, 0.40, _ts(sql.MIN_REQUOTE_LATENCY_S + 0.01), fills)  # opens long
        assert book.position > 0
        assert book.n_round_trips == 0
        assert sql.ROUND_TRIPS_PATH.exists() is False or sql.ROUND_TRIPS_PATH.read_text() == ""

    def test_round_trip_closes_on_ordinary_fill_crossing_zero(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.position = 10.0
        book.cash = -3.0
        book.round_trip_epoch_cash = -3.0
        # our_ask=0.25 -> fill_tokens=MAX_FILL_USD/0.25=20, comfortably
        # more than the existing 10-token long, so the single SELL fill
        # flips all the way through zero to short.
        book.our_bid, book.our_ask = 0.20, 0.25
        book.quote_active_at = _BASE - dt.timedelta(seconds=1)
        book.last_requote_ts = _BASE - dt.timedelta(seconds=1)
        book.last_requote_fv = 0.225

        book.update(0.90, 0.95, _ts(0), fills)  # best_bid(0.90) >= our_ask(0.25) -> SELL

        assert book.position < 0  # flipped short, crossed through zero
        assert book.n_round_trips == 1
        assert len(book.round_trip_pnls) == 1
        lines = sql.ROUND_TRIPS_PATH.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["label"] == "tok"
        assert record["close_reason"] == "organic"

    def test_round_trip_closes_on_active_flatten(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.position = 10.0
        book.cash = -3.0
        book.round_trip_epoch_cash = -3.0
        book.last_requote_ts = None

        book.update(0.001, 0.002, _ts(0), fills)  # near-resolution -> flatten

        assert book.position == 0.0
        assert book.n_round_trips == 1
        record = json.loads(sql.ROUND_TRIPS_PATH.read_text().splitlines()[0])
        assert record["close_reason"] == "forced_flatten"

    def test_round_trip_closes_on_resolution_force_close(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.position = 10.0
        book.cash = -3.0
        book.round_trip_epoch_cash = -3.0

        book.force_close_at_resolution(1.0, _ts(0), fills)

        assert book.n_round_trips == 1
        assert book.round_trip_pnls[0] == pytest.approx(book.cash - (-3.0))
        record = json.loads(sql.ROUND_TRIPS_PATH.read_text().splitlines()[0])
        assert record["close_reason"] == "resolution_forced_close"

    def test_no_round_trip_when_already_flat_at_resolution(self):
        book = sql.ShadowBook("tok")
        fills = io.StringIO()
        book.force_close_at_resolution(0.0, _ts(0), fills)
        assert book.n_round_trips == 0


class TestHalfSpreadOverride:
    """SHADOW_HALF_SPREAD env var lets spread_sweep_backtest.py replay the
    same tape under different spreads in separate subprocesses — a silent
    failure here (env var read but not actually wired through) would make
    every sweep value produce identical results without anything erroring."""

    def test_env_var_overrides_half_spread_and_derived_constants(self):
        import subprocess
        import sys

        env = {**os.environ, "SHADOW_HALF_SPREAD": "0.05"}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "scripts")
        out = subprocess.run(
            [sys.executable, "-c", "import shadow_quote_live as sql; print(sql.HALF_SPREAD, sql.SKEW_MAX_SHIFT, sql.REQUOTE_DRIFT_THRESHOLD)"],
            env=env, capture_output=True, text=True, check=True,
        ).stdout.split()
        assert float(out[0]) == pytest.approx(0.05)
        assert float(out[1]) == pytest.approx(0.15)  # SKEW_MAX_SHIFT = HALF_SPREAD * 3
        assert float(out[2]) == pytest.approx(0.025)  # REQUOTE_DRIFT_THRESHOLD = HALF_SPREAD * 0.5

    def test_default_unchanged_without_env_var(self):
        import subprocess
        import sys

        env = {k: v for k, v in os.environ.items() if k != "SHADOW_HALF_SPREAD"}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "scripts")
        out = subprocess.run(
            [sys.executable, "-c", "import shadow_quote_live as sql; print(sql.HALF_SPREAD)"],
            env=env, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert float(out) == pytest.approx(0.01)


class TestEventWorstCase:
    """Pure function: combined payout if the event resolves adversely
    right now — exactly one leg pays its position, every other pays 0."""

    def test_worst_case_is_cash_plus_min_position(self):
        assert sql.event_worst_case(10.0, [5.0, -8.0, 3.0]) == pytest.approx(2.0)

    def test_all_positive_positions_still_uses_the_smallest(self):
        assert sql.event_worst_case(0.0, [5.0, 2.0, 9.0]) == pytest.approx(2.0)


class TestEventSiblingBooks:
    def test_empty_when_asset_has_no_known_event(self):
        books = {"tok-a": sql.ShadowBook("tok-a")}
        assert sql.event_sibling_books(books, "tok-a") == []

    def test_finds_other_legs_of_the_same_event(self, monkeypatch):
        monkeypatch.setitem(sql.EVENT_IDS, "tok-a", 999)
        monkeypatch.setitem(sql.EVENT_IDS, "tok-b", 999)
        monkeypatch.setitem(sql.EVENT_IDS, "tok-c", 111)  # different event
        book_a, book_b, book_c = sql.ShadowBook("tok-a"), sql.ShadowBook("tok-b"), sql.ShadowBook("tok-c")
        books = {"tok-a": book_a, "tok-b": book_b, "tok-c": book_c}

        siblings = sql.event_sibling_books(books, "tok-a")

        assert siblings == [book_b]

    def test_does_not_include_self(self, monkeypatch):
        monkeypatch.setitem(sql.EVENT_IDS, "tok-a", 999)
        book_a = sql.ShadowBook("tok-a")
        books = {"tok-a": book_a}
        assert sql.event_sibling_books(books, "tok-a") == []


class TestEventLevelRiskCap:
    """Regression for the exact pattern found live 2026-07-17: WNBA
    (liberty_win short + wings_win long — yes/no of ONE market) and
    Rumania (3 legs of one 3-way split) each lost real money because
    every leg manages its own $20 budget with zero awareness the other
    leg(s) are the SAME event — a leg short "yes" and a leg long "no" of
    the same market are the same directional bet twice, not a hedge."""

    def _seed_quoting_book(self, book, *, position, cash, our_bid=0.4, our_ask=0.5):
        book.position = position
        book.cash = cash
        book.best_bid, book.best_ask = 0.49, 0.51
        book.our_bid, book.our_ask = our_bid, our_ask
        book.quote_active_at = _BASE - dt.timedelta(seconds=1)
        book.last_requote_ts = _BASE - dt.timedelta(seconds=1)
        book.last_requote_fv = 0.5

    def test_blocks_fill_the_individual_cap_alone_would_allow(self):
        self_book = sql.ShadowBook("tok_self")
        sibling = sql.ShadowBook("tok_sibling")
        self._seed_quoting_book(self_book, position=-16.0, cash=0.0)
        sibling.position, sibling.cash = 10.0, 0.0
        fills = io.StringIO()

        # best_bid(0.6) >= our_ask(0.5) -> attempted SELL, growing the short
        self_book.update(0.6, 0.7, _ts(0), fills, siblings=[sibling])

        assert self_book.position == -16.0  # unchanged — blocked
        assert self_book.n_fills == 0
        assert self_book.n_blocked_by_inventory_cap == 1

    def test_allows_the_same_fill_without_sibling_context(self):
        # same starting position/fill as above, but with siblings=None
        # (unknown event context) — must behave exactly as before this
        # feature existed, since MAX_EVENT_LOSS_USD alone (without a
        # sibling) wouldn't have blocked this under the old per-token cap.
        self_book = sql.ShadowBook("tok_self")
        self._seed_quoting_book(self_book, position=-16.0, cash=0.0)
        fills = io.StringIO()

        self_book.update(0.6, 0.7, _ts(0), fills, siblings=None)

        assert self_book.position == -26.0  # filled normally
        assert self_book.n_fills == 1

    def test_allows_a_fill_that_genuinely_hedges_the_sibling(self):
        # sibling already short (bad if it resolves) -> self buying
        # (reducing its own short / building long) improves the event's
        # combined worst case rather than worsening it.
        self_book = sql.ShadowBook("tok_self")
        sibling = sql.ShadowBook("tok_sibling")
        self._seed_quoting_book(self_book, position=-2.0, cash=0.0, our_bid=0.5, our_ask=0.6)
        sibling.position, sibling.cash = -3.0, 0.0
        fills = io.StringIO()

        # best_ask(0.3) <= our_bid(0.5) -> attempted BUY, reducing the short
        self_book.update(0.2, 0.3, _ts(0), fills, siblings=[sibling])

        assert self_book.n_fills == 1
        assert self_book.n_blocked_by_inventory_cap == 0


class TestResetRegenerableLog:
    """Regression for the exact bug found live 2026-07-17: main() always
    replays live_book.jsonl from byte 0 on every restart, so a durable
    log opened in append mode re-writes every entry from every prior
    run — round_trips.jsonl had 141 lines with only 49 actually unique.
    reset_regenerable_log() truncates before that replay so it can
    safely regenerate everything from scratch, keeping only
    "backfilled" entries (which predate the tape and can't be
    regenerated by replaying it)."""

    def test_no_op_when_file_does_not_exist(self, tmp_path):
        path = tmp_path / "does-not-exist.jsonl"
        sql.reset_regenerable_log(path)  # must not raise
        assert not path.exists()

    def test_truncates_everything_by_default(self, tmp_path):
        path = tmp_path / "log.jsonl"
        path.write_text('{"pnl": 1}\n{"pnl": 2, "backfilled": true}\n')

        sql.reset_regenerable_log(path)

        assert path.read_text() == ""

    def test_keeps_only_backfilled_entries_when_requested(self, tmp_path):
        path = tmp_path / "log.jsonl"
        path.write_text(
            '{"pnl": 1}\n'
            '{"pnl": 2, "backfilled": true}\n'
            '{"pnl": 3}\n'
            '{"pnl": 4, "backfilled": true}\n'
        )

        sql.reset_regenerable_log(path, keep_backfilled=True)

        lines = [json.loads(l) for l in path.read_text().splitlines()]
        assert [r["pnl"] for r in lines] == [2, 4]

    def test_skips_malformed_lines_without_raising(self, tmp_path):
        path = tmp_path / "log.jsonl"
        path.write_text('not valid json\n{"pnl": 1, "backfilled": true}\n')

        sql.reset_regenerable_log(path, keep_backfilled=True)

        lines = [json.loads(l) for l in path.read_text().splitlines()]
        assert len(lines) == 1


class TestMarketWideTradeRecording:
    """record_market_trade tracks arrival times of REAL trades (any
    participant, from last_trade_price feed events) separately from
    fill_times (only OUR fills) — see MARKET_VPIN_ENABLED docstring for
    why this feeds a second, independent toxic-flow signal."""

    def test_appends_and_prunes_beyond_long_window(self):
        book = sql.ShadowBook("tok")
        book.record_market_trade(_ts(0), "BUY", 1.0)
        book.record_market_trade(_ts(sql.TOXIC_LONG_WINDOW_S + 1), "BUY", 1.0)
        # the first trade is now older than TOXIC_LONG_WINDOW_S relative
        # to the second — pruned on the second call.
        assert len(book.market_trade_times) == 1

    def test_process_message_routes_last_trade_price_without_touching_position(self):
        books = {}
        sql.TOKEN_LABELS["tok"] = "tok_label"
        try:
            raw = {"event_type": "last_trade_price", "asset_id": "tok", "side": "BUY", "size": "10", "price": "0.5"}
            sql.process_message(raw, books, _ts(0), io.StringIO())
            assert len(books["tok"].market_trade_times) == 1
            assert books["tok"].position == 0.0
            assert books["tok"].n_fills == 0
        finally:
            del sql.TOKEN_LABELS["tok"]

    def test_process_message_ignores_untracked_asset(self):
        books = {}
        raw = {"event_type": "last_trade_price", "asset_id": "not-tracked", "side": "BUY", "size": "10"}
        sql.process_message(raw, books, _ts(0), io.StringIO())
        assert books == {}


class TestMarketWideToxicFlow:
    """MARKET_VPIN_ENABLED gates a second, independent toxic-flow trigger
    fed by real market-wide trades instead of our own fills — default off
    (see module docstring for the calibration that led to a rate-anomaly
    signal instead of a directional-imbalance one)."""

    def test_disabled_by_default_market_trades_dont_trigger(self, monkeypatch):
        monkeypatch.setattr(sql, "MARKET_VPIN_ENABLED", False)
        book = sql.ShadowBook("tok")
        now = _BASE
        for i in range(20):
            book.record_market_trade((now + dt.timedelta(seconds=i * 0.1)).isoformat(), "BUY", 1.0)
        assert book._check_toxic_flow(now + dt.timedelta(seconds=2)) is False

    def test_enabled_triggers_on_market_wide_rate_anomaly_alone(self, monkeypatch):
        monkeypatch.setattr(sql, "MARKET_VPIN_ENABLED", True)
        monkeypatch.setattr(sql, "MARKET_VPIN_RATE_THRESHOLD", 3.0)
        book = sql.ShadowBook("tok")
        now = _BASE
        # 5 trades spread over the long window to clear the long_count>=5
        # floor, then a burst of many trades in the last few seconds —
        # no fills of OUR OWN at all, self_fill_toxic stays False.
        for i in range(5):
            book.record_market_trade((now - dt.timedelta(seconds=i * 300)).isoformat(), "BUY", 1.0)
        for i in range(10):
            book.record_market_trade((now + dt.timedelta(seconds=i * 0.1)).isoformat(), "BUY", 1.0)
        result = book._check_toxic_flow(now + dt.timedelta(seconds=1))
        assert result is True
        assert book.n_toxic_widenings == 1

    def test_enabled_but_below_threshold_does_not_trigger(self, monkeypatch):
        monkeypatch.setattr(sql, "MARKET_VPIN_ENABLED", True)
        monkeypatch.setattr(sql, "MARKET_VPIN_RATE_THRESHOLD", 1000.0)
        book = sql.ShadowBook("tok")
        now = _BASE
        for i in range(10):
            book.record_market_trade((now - dt.timedelta(seconds=i * 60)).isoformat(), "BUY", 1.0)
        assert book._check_toxic_flow(now) is False


class TestMarketFlowSkew:
    """market_flow_skew: signed order-flow imbalance over the last
    MARKET_FLOW_SKEW_WINDOW_TRADES real trades — leans the reservation
    into the persistent bias instead of trying to detect/avoid it."""

    def test_returns_zero_below_min_trades(self):
        book = sql.ShadowBook("tok")
        for i in range(sql.MARKET_FLOW_SKEW_MIN_TRADES - 1):
            book.record_market_trade(_ts(i), "BUY", 1.0)
        assert book.market_flow_skew() == 0.0

    def test_all_buy_gives_positive_one(self):
        book = sql.ShadowBook("tok")
        for i in range(sql.MARKET_FLOW_SKEW_MIN_TRADES):
            book.record_market_trade(_ts(i), "BUY", 1.0)
        assert book.market_flow_skew() == pytest.approx(1.0)

    def test_all_sell_gives_negative_one(self):
        book = sql.ShadowBook("tok")
        for i in range(sql.MARKET_FLOW_SKEW_MIN_TRADES):
            book.record_market_trade(_ts(i), "SELL", 1.0)
        assert book.market_flow_skew() == pytest.approx(-1.0)

    def test_mixed_gives_proportional_ratio(self):
        book = sql.ShadowBook("tok")
        for i in range(15):
            book.record_market_trade(_ts(i), "BUY", 1.0)
        for i in range(5):
            book.record_market_trade(_ts(15 + i), "SELL", 1.0)
        # window defaults to 20: 15 BUY + 5 SELL -> (15-5)/20 = 0.5
        assert book.market_flow_skew() == pytest.approx(0.5)

    def test_window_evicts_older_trades(self):
        book = sql.ShadowBook("tok")
        for i in range(sql.MARKET_FLOW_SKEW_WINDOW_TRADES):
            book.record_market_trade(_ts(i), "SELL", 1.0)
        assert book.market_flow_skew() == pytest.approx(-1.0)
        for i in range(sql.MARKET_FLOW_SKEW_WINDOW_TRADES):
            book.record_market_trade(_ts(100 + i), "BUY", 1.0)
        assert book.market_flow_skew() == pytest.approx(1.0)  # old SELLs fully evicted


class TestMarketFlowSkewInReservation:
    """MARKET_FLOW_SKEW_ENABLED gates whether market_flow_skew() shifts
    the reservation price — default off, unchanged production behavior."""

    def test_disabled_by_default_no_effect_on_reservation(self, monkeypatch):
        monkeypatch.setattr(sql, "MARKET_FLOW_SKEW_ENABLED", False)
        book = sql.ShadowBook("tok")
        for i in range(sql.MARKET_FLOW_SKEW_MIN_TRADES):
            book.record_market_trade(_ts(i), "BUY", 1.0)
        book.update(0.49, 0.51, _ts(100), io.StringIO())
        fv = 0.50
        assert book.our_bid == pytest.approx(fv - sql.HALF_SPREAD)
        assert book.our_ask == pytest.approx(fv + sql.HALF_SPREAD)

    def test_enabled_shifts_reservation_up_on_buy_heavy_flow(self, monkeypatch):
        monkeypatch.setattr(sql, "MARKET_FLOW_SKEW_ENABLED", True)
        book = sql.ShadowBook("tok")
        for i in range(sql.MARKET_FLOW_SKEW_MIN_TRADES):
            book.record_market_trade(_ts(i), "BUY", 1.0)
        book.update(0.49, 0.51, _ts(100), io.StringIO())
        fv = 0.50
        expected_reservation = fv + 1.0 * sql.FLOW_SKEW_MAX_SHIFT
        assert book.our_bid == pytest.approx(expected_reservation - sql.HALF_SPREAD)
        assert book.our_ask == pytest.approx(expected_reservation + sql.HALF_SPREAD)

    def test_enabled_shifts_reservation_down_on_sell_heavy_flow(self, monkeypatch):
        monkeypatch.setattr(sql, "MARKET_FLOW_SKEW_ENABLED", True)
        book = sql.ShadowBook("tok")
        for i in range(sql.MARKET_FLOW_SKEW_MIN_TRADES):
            book.record_market_trade(_ts(i), "SELL", 1.0)
        book.update(0.49, 0.51, _ts(100), io.StringIO())
        fv = 0.50
        expected_reservation = fv - 1.0 * sql.FLOW_SKEW_MAX_SHIFT
        assert book.our_bid == pytest.approx(expected_reservation - sql.HALF_SPREAD)
        assert book.our_ask == pytest.approx(expected_reservation + sql.HALF_SPREAD)
