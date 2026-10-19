"""
Local terminal: news matched against value-chain chokepoints, with
90-day directional theses, as a review queue. Run with:
    streamlit run src/dashboard/app.py --server.address 0.0.0.0

Not a live-alerting system — by design (per user's choice) this is a queue
you review when you open it, not a push-notification system.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news.rss_ingest import fetch_new_articles, ARTICLES_PATH
from news.match_chains import match_articles

REVIEWED_PATH = "data/news/reviewed.json"
ROLE_LABEL = {"chokepoint": "ORIGEN", "direct": "DIRECTA", "indirect": "INDIRECTA", "beneficiary": "BENEFICIARIO"}

st.set_page_config(page_title="Terminal · Cadenas de Valor", layout="wide", page_icon="📡")

st.markdown("""
<style>
    .stApp { font-family: 'SF Mono', 'Consolas', monospace; }
    div[data-testid="stMetricValue"] { font-family: 'SF Mono', 'Consolas', monospace; }
    .ticker-bull { color: #00e0a0; font-weight: 700; }
    .ticker-bear { color: #ff4b6e; font-weight: 700; }
    .thesis-box { border-left: 3px solid #444; padding: 6px 12px; margin: 4px 0; font-size: 0.92em; }
    .thesis-bear { border-left-color: #ff4b6e; background: rgba(255,75,110,0.06); }
    .thesis-bull { border-left-color: #00e0a0; background: rgba(0,224,160,0.06); }
    h1, h2, h3 { font-family: 'SF Mono', 'Consolas', monospace; letter-spacing: -0.5px; }
    .chokepoint-tag { color: #8a8f98; text-transform: uppercase; font-size: 0.78em; letter-spacing: 1px; }
</style>
""", unsafe_allow_html=True)


def load_reviewed() -> set:
    try:
        return set(json.loads(Path(REVIEWED_PATH).read_text()))
    except FileNotFoundError:
        return set()


def save_reviewed(reviewed: set):
    Path(REVIEWED_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(REVIEWED_PATH).write_text(json.dumps(sorted(reviewed)))


@st.cache_data(ttl=60)
def load_matches() -> pd.DataFrame:
    try:
        articles = pd.read_parquet(ARTICLES_PATH)
    except FileNotFoundError:
        return pd.DataFrame(columns=["article_id", "published_utc", "title", "link", "industry", "chokepoint", "companies", "thesis_90d"])
    return match_articles(articles)


def ticker_badge(ticker: str, direction: str, role: str) -> str:
    cls = "ticker-bull" if direction == "bullish" else "ticker-bear"
    arrow = "▲" if direction == "bullish" else "▼"
    return f'<span class="{cls}">{arrow} {ticker}</span> <span class="chokepoint-tag">{ROLE_LABEL.get(role, role)}</span>'


st.title("📡 TERMINAL — Noticias × Cadenas de Valor")
st.caption("Tesis cualitativas de 90 días, filtradas por relevancia de cadena de suministro. No es alerta push — es una cola para revisar.")

col1, col2, col3, col4 = st.columns([1.3, 1.3, 2, 3])
with col1:
    if st.button("🔄  Buscar noticias nuevas", width="stretch"):
        with st.spinner("Bajando feeds RSS..."):
            new = fetch_new_articles()
        st.cache_data.clear()
        st.success(f"{len(new)} artículos nuevos")
with col2:
    show_reviewed = st.checkbox("Ver revisados", value=False)

matches = load_matches()
reviewed = load_reviewed()

if matches.empty:
    st.info("No hay matches todavía. Apretá 'Buscar noticias nuevas' para la primera corrida.")
    st.stop()

# --- summary metrics row ---
by_article_all = matches.groupby("article_id").first().reset_index()
n_bull = sum(1 for cs in matches["companies"] for c in cs if c["direction"] == "bullish")
n_bear = sum(1 for cs in matches["companies"] for c in cs if c["direction"] == "bearish")
n_pending = len(set(matches["article_id"]) - reviewed)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Noticias con match", len(by_article_all))
m2.metric("Pendientes de revisar", n_pending)
m3.metric("Menciones bajistas", n_bear, delta=None)
m4.metric("Menciones alcistas", n_bull, delta=None)

st.divider()

by_article = (
    matches.groupby(["article_id", "published_utc", "title", "link"])
    .apply(lambda g: list(zip(g["industry"], g["chokepoint"], g["companies"], g["thesis_90d"])), include_groups=False)
    .reset_index(name="chain_matches")
)
by_article = by_article.sort_values("published_utc", ascending=False)

if not show_reviewed:
    by_article = by_article[~by_article["article_id"].isin(reviewed)]

industries = sorted(matches["industry"].unique())
picked = st.sidebar.multiselect("Industria", industries, default=industries)
direction_filter = st.sidebar.radio("Dirección", ["Todas", "Solo bajistas", "Solo alcistas"], index=0)

by_article = by_article[by_article["chain_matches"].apply(lambda cm: any(i in picked for i, _, _, _ in cm))]

st.caption(f"**{len(by_article)}** noticias en cola" + ("" if show_reviewed else " (sin revisar)"))

for _, row in by_article.iterrows():
    with st.container(border=True):
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(f"#### [{row['title']}]({row['link']})")
            st.caption(f"🕐 {row['published_utc']}")
        with c2:
            already = row["article_id"] in reviewed
            if st.button("✓ Revisado" if not already else "↺ Reabrir", key=f"rev_{row['article_id']}"):
                if already:
                    reviewed.discard(row["article_id"])
                else:
                    reviewed.add(row["article_id"])
                save_reviewed(reviewed)
                st.rerun()

        for industry, chokepoint, companies, thesis in row["chain_matches"]:
            if industry not in picked:
                continue
            if direction_filter == "Solo bajistas" and not any(c["direction"] == "bearish" for c in companies):
                continue
            if direction_filter == "Solo alcistas" and not any(c["direction"] == "bullish" for c in companies):
                continue

            st.markdown(f'<span class="chokepoint-tag">{industry}</span> → **{chokepoint}**', unsafe_allow_html=True)

            badges = "&nbsp;&nbsp;".join(ticker_badge(c["ticker"], c["direction"], c["role"]) for c in companies)
            st.markdown(badges, unsafe_allow_html=True)

            if thesis.get("bearish"):
                st.markdown(f'<div class="thesis-box thesis-bear">📉 <b>Tesis bajista (90d):</b> {thesis["bearish"]}</div>', unsafe_allow_html=True)
            if thesis.get("bullish"):
                st.markdown(f'<div class="thesis-box thesis-bull">📈 <b>Tesis alcista (90d):</b> {thesis["bullish"]}</div>', unsafe_allow_html=True)
            st.write("")
