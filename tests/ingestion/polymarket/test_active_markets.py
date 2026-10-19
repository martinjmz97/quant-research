import datetime as dt

from ingestion.polymarket.active_markets import (
    LEAGUE_TAG_IDS,
    TrackedToken,
    discover_tracked_tokens,
    is_in_scope_game,
    merge_tracked_tokens,
    tokens_from_market,
)

NOW = dt.datetime(2026, 7, 17, 12, 0, tzinfo=dt.timezone.utc)


class TestIsInScopeGame:
    def test_excludes_season_long_futures_event(self, make_event, make_market):
        # confirmed live: a futures/props event (World Series Champion,
        # MVP awards, ...) has event.sports.game_id == None, unlike a real
        # single-game event.
        event = make_event(game_id=None)
        market = make_market(sports_market_type="moneyline", game_start_time=NOW)
        assert not is_in_scope_game(event, market, NOW)

    def test_excludes_non_moneyline_market_type(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="spreads", game_start_time=NOW)
        assert not is_in_scope_game(event, market, NOW)

    def test_excludes_market_with_no_game_start_time(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="moneyline", game_start_time=None)
        assert not is_in_scope_game(event, market, NOW)

    def test_includes_game_starting_soon(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="moneyline", game_start_time=NOW + dt.timedelta(hours=1))
        assert is_in_scope_game(event, market, NOW)

    def test_includes_game_already_in_progress(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="moneyline", game_start_time=NOW - dt.timedelta(hours=3))
        assert is_in_scope_game(event, market, NOW)

    def test_excludes_game_too_far_in_the_future(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="moneyline", game_start_time=NOW + dt.timedelta(hours=5))
        assert not is_in_scope_game(event, market, NOW)

    def test_excludes_game_too_far_in_the_past(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="moneyline", game_start_time=NOW - dt.timedelta(hours=20))
        assert not is_in_scope_game(event, market, NOW)

    def test_window_bounds_are_overridable(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="moneyline", game_start_time=NOW - dt.timedelta(hours=20))
        assert is_in_scope_game(event, market, NOW, max_lookback=dt.timedelta(hours=24))

    def test_excludes_market_already_decided_near_zero(self, make_event, make_market):
        # regression: an 8h lookback once onboarded 4 already-finished
        # Chinese Super League matches whose price was already at the
        # 0/1 extreme — the time window alone didn't catch it.
        event = make_event(game_id=12345)
        market = make_market(
            sports_market_type="moneyline", game_start_time=NOW - dt.timedelta(hours=3), yes_price=0.0005,
        )
        assert not is_in_scope_game(event, market, NOW)

    def test_excludes_market_already_decided_near_one(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(
            sports_market_type="moneyline", game_start_time=NOW - dt.timedelta(hours=3), yes_price=0.9995,
        )
        assert not is_in_scope_game(event, market, NOW)

    def test_includes_market_still_genuinely_uncertain(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(
            sports_market_type="moneyline", game_start_time=NOW - dt.timedelta(hours=1), yes_price=0.55,
        )
        assert is_in_scope_game(event, market, NOW)

    def test_includes_market_with_unknown_price(self, make_event, make_market):
        # price=None (not yet set / not populated) shouldn't be treated
        # as "decided" — only an actual extreme price excludes.
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="moneyline", game_start_time=NOW, yes_price=None)
        assert is_in_scope_game(event, market, NOW)

    def test_excludes_market_below_liquidity_floor(self, make_event, make_market):
        # regression: an event bundling a liquid moneyline market with a
        # thin draw market (Romanian league, $223 volume on the draw vs
        # $3.6k-$5.4k on the moneyline siblings) can pass the event-level
        # volume_min while the draw market itself is too thin to reliably
        # cross a resting quote.
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="moneyline", game_start_time=NOW, liquidity=5_000)
        assert not is_in_scope_game(event, market, NOW)

    def test_includes_market_at_or_above_liquidity_floor(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="moneyline", game_start_time=NOW, liquidity=32_617)
        assert is_in_scope_game(event, market, NOW)

    def test_includes_market_with_unknown_liquidity(self, make_event, make_market):
        event = make_event(game_id=12345)
        market = make_market(sports_market_type="moneyline", game_start_time=NOW, liquidity=None)
        assert is_in_scope_game(event, market, NOW)


class TestTokensFromMarket:
    def test_derives_label_and_side_per_outcome(self, make_market):
        market = make_market(
            id="42",
            yes_label="New York Liberty",
            no_label="Dallas Wings",
            yes_token_id="tok-yes",
            no_token_id="tok-no",
            game_start_time=NOW,
        )
        tokens = tokens_from_market(market, event_id=999)
        by_side = {t.side: t for t in tokens}
        assert by_side["yes"].label == "new_york_liberty_win"
        assert by_side["yes"].asset_id == "tok-yes"
        assert by_side["no"].label == "dallas_wings_win"
        assert by_side["no"].asset_id == "tok-no"
        assert all(t.market_id == 42 and t.event_id == 999 and t.game_start_time == NOW for t in tokens)

    def test_skips_outcome_with_no_token_id(self, make_market):
        market = make_market(
            yes_label="Team A", no_label="Team B",
            yes_token_id=None, no_token_id="tok-no",
        )
        tokens = tokens_from_market(market, event_id=1)
        assert [t.side for t in tokens] == ["no"]

    def test_generic_yes_no_market_uses_group_item_title_and_only_yes_side(self, make_market):
        # "Will {team} win?" per-outcome split (soccer 3-way style) —
        # outcomes.yes/no are literally "Yes"/"No", team name is on
        # group_item_title. Confirmed live against a real market
        # (question="Will Beijing Guoan FC win on 2026-07-17?",
        # group_item_title="Beijing Guoan FC", outcomes yes/no labeled
        # "Yes"/"No").
        market = make_market(
            question="Will Beijing Guoan FC win on 2026-07-17?",
            group_item_title="Beijing Guoan FC",
            yes_token_id="tok-yes", no_token_id="tok-no",
        )
        tokens = tokens_from_market(market, event_id=1)
        assert len(tokens) == 1
        assert tokens[0].side == "yes"
        assert tokens[0].asset_id == "tok-yes"
        assert tokens[0].label == "beijing_guoan_fc_win"

    def test_generic_yes_no_market_with_no_yes_token_yields_nothing(self, make_market):
        market = make_market(group_item_title="Team A", yes_token_id=None, no_token_id="tok-no")
        assert tokens_from_market(market, event_id=1) == []


class _FakePaginator:
    def __init__(self, items):
        self._items = items

    def iter_items(self):
        yield from self._items


class _StubClient:
    def __init__(self, items_by_tag):
        self.items_by_tag = items_by_tag
        self.calls = []

    def list_events(self, *, tag_ids, tag_match, closed, page_size, volume_min, end_date_min):
        self.calls.append(tag_ids)
        league_tag = tag_ids[1] if isinstance(tag_ids, list) else tag_ids
        return _FakePaginator(self.items_by_tag.get(league_tag, []))


class TestDiscoverTrackedTokens:
    def test_queries_every_in_scope_league(self, make_event, make_market):
        client = _StubClient({})
        discover_tracked_tokens(client, NOW, page_delay=0)
        queried_league_tags = {c[1] for c in client.calls}
        assert queried_league_tags == set(LEAGUE_TAG_IDS.values())

    def test_flattens_only_in_scope_markets(self, make_event, make_market):
        in_scope_market = make_market(
            id="1", yes_label="Team A", no_label="Team B", yes_token_id="tok-a", no_token_id="tok-b",
            sports_market_type="moneyline", game_start_time=NOW,
        )
        futures_market = make_market(id="2", yes_token_id="tok-c", no_token_id="tok-d")
        game_event = make_event(id=10, game_id=555, markets=(in_scope_market,))
        futures_event = make_event(id=20, game_id=None, markets=(futures_market,))
        client = _StubClient({LEAGUE_TAG_IDS["mlb"]: [game_event, futures_event]})

        tokens = discover_tracked_tokens(client, NOW, leagues={"mlb": LEAGUE_TAG_IDS["mlb"]}, page_delay=0)

        assert {t.asset_id for t in tokens} == {"tok-a", "tok-b"}

    def test_dedupes_asset_id_seen_across_leagues(self, make_event, make_market):
        market = make_market(
            id="1", yes_label="Team A", no_label="Team B", yes_token_id="tok-a", no_token_id="tok-b",
            sports_market_type="moneyline", game_start_time=NOW,
        )
        event = make_event(id=10, game_id=555, markets=(market,))
        client = _StubClient({
            LEAGUE_TAG_IDS["mlb"]: [event],
            LEAGUE_TAG_IDS["nba"]: [event],
        })

        tokens = discover_tracked_tokens(
            client, NOW, leagues={"mlb": LEAGUE_TAG_IDS["mlb"], "nba": LEAGUE_TAG_IDS["nba"]}, page_delay=0,
        )

        assert len(tokens) == 2  # yes+no once each, not duplicated per league


class TestMergeTrackedTokens:
    """Regression for the exact bug found live 2026-07-17: overwriting
    the tracked-markets file each discovery run meant that once every
    previously-tracked game legitimately aged out of the active-now
    window (0 currently-active games is a real, correct outcome), a
    shadow_quote_live.py restart landing right then rebuilt its
    TOKEN_LABELS/etc. from an empty file — losing all previously-known
    tokens, even ones with resolved-but-not-yet-REST-confirmed state."""

    def _token(self, asset_id="tok-a", label="team_a_win"):
        return TrackedToken(
            asset_id=asset_id, label=label, market_id=1, event_id=2,
            side="yes", game_start_time=None,
        )

    def test_keeps_existing_token_when_discovery_finds_nothing(self):
        existing = [{"asset_id": "tok-a", "label": "team_a_win"}]
        merged = merge_tracked_tokens(existing, [])
        assert merged == existing

    def test_adds_newly_discovered_token(self):
        existing = [{"asset_id": "tok-a", "label": "team_a_win"}]
        merged = merge_tracked_tokens(existing, [self._token("tok-b", "team_b_win")])
        assert {t["asset_id"] for t in merged} == {"tok-a", "tok-b"}

    def test_existing_entry_wins_over_a_rediscovery_of_the_same_token(self):
        existing = [{"asset_id": "tok-a", "label": "hand-edited-label"}]
        merged = merge_tracked_tokens(existing, [self._token("tok-a", "freshly_discovered_label")])
        assert len(merged) == 1
        assert merged[0]["label"] == "hand-edited-label"
