"""Live dashboard for the shadow-quoting run — serves a self-refreshing
page reading shadow_state.json (current session, live books) plus two
DURABLE, append-only, never-renamed/reset logs written by
shadow_quote_live.py: round_trips.jsonl and resolved_games.jsonl. No new
dependencies: stdlib http.server only.

Rewritten 2026-07-17 — the previous version re-derived round trips by
replaying shadow_fills.jsonl itself. That file gets manually archived
(reset) before every redeploy restart (see POLYMARKET_MM.md "Round-trips
durables"), so the dashboard's own history silently reset on every
restart too — confirmed live: MLB's round-trip distribution disappeared
from the dashboard even though the games had already resolved, because
shadow_quote_live.py now tracks round trips AND resolved-game summaries
itself and logs them durably — this dashboard just wasn't reading them.
Reading those logs directly instead of re-deriving from fills also
removes an entire duplicate implementation of the same round-trip-
detection logic that could drift from the live one.

Bind: 0.0.0.0:8765 — reachable at http://<private-host-ip>:8765
from any device on the tailnet.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8765
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "polymarket" / "orderbook_live"
STATE_PATH = DATA_DIR / "shadow_state.json"
ROUND_TRIPS_PATH = DATA_DIR / "round_trips.jsonl"
RESOLVED_GAMES_PATH = DATA_DIR / "resolved_games.jsonl"
TRACKED_MARKETS_PATH = DATA_DIR / "tracked_markets.json"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def build_payload() -> dict:
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {"books": {}, "updated_at": None}
    books = state.get("books", {})

    round_trips = load_jsonl(ROUND_TRIPS_PATH)  # durable, cumulative across every restart
    pnls = [rt["pnl"] for rt in round_trips]
    n = len(pnls)
    mean_pnl = sum(pnls) / n if n else 0.0
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / n if n else None
    variance = sum((p - mean_pnl) ** 2 for p in pnls) / (n - 1) if n > 1 else None
    std_pnl = variance ** 0.5 if variance is not None else None
    cumulative_realized = sum(pnls)

    # breakdown by HOW each trip closed — "organic" (crossed on its own),
    # "forced_flatten" (actively crossed the book near resolution/game-over),
    # "resolution_forced_close" (rode all the way to the terminal 0/1
    # payout). Round trips logged before close_reason existed (and the
    # hand-backfilled MLB/WNBA ones) have no tag — bucketed as "unknown"
    # rather than guessed. This is what actually answers "how much of our
    # inventory rides to resolution instead of being closed out" — the
    # single win-rate/mean-pnl tiles above can't distinguish that.
    reason_stats = {}
    for rt in round_trips:
        reason = rt.get("close_reason", "unknown")
        s = reason_stats.setdefault(reason, {"n": 0, "pnl_sum": 0.0})
        s["n"] += 1
        s["pnl_sum"] += rt["pnl"]
    for s in reason_stats.values():
        s["pnl_mean"] = s["pnl_sum"] / s["n"] if s["n"] else 0.0

    resolved_games = load_jsonl(RESOLVED_GAMES_PATH)  # durable, cumulative across every restart
    resolved_games.sort(key=lambda g: g.get("resolved_at", ""), reverse=True)
    net_resolved_pnl = sum(g.get("final_cash", 0) for g in resolved_games)

    # every token discover_active_markets.py has ever found (cumulative,
    # see merge_tracked_tokens) — cross-referenced against the live
    # books dict to show whether record_orderbook.py has actually
    # started feeding it real ticks yet (best_bid not None) or it's
    # still pending (just discovered, or game far enough out that the
    # websocket hasn't been resubscribed — see IDLE_RECV_TIMEOUT_S in
    # record_orderbook.py for why that resubscribe can lag).
    tracked = json.loads(TRACKED_MARKETS_PATH.read_text())["tokens"] if TRACKED_MARKETS_PATH.exists() else []
    upcoming = []
    for t in tracked:
        book = books.get(t["label"])
        upcoming.append({
            "label": t["label"],
            "game_start_time": t["game_start_time"],
            "has_live_data": bool(book and book.get("best_bid") is not None),
            "is_resolved": any(g["label"] == t["label"] for g in resolved_games),
        })
    upcoming.sort(key=lambda t: t["game_start_time"] or "")

    worst_drawdown = min((b.get("worst_mark_to_market", 0) for b in books.values()), default=0)
    total_unrealized_mtm = sum(b.get("mark_to_market", 0) for b in books.values())

    # worst/best case if every currently-tracked book resolved RIGHT NOW:
    # pays exactly 0 or 1, not the live fair_value — computed directly
    # from cash/position already in the live snapshot, no fills replay
    # needed. Sum across tokens is conservative (assumes every open
    # position resolves against us simultaneously, overstating true
    # joint risk since outcomes aren't independent across unrelated
    # markets) but that's the right direction to err for a risk figure.
    open_positions = {}
    for label, b in books.items():
        position, cash = b.get("position", 0.0), b.get("cash", 0.0)
        if abs(position) < 1e-6:
            continue
        pays_0, pays_1 = cash + position * 0.0, cash + position * 1.0
        open_positions[label] = {
            "open_position": position,
            "worst_case_resolution_pnl": min(pays_0, pays_1),
            "best_case_resolution_pnl": max(pays_0, pays_1),
        }
    worst_case_if_all_resolve_now = sum(o["worst_case_resolution_pnl"] for o in open_positions.values())

    return {
        "updated_at": state.get("updated_at"),
        "books": books,
        "n_fills_live_session": sum(b.get("n_fills", 0) for b in books.values()),
        "round_trips": round_trips,
        "n_round_trips": n,
        "mean_round_trip_pnl": mean_pnl,
        "std_round_trip_pnl": std_pnl,
        "win_rate": win_rate,
        "cumulative_realized_pnl": cumulative_realized,
        "reason_stats": reason_stats,
        "resolved_games": resolved_games,
        "n_resolved_games": len(resolved_games),
        "net_resolved_pnl": net_resolved_pnl,
        "upcoming": upcoming,
        "total_unrealized_mtm": total_unrealized_mtm,
        "worst_drawdown": worst_drawdown,
        "open_positions": open_positions,
        "worst_case_if_all_resolve_now": worst_case_if_all_resolve_now,
    }


PAGE = """<!doctype html><meta charset="utf-8">
<title>Shadow MM — monitor en vivo</title>
<style>
:root {
  color-scheme: light;
  --surface-1: #fcfcfb; --page: #f9f9f7; --text-primary: #0b0b0b;
  --text-secondary: #52514e; --text-muted: #898781; --grid: #e1e0d9;
  --axis: #c3c2b7; --blue: #2a78d6; --red: #e34948; --green: #008300;
  --border: rgba(11,11,11,0.10);
}
@media (prefers-color-scheme: dark) {
  :root { color-scheme: dark; --surface-1: #1a1a19; --page: #0d0d0d;
    --text-primary: #fff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --blue: #3987e5; --red: #e66767;
    --green: #0ca30c; --border: rgba(255,255,255,0.10); }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; padding: 20px 16px 48px; }
.wrap { max-width: 980px; margin: 0 auto; }
h1 { font-size: 17px; font-weight: 600; margin: 0 0 2px; }
.sub { font-size: 12px; color: var(--text-muted); margin: 0 0 20px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px,1fr)); gap: 10px; margin-bottom: 20px; }
.tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }
.tile .label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .03em; }
.tile .value { font-size: 20px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }
.tile .value.pos { color: var(--green); } .tile .value.neg { color: var(--red); }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
.card h2 { font-size: 13px; font-weight: 600; margin: 0 0 10px; }
.table-scroll { overflow-x: auto; margin: 0 -16px; padding: 0 16px; }
table { width: 100%; min-width: 1100px; border-collapse: collapse; font-size: 12px; }
th, td { text-align: right; padding: 5px 8px; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--text-muted); font-weight: 500; }
svg { display: block; width: 100%; height: auto; }
.bar { fill: var(--blue); }
.bar.neg { fill: var(--red); }
.axis-label { fill: var(--text-muted); font-size: 10px; }
.empty { color: var(--text-muted); font-size: 12px; padding: 20px 0; text-align: center; }
</style>
<div class="wrap">
  <h1>Shadow MM — monitor en vivo</h1>
  <p class="sub" id="updated">cargando...</p>
  <div class="tiles" id="tiles"></div>
  <div class="card"><h2>Distribución de round-trips cerrados (acumulado histórico, todos los partidos)</h2><div id="hist"></div></div>
  <div class="card"><h2>Round-trips por cómo se cerraron</h2><div id="reasons"></div></div>
  <div class="card"><h2>Partidos resueltos (acumulado histórico)</h2><div id="resolved"></div></div>
  <div class="card"><h2>Próximos partidos / trackeados</h2><div id="upcoming"></div></div>
  <div class="card"><h2>Books en vivo (sesión actual)</h2><div id="books"></div></div>
</div>
<script>
function fmt(x, d=4) { return x === null || x === undefined ? "—" : Number(x).toFixed(d); }
function tile(label, value, cls) {
  return `<div class="tile"><div class="label">${label}</div><div class="value ${cls||''}">${value}</div></div>`;
}
function renderHist(pnls) {
  if (!pnls.length) return '<p class="empty">todavía no hay round-trips cerrados</p>';
  const W=900, H=160, padL=40, padB=20, padT=10;
  const min = Math.min(...pnls, 0), max = Math.max(...pnls, 0);
  const nBins = Math.min(20, Math.max(5, Math.round(Math.sqrt(pnls.length))));
  const binW = (max - min) / nBins || 1;
  const bins = new Array(nBins).fill(0);
  pnls.forEach(p => { let idx = Math.floor((p - min) / binW); if (idx>=nBins) idx=nBins-1; if(idx<0) idx=0; bins[idx]++; });
  const maxCount = Math.max(...bins);
  const xScale = v => padL + (v - min) / (max - min || 1) * (W - padL - 10);
  const yScale = v => padT + (H - padT - padB) - (v / maxCount) * (H - padT - padB);
  const zeroX = xScale(0);
  let bars = '';
  for (let i=0;i<nBins;i++){
    const x0 = padL + i*(W-padL-10)/nBins, x1 = padL + (i+1)*(W-padL-10)/nBins;
    const binCenter = min + (i+0.5)*binW;
    const y = yScale(bins[i]);
    bars += `<rect class="bar ${binCenter<0?'neg':''}" x="${x0+1}" y="${y}" width="${x1-x0-2}" height="${(H-padB)-y}" rx="1"/>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}">
    <line x1="${padL}" x2="${W-10}" y1="${H-padB}" y2="${H-padB}" stroke="var(--axis)"/>
    <line x1="${zeroX}" x2="${zeroX}" y1="${padT}" y2="${H-padB}" stroke="var(--axis)" stroke-dasharray="2,2"/>
    ${bars}
    <text class="axis-label" x="${padL}" y="${H-4}">${fmt(min,3)}</text>
    <text class="axis-label" x="${W-10}" y="${H-4}" text-anchor="end">${fmt(max,3)}</text>
  </svg>`;
}
const REASON_LABEL = {
  organic: "orgánico (cruzó solo)",
  forced_flatten: "flatten activo (cerca de resolución/fin de partido)",
  resolution_forced_close: "forzado a resolución (rodó hasta el payout terminal)",
  unknown: "sin tag (previo a este campo / backfilled)",
};
function renderReasons(stats) {
  const keys = Object.keys(stats);
  if (!keys.length) return '<p class="empty">todavía no hay round-trips cerrados</p>';
  const total = keys.reduce((acc, k) => acc + stats[k].n, 0);
  const order = ["organic", "forced_flatten", "resolution_forced_close", "unknown"];
  const sorted = keys.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return `<div class="table-scroll"><table><thead><tr><th>cómo cerró</th><th>n</th><th>% del total</th><th>PnL medio</th><th>PnL sumado</th></tr></thead><tbody>
    ${sorted.map(k => {
      const s = stats[k];
      const pct = total ? (100 * s.n / total).toFixed(0) + '%' : '—';
      return `<tr><td>${REASON_LABEL[k] || k}</td><td>${s.n}</td><td>${pct}</td><td class="${s.pnl_mean<0?'neg':s.pnl_mean>0?'pos':''}">${fmt(s.pnl_mean)}</td><td class="${s.pnl_sum<0?'neg':s.pnl_sum>0?'pos':''}">${fmt(s.pnl_sum)}</td></tr>`;
    }).join('')}
  </tbody></table></div>
  <p style="font-size:11px;color:var(--text-muted);margin-top:8px">"forzado a resolución" = la posición quedó abierta hasta que el mercado resolvió y se liquidó contra el payout real (0 o 1) en vez de cerrarse activamente antes — es el caso de cola que más importa para selección adversa. Si ese PnL medio es consistentemente negativo y su % del total es alto, el problema no es calibración de spread, es que el mecanismo de flatten/stop-quoting no está cerrando el inventario a tiempo.</p>`;
}
function renderBooks(books, openPositions) {
  const rows = Object.values(books).filter(b => b.label && !/^[0-9]+$/.test(b.label));
  if (!rows.length) return '<p class="empty">sin datos todavía</p>';
  return `<div class="table-scroll"><table><thead><tr><th>token</th><th>nuestro bid</th><th>nuestro ask</th><th>bid real</th><th>ask real</th><th>fills</th><th>re-quotes</th><th>posición</th><th>mtm (fair value)</th><th>peor caso si resuelve YA</th><th>mejor caso si resuelve YA</th><th>bloqueados x tope</th><th>ensanches tóxicos</th><th>en cooldown</th><th>paradas</th><th>parado ahora</th></tr></thead><tbody>
    ${rows.map(b => {
      const op = (openPositions && openPositions[b.label]) || {};
      return `<tr><td>${b.label}</td><td>${b.is_stopped ? '—' : fmt(b.our_bid,4)}</td><td>${b.is_stopped ? '—' : fmt(b.our_ask,4)}</td><td>${fmt(b.best_bid,3)}</td><td>${fmt(b.best_ask,3)}</td><td>${b.n_fills}</td><td>${b.n_requotes ?? 0}</td><td>${fmt(b.position,2)}</td><td>${fmt(b.mark_to_market,3)}</td><td class="${op.worst_case_resolution_pnl<0?'neg':''}">${fmt(op.worst_case_resolution_pnl,3)}</td><td>${fmt(op.best_case_resolution_pnl,3)}</td><td>${b.n_blocked_by_inventory_cap ?? 0}</td><td>${b.n_toxic_widenings ?? 0}</td><td>${b.in_toxic_cooldown ? '🔶' : ''}</td><td>${b.n_stops ?? 0}</td><td>${b.is_stopped ? '⛔' : ''}</td></tr>`;
    }).join('')}
  </tbody></table></div>
  <p style="font-size:11px;color:var(--text-muted);margin-top:8px">"nuestro bid/ask" es la cotización resting actual (se actualiza solo cuando hay drift/intervalo/fill, no en cada mensaje — comparalo con "bid/ask real" para ver cuánto nos quedamos atrás entre re-quotes). "peor/mejor caso si resuelve YA" marca la posición abierta contra el payoff terminal real (0 o 1), no contra el fair value actual. "bloqueados x tope" = veces que el límite de inventario impidió un fill que hubiera agrandado la posición. "ensanches tóxicos" = veces que el detector de flujo disparó un ensanchamiento reactivo. "paradas" = veces que se retiró la cotización del todo (cerca de resolución, el detector tóxico disparó dos veces seguidas, o el book no tiene liquidez real — spread &gt;30%). Esta tabla es solo la sesión actual (se reinicia con el proceso) — el historial completo está en las otras dos secciones.</p>`;
}
function renderResolved(games) {
  if (!games.length) return '<p class="empty">todavía no resolvió ningún partido</p>';
  return `<div class="table-scroll"><table><thead><tr><th>token</th><th>resuelto</th><th>payout</th><th>cash final</th><th>fills</th><th>flattens forzados</th><th>estado partido</th><th>backfilled</th></tr></thead><tbody>
    ${games.map(g => `<tr><td>${g.label}</td><td>${(g.resolved_at||'').replace('T',' ').slice(0,19)}</td><td>${fmt(g.payout,2)}</td><td class="${g.final_cash<0?'neg':g.final_cash>0?'pos':''}">${fmt(g.final_cash,3)}</td><td>${g.n_fills}</td><td>${g.n_forced_flattens ?? 0}</td><td>${g.game_period ?? '—'}</td><td>${g.backfilled ? '📦' : ''}</td></tr>`).join('')}
  </tbody></table></div>
  <p style="font-size:11px;color:var(--text-muted);margin-top:8px">📦 = reconstruido de un archivo viejo a mano (antes de que este log existiera), no generado por el mecanismo automático. "PnL neto partidos resueltos" (suma de cash final) y "PnL realizado acum. (RT)" (suma de round-trips detectados) miden cosas relacionadas pero no idénticas — el detector de round-trips usa un margen de tolerancia (cruce de signo, no cero exacto), así que pueden no coincidir centavo a centavo.</p>`;
}
function renderUpcoming(rows) {
  if (!rows.length) return '<p class="empty">nada trackeado todavía — el discovery corre cada 15 min</p>';
  const now = new Date().toISOString();
  return `<div class="table-scroll"><table><thead><tr><th>token</th><th>kickoff (UTC)</th><th>estado</th></tr></thead><tbody>
    ${rows.map(t => {
      const status = t.is_resolved ? '✅ resuelto' : t.has_live_data ? '🟢 con datos en vivo' : (t.game_start_time && t.game_start_time > now) ? '⏳ próximo' : '🟡 esperando datos';
      return `<tr><td>${t.label}</td><td>${(t.game_start_time||'—').replace('T',' ').slice(0,16)}</td><td>${status}</td></tr>`;
    }).join('')}
  </tbody></table></div>
  <p style="font-size:11px;color:var(--text-muted);margin-top:8px">Todo lo que descubrió scripts/discover_active_markets.py alguna vez (acumulativo, nunca se saca — ver POLYMARKET_MM.md "tracked_markets.json se sobreescribía"). "🟡 esperando datos" con el kickoff ya pasado puede tardar hasta ~5min en resolverse tras el descubrimiento (record_orderbook.py resuscribe con ese retraso).</p>`;
}
async function refresh() {
  const r = await fetch('/api/data');
  const d = await r.json();
  document.getElementById('updated').textContent = 'actualizado: ' + (d.updated_at || '—');
  document.getElementById('tiles').innerHTML = [
    tile('partidos resueltos', d.n_resolved_games),
    tile('PnL neto partidos resueltos', fmt(d.net_resolved_pnl), d.net_resolved_pnl>0?'pos':d.net_resolved_pnl<0?'neg':''),
    tile('round-trips cerrados', d.n_round_trips),
    tile('PnL medio / RT', fmt(d.mean_round_trip_pnl), d.mean_round_trip_pnl>0?'pos':d.mean_round_trip_pnl<0?'neg':''),
    tile('win rate', d.win_rate===null?'—':(d.win_rate*100).toFixed(0)+'%'),
    tile('PnL realizado acum. (RT)', fmt(d.cumulative_realized_pnl), d.cumulative_realized_pnl>0?'pos':d.cumulative_realized_pnl<0?'neg':''),
    tile('mtm no realizado (sesión actual)', fmt(d.total_unrealized_mtm), d.total_unrealized_mtm>0?'pos':d.total_unrealized_mtm<0?'neg':''),
    tile('peor caso si TODO resuelve ya', fmt(d.worst_case_if_all_resolve_now), 'neg'),
    tile('peor drawdown visto (sesión actual)', fmt(d.worst_drawdown), 'neg'),
    tile('fills sesión actual', d.n_fills_live_session),
  ].join('');
  document.getElementById('hist').innerHTML = renderHist(d.round_trips.map(rt => rt.pnl));
  document.getElementById('reasons').innerHTML = renderReasons(d.reason_stats);
  document.getElementById('resolved').innerHTML = renderResolved(d.resolved_games);
  document.getElementById('upcoming').innerHTML = renderUpcoming(d.upcoming);
  document.getElementById('books').innerHTML = renderBooks(d.books, d.open_positions);
}
refresh();
setInterval(refresh, 5000);
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/api/data":
            payload = json.dumps(build_payload()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"dashboard on :{PORT}", flush=True)
    server.serve_forever()
