"""Record the live CLOB market websocket (book snapshots + price_changes)
for the currently-active set of tokens to disk, indefinitely, with
reconnect-on-drop and reconnect-on-token-list-change.

Meant to run as a long-lived process (launchd on a remote host, see
POLYMARKET_MM.md "Infraestructura") — this is the only way to get real
order-book history, since Polymarket's REST API only exposes the CURRENT
book (no historical endpoint, confirmed against the SDK). Each raw
message is written as one JSONL line with a receipt-time wall-clock
timestamp prepended, so book state can be reconstructed later by replaying
snapshot + diffs in order.

L2 aggregate depth only (price+size per level), not L3 order-level — the
feed does not expose individual order queue position.

The tracked token list used to be a hand-maintained dict (one match at a
time) — replaced 2026-07-17 with scripts/discover_active_markets.py's
output (data/raw/polymarket/orderbook_live/tracked_markets.json),
refreshed by re-reading that file periodically and reconnecting the
websocket with the updated list when it changes (the subscribe protocol
here sends the full asset list once at connect time; there's no known
incremental add/remove message, so reconnecting is the simplest correct
way to pick up new games without restarting this whole process).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path

import websockets

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "polymarket" / "orderbook_live"
OUT_PATH = OUT_DIR / "live_book.jsonl"
CONFIG_PATH = OUT_DIR / "tracked_markets.json"

RECONNECT_BACKOFF_S = 5
# how often to check tracked_markets.json for changes while connected —
# new games don't start more often than this, no need to check per-message.
CONFIG_REFRESH_INTERVAL_S = 300
# recv() timeout while idle — this is what actually makes the refresh
# check above fire. Found live 2026-07-17: a reconnect landed with 0
# subscribed tokens (nothing tracked at that instant), and since the old
# code only checked for config changes INSIDE `async for raw_msg in ws`,
# a subscription that never receives a message (0 tokens, or tokens with
# no live trading) never re-checked either — stuck for 30+ minutes,
# missing a newly-discovered game entirely until this fix.
IDLE_RECV_TIMEOUT_S = 30


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_tracked_asset_ids() -> list[str]:
    if not CONFIG_PATH.exists():
        return []
    data = json.loads(CONFIG_PATH.read_text())
    return [t["asset_id"] for t in data["tokens"]]


async def record_forever() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with OUT_PATH.open("a") as f:
        while True:
            asset_ids = load_tracked_asset_ids()
            if not asset_ids:
                print(f"[{_now_iso()}] no tracked tokens right now, waiting", flush=True)
                await asyncio.sleep(15)
                continue
            try:
                async with websockets.connect(WS_URL, ping_interval=10, ping_timeout=20) as ws:
                    await ws.send(json.dumps({"assets_ids": asset_ids, "type": "market"}))
                    print(f"[{_now_iso()}] connected, subscribed {len(asset_ids)} tokens", flush=True)
                    last_refresh = asyncio.get_event_loop().time()
                    while True:
                        try:
                            raw_msg = await asyncio.wait_for(ws.recv(), timeout=IDLE_RECV_TIMEOUT_S)
                        except asyncio.TimeoutError:
                            raw_msg = None
                        if raw_msg is not None:
                            line = json.dumps({"recv_ts": _now_iso(), "raw": json.loads(raw_msg)})
                            f.write(line + "\n")
                            f.flush()
                        now = asyncio.get_event_loop().time()
                        if now - last_refresh > CONFIG_REFRESH_INTERVAL_S:
                            last_refresh = now
                            if set(load_tracked_asset_ids()) != set(asset_ids):
                                print(f"[{_now_iso()}] tracked-token list changed, reconnecting", flush=True)
                                break
            except Exception as exc:
                print(f"[{_now_iso()}] disconnected ({exc!r}), reconnecting in {RECONNECT_BACKOFF_S}s", flush=True)
                await asyncio.sleep(RECONNECT_BACKOFF_S)


if __name__ == "__main__":
    asyncio.run(record_forever())
