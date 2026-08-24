"""
Monster Cheese Team Manager — Streamlit home page.

Phase 1 (current): draft-day tooling. See pages/1_Draft_Board.py for the
actual draft board — this page is a landing/status page with links and a
quick league-settings summary.
"""

from __future__ import annotations

import datetime as dt
import os

import streamlit as st

from src.scoring import load_config

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "league_settings.yaml")

st.set_page_config(page_title="Monster Cheese Team Manager", page_icon="🏈", layout="wide")


@st.cache_resource
def get_config():
    return load_config(CONFIG_PATH)


config = get_config()
league = config["league"]
draft = config["draft"]

st.title("🏈 Monster Cheese Team Manager")
st.caption(f"{league['name']} — {league['team_name']}")

draft_dt = dt.datetime.fromisoformat(draft["date_time"])
now = dt.datetime.now(draft_dt.tzinfo)
delta = draft_dt - now

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Draft date", draft_dt.strftime("%a %b %d, %Y"))
with col2:
    st.metric("Draft time", draft_dt.strftime("%I:%M %p %Z"))
with col3:
    if delta.total_seconds() > 0:
        days = delta.days
        hours = delta.seconds // 3600
        st.metric("Time until draft", f"{days}d {hours}h")
    else:
        st.metric("Time until draft", "Draft time has passed / in progress")

st.divider()

st.subheader("League settings summary")
c1, c2 = st.columns(2)
with c1:
    st.markdown(
        f"""
- **Teams:** {league['teams']} ({league['divisions']} divisions)
- **Draft:** {draft['format']}, {draft['order_type']}, {draft['rounds']} rounds,
  {draft['seconds_per_pick']}s/pick, autopick on expired clock: {draft['autopick_on_expire']}
- **Roster:** {config['roster']['total_starters']} starters,
  bench {config['roster']['bench_min']}-{config['roster']['bench_max']},
  total {config['roster']['roster_total_min']}-{config['roster']['roster_total_max']}
"""
    )
with c2:
    starters_lines = "\n".join(
        f"- {s['count']}x **{s['slot']}** ({'/'.join(s['eligible'])})" for s in config["roster"]["starters"]
    )
    st.markdown("**Starting lineup slots:**\n" + starters_lines)

st.info(
    "Scoring uses CBS's bucketed yardage-bonus system (not flat PPR) — "
    "see `config/league_settings.yaml` for the full tier tables, captured "
    "directly from the league rules page.",
    icon="ℹ️",
)

st.divider()
st.page_link("pages/1_Draft_Board.py", label="Go to Draft Board →", icon="🏈")

with st.expander("Data & config notes"):
    st.write(config.get("metadata", {}).get("notes", ""))
    st.caption(
        f"League settings captured: {config.get('metadata', {}).get('captured_at')} "
        f"from {config.get('metadata', {}).get('source_url')}"
    )
