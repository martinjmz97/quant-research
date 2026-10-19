"""Factories for minimal-but-valid Gamma API models, used to test the
catalog flattening logic without hitting the network. Every sub-object on
Market/Event is a required field (no Optional wrapper), but the sub-objects
themselves have no required fields of their own — so these factories build
one empty instance of each and let each test override just what it cares
about.
"""

import pytest
from polymarket.models.gamma.common import SportsMetadata
from polymarket.models.gamma.event import (
    Event,
    EventDisplay,
    EventEstimation,
    EventResolution,
    EventSchedule,
    EventSportsMetadata,
    EventState,
    EventTrading,
)
from polymarket.models.gamma.event import EventMetrics as EventMetricsModel
from polymarket.models.gamma.market import (
    Market,
    MarketMetrics,
    MarketOutcome,
    MarketOutcomes,
    MarketPrices,
    MarketResolution,
    MarketRewards,
    MarketSportsMetadata,
    MarketState,
    MarketTrading,
)


@pytest.fixture
def make_market():
    def _make(
        *,
        id="1",
        condition_id="0x" + "ab" * 32,
        question="Will it happen?",
        group_item_title=None,
        yes_token_id="tok-yes",
        no_token_id="tok-no",
        yes_label="Yes",
        no_label="No",
        yes_price=None,
        volume=None,
        liquidity=None,
        min_tick_size=None,
        min_order_size=None,
        sports_market_type=None,
        game_id=None,
        game_start_time=None,
        closed=False,
    ):
        return Market(
            id=id,
            condition_id=condition_id,
            question=question,
            group_item_title=group_item_title,
            state=MarketState(closed=closed),
            outcomes=MarketOutcomes(
                yes=MarketOutcome(label=yes_label, token_id=yes_token_id, price=yes_price),
                no=MarketOutcome(label=no_label, token_id=no_token_id, price=None),
            ),
            metrics=MarketMetrics(volume=volume, liquidity=liquidity),
            prices=MarketPrices(),
            trading=MarketTrading(minimum_tick_size=min_tick_size, minimum_order_size=min_order_size),
            resolution=MarketResolution(),
            rewards=MarketRewards(),
            sports=MarketSportsMetadata(
                sports_market_type=sports_market_type, game_id=game_id, game_start_time=game_start_time,
            ),
            events=(),
            tags=(),
        )

    return _make


@pytest.fixture
def make_event():
    def _make(
        *,
        id=1,
        title="Team A vs Team B",
        markets=(),
        sport=None,
        home_team=None,
        away_team=None,
        score=None,
        period=None,
        league=None,
        game_id=None,
    ):
        sport_metadata = (
            SportsMetadata(id=1, sport=sport, image="", resolution="", ordering="", tags="", series="")
            if sport
            else None
        )
        return Event(
            id=id,
            title=title,
            state=EventState(),
            schedule=EventSchedule(),
            metrics=EventMetricsModel(),
            display=EventDisplay(),
            trading=EventTrading(),
            resolution=EventResolution(),
            estimation=EventEstimation(),
            sports=EventSportsMetadata(
                series_slug=league,
                score=score,
                period=period,
                game_id=game_id,
                home_team_name=home_team,
                away_team_name=away_team,
                sport=sport_metadata,
            ),
            partners=(),
            markets=tuple(markets),
            series=(),
            tags=(),
            creators=(),
        )

    return _make
