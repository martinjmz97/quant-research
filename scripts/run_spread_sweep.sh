#!/bin/bash
# Runs scripts/spread_sweep_backtest.py once per HALF_SPREAD value against
# the recorded tape, sequentially (one subprocess per value — see that
# script's docstring for why it can't be a loop within one process).
# Each run replays the full tape (took ~3.5min for 22.27M lines on the Mac
# mini, 2026-07-18) so this is slow by design, not a bug.
#
# Usage: scripts/run_spread_sweep.sh ["0.01 0.02 0.03 0.05 0.08"]
set -euo pipefail
cd "$(dirname "$0")/.."

SPREADS="${1:-0.01 0.02 0.03 0.05 0.08}"
OUT="data/raw/polymarket/orderbook_live/spread_sweep_results.jsonl"
: > "$OUT"

for s in $SPREADS; do
  echo "[$(date -u +%FT%TZ)] running SHADOW_HALF_SPREAD=$s..." >&2
  SHADOW_HALF_SPREAD="$s" .venv/bin/python3 scripts/spread_sweep_backtest.py >> "$OUT"
done

echo "[$(date -u +%FT%TZ)] done — results in $OUT" >&2
