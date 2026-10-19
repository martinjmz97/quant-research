from ingestion.polymarket.discovery import SOCCER_TAG_ID, SPORTS_TAG_ID, iter_sports_events


class _FakePaginator:
    def __init__(self, items):
        self._items = items

    def iter_items(self):
        yield from self._items


class _StubClient:
    def __init__(self, items):
        self._items = items
        self.calls = []

    def list_events(self, *, tag_ids, tag_match, closed, page_size, volume_min, end_date_min):
        self.calls.append(
            {
                "tag_ids": tag_ids,
                "tag_match": tag_match,
                "closed": closed,
                "page_size": page_size,
                "volume_min": volume_min,
                "end_date_min": end_date_min,
            }
        )
        return _FakePaginator(self._items)


class TestIterSportsEvents:
    def test_yields_every_item_from_the_paginator(self):
        client = _StubClient(["event-1", "event-2"])
        assert list(iter_sports_events(client)) == ["event-1", "event-2"]

    def test_filters_by_the_sports_master_tag(self):
        client = _StubClient([])
        list(iter_sports_events(client))
        assert client.calls[0]["tag_ids"] == SPORTS_TAG_ID

    def test_defaults_to_closed_events_for_historical_ingestion(self):
        client = _StubClient([])
        list(iter_sports_events(client))
        assert client.calls[0]["closed"] is True

    def test_closed_flag_and_page_size_are_forwarded(self):
        client = _StubClient([])
        list(iter_sports_events(client, closed=False, page_size=50))
        assert client.calls[0]["closed"] is False
        assert client.calls[0]["page_size"] == 50

    def test_volume_and_date_filters_default_to_none(self):
        client = _StubClient([])
        list(iter_sports_events(client))
        assert client.calls[0]["volume_min"] is None
        assert client.calls[0]["end_date_min"] is None

    def test_volume_and_date_filters_are_forwarded(self):
        client = _StubClient([])
        list(iter_sports_events(client, volume_min=50_000, end_date_min="2025-01-01"))
        assert client.calls[0]["volume_min"] == 50_000
        assert client.calls[0]["end_date_min"] == "2025-01-01"

    def test_no_additional_tag_means_just_the_sports_master_tag(self):
        client = _StubClient([])
        list(iter_sports_events(client))
        assert client.calls[0]["tag_ids"] == SPORTS_TAG_ID
        assert client.calls[0]["tag_match"] is None

    def test_additional_tag_id_narrows_with_tag_match_all(self):
        client = _StubClient([])
        list(iter_sports_events(client, additional_tag_id=SOCCER_TAG_ID))
        assert client.calls[0]["tag_ids"] == [SPORTS_TAG_ID, SOCCER_TAG_ID]
        assert client.calls[0]["tag_match"] == "all"
