"""
Development — a punch list for THIS APP'S OWN development: ideas,
tweaks, and bugs noticed while using it day to day. Input, edit, and
close items right here as the app keeps getting refined; nothing to
track in a separate doc.

Persisted to data/punch_list.json via src/punch_list.py, the same
atomic-write-then-replace JSON pattern src/draft_state.py uses for the
live draft, so it survives Streamlit's constant reruns and app restarts.
This file is intentionally NOT football-specific -- it's app upkeep,
not draft data -- but lives alongside the other pages so it's always
one click away while using the app.
"""

from __future__ import annotations

import os

import streamlit as st

from src.punch_list import VALID_PRIORITIES, PunchList

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUNCH_LIST_FILE = os.path.join(ROOT, "data", "punch_list.json")

PRIORITY_ORDER = {p: i for i, p in enumerate(VALID_PRIORITIES)}  # High < Medium < Low
PRIORITY_BADGE = {"High": "🔴 High", "Medium": "🟡 Medium", "Low": "🟢 Low"}


def get_punch_list() -> PunchList:
    # Deliberately NOT @st.cache_resource -- unlike DraftState (read via a
    # cached config + reloaded state file), this is small enough that a
    # fresh instance every rerun is simpler and guarantees no stale
    # in-memory copy after another browser tab/session writes to the file.
    return PunchList(state_file=PUNCH_LIST_FILE)


st.title("🛠️ Development")
st.caption(
    "A running punch list for this app itself — ideas, tweaks, and bugs "
    "you notice while using it. Add items below as you go; edit or close "
    "them any time. Each item gets a permanent **#number** the moment "
    "it's added — reference it (\"work on #7\") when asking Claude to "
    "pick up an item; numbers are never reused, even after deleting."
)

punch_list = get_punch_list()

# ---------------------------------------------------------------------
# Add a new item
# ---------------------------------------------------------------------
st.subheader("Add an item")
with st.form("add_punch_list_item", clear_on_submit=True):
    new_title = st.text_input(
        "Title", placeholder='e.g. "Add bye-week column to Draft Board"',
    )
    new_description = st.text_area(
        "Details (optional)", placeholder="Any context, steps to reproduce, ideas on approach, etc.",
    )
    new_priority = st.selectbox("Priority", VALID_PRIORITIES, index=1)
    submitted = st.form_submit_button("➕ Add to list")
    if submitted:
        if not new_title.strip():
            st.warning("Title is required.")
        else:
            added = punch_list.add(new_title, new_description, new_priority)
            st.success(f'Added #{added.number} — "{added.title}"')
            st.rerun()

st.divider()

# ---------------------------------------------------------------------
# Open items -- editable, sorted by priority (High first) then oldest
# first within a priority
# ---------------------------------------------------------------------
open_items = sorted(
    punch_list.open_items(),
    key=lambda i: (PRIORITY_ORDER.get(i.priority, len(VALID_PRIORITIES)), i.created_at),
)
st.subheader(f"Open ({len(open_items)})")
if not open_items:
    st.caption("Nothing open — add an item above.")
else:
    for item in open_items:
        with st.expander(f"#{item.number} · {PRIORITY_BADGE.get(item.priority, item.priority)} — {item.title}"):
            edit_title = st.text_input("Title", value=item.title, key=f"title_{item.id}")
            edit_description = st.text_area("Details", value=item.description, key=f"desc_{item.id}")
            edit_priority = st.selectbox(
                "Priority", VALID_PRIORITIES,
                index=VALID_PRIORITIES.index(item.priority) if item.priority in VALID_PRIORITIES else 1,
                key=f"prio_{item.id}",
            )
            save_col, close_col, delete_col = st.columns(3)
            if save_col.button("💾 Save changes", key=f"save_{item.id}", use_container_width=True):
                if not edit_title.strip():
                    st.warning("Title is required.")
                else:
                    punch_list.update(item.id, title=edit_title, description=edit_description, priority=edit_priority)
                    st.rerun()
            if close_col.button("✅ Close", key=f"close_{item.id}", use_container_width=True):
                punch_list.close(item.id)
                st.rerun()
            if delete_col.button("🗑️ Delete", key=f"delete_{item.id}", use_container_width=True):
                punch_list.delete(item.id)
                st.rerun()

            timestamp_note = f"Added {item.created_at[:10]}"
            if item.updated_at[:10] != item.created_at[:10]:
                timestamp_note += f" · updated {item.updated_at[:10]}"
            st.caption(timestamp_note)

st.divider()

# ---------------------------------------------------------------------
# Closed items -- collapsed by default, most recently closed first,
# with a one-click reopen
# ---------------------------------------------------------------------
closed_items = sorted(punch_list.closed_items(), key=lambda i: i.closed_at or "", reverse=True)
with st.expander(f"Closed ({len(closed_items)})", expanded=False):
    if not closed_items:
        st.caption("Nothing closed yet.")
    else:
        for item in closed_items:
            label_col, reopen_col = st.columns([6, 1])
            label_col.markdown(
                f"**#{item.number}** &nbsp; ~~**{item.title}**~~ &nbsp; "
                f"{PRIORITY_BADGE.get(item.priority, item.priority)}"
            )
            if item.description:
                label_col.caption(item.description)
            if item.closed_at:
                label_col.caption(f"Closed {item.closed_at[:10]}")
            if reopen_col.button("↩️ Reopen", key=f"reopen_{item.id}"):
                punch_list.reopen(item.id)
                st.rerun()
