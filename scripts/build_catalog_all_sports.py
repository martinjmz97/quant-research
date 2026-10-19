import time

import polars as pl
from polymarket.clients.public import PublicClient

from ingestion.polymarket.catalog import RAW_DIR, event_to_rows, save_catalog
from ingestion.polymarket.discovery import iter_sports_events

# Widens scope from the soccer-only catalog (`sports_markets_catalog.parquet`,
# see build_catalog.py) to every sport, keeping the same volume/date filters
# that already made the soccer pull finish in reasonable time. The earlier
# attempt at "every sport" with no checkpointing ran for minutes with no
# ETA and nothing to show for it if killed — this saves a snapshot every
# CHECKPOINT_EVERY events so a kill/crash keeps whatever was pulled so far,
# and drops MAX_EVENTS's role from "the actual stopping condition" to "a
# safety backstop" (real stop is the pagination iterator running dry).
VOLUME_MIN = 20_000
END_DATE_MIN = "2025-01-01"
CHECKPOINT_EVERY = 500
MAX_EVENTS = 100_000
PAGE_SIZE = 100
# ~2 pages/s ran clean for 90s in testing; ~6 pages/s hit the Gamma API's
# undocumented rate limit within 10s (see discovery.py docstring). 0.5s
# gives 2 pages/s with margin.
PAGE_DELAY = 0.5
OUT_PATH = RAW_DIR / "sports_markets_catalog_all.parquet"

client = PublicClient()
t0 = time.time()
rows = []
n_events = 0
for event in iter_sports_events(
    client,
    closed=True,
    page_size=PAGE_SIZE,
    volume_min=VOLUME_MIN,
    end_date_min=END_DATE_MIN,
    page_delay=PAGE_DELAY,
):
    rows.extend(event_to_rows(event))
    n_events += 1
    if n_events % CHECKPOINT_EVERY == 0:
        elapsed = time.time() - t0
        rate = n_events / elapsed
        df = pl.DataFrame(rows, infer_schema_length=None)
        save_catalog(df, OUT_PATH)
        print(
            f"{n_events} events | {len(rows)} market rows | {elapsed:.0f}s elapsed | "
            f"{rate:.2f} events/s | checkpoint saved",
            flush=True,
        )
    if n_events >= MAX_EVENTS:
        print(f"stopping at MAX_EVENTS={MAX_EVENTS} (safety backstop, not the intended stop condition)", flush=True)
        break

elapsed = time.time() - t0
print(f"DONE: {n_events} events, {len(rows)} market rows in {elapsed:.0f}s", flush=True)
df = pl.DataFrame(rows, infer_schema_length=None)
save_catalog(df, OUT_PATH)
print(f"saved to {OUT_PATH}", flush=True)
