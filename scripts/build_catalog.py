import time

import polars as pl
from polymarket.clients.public import PublicClient

from ingestion.polymarket.catalog import CATALOG_PATH, event_to_rows, save_catalog
from ingestion.polymarket.discovery import SOCCER_TAG_ID, iter_sports_events

# Preliminary/bounded run, see POLYMARKET_MM.md "Ingesta de datos" —
# unfiltered and even $100k-volume-filtered pulls across every sport ran
# for minutes without finishing (tens of thousands of events, no total
# exposed by the API to compute an ETA). This scopes to soccer (the first
# concrete sport this project targets) and hard-caps event count so it
# finishes deterministically; widen once the real ingestion strategy for
# "every sport" is decided (see Próximos pasos).
VOLUME_MIN = 20_000
END_DATE_MIN = "2025-01-01"
MAX_EVENTS = 3000

client = PublicClient()
t0 = time.time()
rows = []
n_events = 0
for event in iter_sports_events(
    client,
    closed=True,
    page_size=100,
    volume_min=VOLUME_MIN,
    end_date_min=END_DATE_MIN,
    additional_tag_id=SOCCER_TAG_ID,
):
    rows.extend(event_to_rows(event))
    n_events += 1
    if n_events % 200 == 0:
        elapsed = time.time() - t0
        rate = n_events / elapsed
        print(f"{n_events} events | {len(rows)} market rows | {elapsed:.0f}s elapsed | {rate:.1f} events/s", flush=True)
    if n_events >= MAX_EVENTS:
        print(f"stopping at MAX_EVENTS={MAX_EVENTS} (preliminary cap)", flush=True)
        break

elapsed = time.time() - t0
print(f"DONE: {n_events} events, {len(rows)} market rows in {elapsed:.0f}s", flush=True)
df = pl.DataFrame(rows, infer_schema_length=None)
save_catalog(df, CATALOG_PATH)
print(f"saved to {CATALOG_PATH}", flush=True)
