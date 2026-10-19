from ingestion.polymarket.catalog import event_to_rows


class TestEventToRows:
    def test_one_row_per_market_in_the_event(self, make_event, make_market):
        event = make_event(markets=[make_market(id="1"), make_market(id="2")])
        rows = event_to_rows(event)
        assert [r["market_id"] for r in rows] == ["1", "2"]

    def test_empty_event_yields_no_rows(self, make_event):
        assert event_to_rows(make_event(markets=[])) == []

    def test_carries_sport_and_game_state_from_the_event(self, make_event, make_market):
        event = make_event(
            markets=[make_market()],
            sport="mlb",
            home_team="Atlanta Braves",
            away_team="Chicago White Sox",
            score="0-0",
            period="Top 1st",
            league="mlb",
        )
        row = event_to_rows(event)[0]
        assert row["sport"] == "mlb"
        assert row["home_team"] == "Atlanta Braves"
        assert row["away_team"] == "Chicago White Sox"
        assert row["score_at_snapshot"] == "0-0"
        assert row["period_at_snapshot"] == "Top 1st"

    def test_sport_is_none_when_event_has_no_sports_metadata(self, make_event, make_market):
        row = event_to_rows(make_event(markets=[make_market()]))[0]
        assert row["sport"] is None

    def test_carries_tick_and_order_size_from_market_trading(self, make_event, make_market):
        market = make_market(min_tick_size=0.001, min_order_size=5.0)
        row = event_to_rows(make_event(markets=[market]))[0]
        assert row["min_tick_size"] == 0.001
        assert row["min_order_size"] == 5.0

    def test_carries_token_ids_for_both_outcomes(self, make_event, make_market):
        market = make_market(yes_token_id="tok-yes-1", no_token_id="tok-no-1")
        row = event_to_rows(make_event(markets=[market]))[0]
        assert row["yes_token_id"] == "tok-yes-1"
        assert row["no_token_id"] == "tok-no-1"

    def test_volume_and_yes_price_are_converted_to_float(self, make_event, make_market):
        market = make_market(volume=123.45, yes_price=0.62)
        row = event_to_rows(make_event(markets=[market]))[0]
        assert row["volume"] == 123.45
        assert row["yes_price"] == 0.62
        assert isinstance(row["volume"], float)
