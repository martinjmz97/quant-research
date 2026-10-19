"""Only load_tracked_asset_ids() is pure/sync enough to unit test cheaply
— record_forever()'s reconnect-on-idle behavior (see IDLE_RECV_TIMEOUT_S
in record_orderbook.py: found live 2026-07-17, a 0-token or otherwise
message-silent subscription never re-checked tracked_markets.json for
changes, missing a newly-discovered game for 30+ minutes) is real I/O
loop logic that would need heavy asyncio/websocket mocking to cover
meaningfully — not done here, a known coverage gap.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import record_orderbook as ro  # noqa: E402


class TestLoadTrackedAssetIds:
    def test_returns_empty_list_when_config_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ro, "CONFIG_PATH", tmp_path / "does-not-exist.json")
        assert ro.load_tracked_asset_ids() == []

    def test_returns_asset_ids_from_config(self, tmp_path, monkeypatch):
        config = tmp_path / "tracked_markets.json"
        config.write_text(json.dumps({"tokens": [{"asset_id": "tok-a"}, {"asset_id": "tok-b"}]}))
        monkeypatch.setattr(ro, "CONFIG_PATH", config)
        assert ro.load_tracked_asset_ids() == ["tok-a", "tok-b"]

    def test_returns_empty_list_when_config_has_no_tokens(self, tmp_path, monkeypatch):
        config = tmp_path / "tracked_markets.json"
        config.write_text(json.dumps({"tokens": []}))
        monkeypatch.setattr(ro, "CONFIG_PATH", config)
        assert ro.load_tracked_asset_ids() == []
