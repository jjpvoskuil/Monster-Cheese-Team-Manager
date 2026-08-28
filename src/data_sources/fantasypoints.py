"""
FantasyPoints.com season stat projections: parse a browser-captured export.

FantasyPoints.com is a PAID, login-gated site (league manager's own
subscription) -- like CBS (see cbs.py), there is no public/unauthenticated
API or plain-HTTP path to it, so fetch_all()/fetch_position() below are
deliberately NotImplementedError, matching cbs.fetch_league_settings()'s
precedent. The only way to get data in is a live Claude session driving a
real logged-in browser (Claude in Chrome) and capturing the export, then
parsing it with load_capture_dir() below -- see pages/2_Projections.py's
"Log in & refresh" button, which opens the site for exactly this workflow.

CAPTURE METHOD (2026-08-28, first pull): the "2026 NFL Season Projections"
page (NFL -> Projections & Rankings -> Season) renders an ag-Grid table
with its OWN "Download CSV" button per position (position picked via a
dropdown -- the underlying grid actually holds all ~630 players across
every position at once, but the CSV export only ever exports whatever
position is currently selected in the dropdown, so it has to be clicked
once per position: QB/RB/WR/TE/K/DST). That per-position CSV is far more
reliable than DOM-scraping the rendered table (cf. fantasypros.py's
docstring on WebFetch fabricating data for that site) since it's the
site's own designed export feature. Saved to
data/projections/raw/fantasypoints_capture/{qb,rb,wr,te,k,dst}.csv.

CSV SHAPE -- two header rows (a sparse group-label row, e.g. "Rushing"
only over its first column, then the real column-name row), and the real
row beneath THAT repeats generic names like "YDS"/"TD" once per stat
group (e.g. RB's CSV has YDS/TD for rushing AND YDS/TD for receiving) --
pandas can't dedupe those by name alone, so POSITION_COLUMNS below maps
canonical fields to fixed COLUMN INDEXES per position (verified against
the 2026-08-28 capture; a layout change on FantasyPoints' end would need
re-verifying these offsets, not just field names).

KNOWN LIMITATIONS of this source (both confirmed against the 2026-08-28
capture -- re-check if FantasyPoints changes their export):
  - No fumbles-lost column anywhere (QB/RB/WR/TE) -- this export just
    doesn't include it, unlike CBS/FFToday. fumbles_lost is left at the
    canonical default (0) for every row from this source; blending with
    CBS/FFToday (which DO have it) still gets fumbles into the composite,
    just not from this source's own vote.
  - DST's CSV has no points-allowed or yards-allowed columns (only
    SACK/INT/FR/DTD/STD) -- a real gap since PA/yards-allowed are a big
    chunk of this league's DST scoring (see league_settings.yaml). DST
    rows from this source contribute sacks/int/fumble-rec/TD only;
    points_allowed_per_game/yards_allowed_per_game stay at the canonical
    default (0) and should keep coming from CBS/FFToday in the blend.
  - "STD" (special-teams TD) on the DST export bundles punt- and
    kick-return TDs into one number with no split -- mapped to
    kick_return_td as a best-effort single bucket (punt_return_td stays
    0) rather than dropped entirely, since the two canonical columns are
    weighted identically in scoring.py anyway (a return TD's the same 6
    points regardless of which canonical column it's filed under).
"""

from __future__ import annotations

import os

import pandas as pd

from .team_names import canonical_dst_name

# Column INDEX (0-based, after skipping the sparse group-label row) for
# each canonical field, per position -- see this module's docstring for
# why index-based beats name-based here (duplicate YDS/TD column names).
# Columns common to every position's export: 0 RANK, 1 NAME, 2 Position,
# 3 Team, 4 BYE, 5 FPTS, 6 GP, 7 FPTS/G, 8 TIER.
POSITION_COLUMNS = {
    "QB": {
        "pass_yards": 13, "pass_td": 14, "pass_int": 15,
        "rush_yards": 17, "rush_td": 18,
    },
    "RB": {
        "rush_yards": 12, "rush_td": 13,
        "receptions": 15, "rec_yards": 16, "rec_td": 17,
    },
    "WR": {
        "rush_yards": 12, "rush_td": 13,
        "receptions": 15, "rec_yards": 16, "rec_td": 17,
    },
    "TE": {
        "rush_yards": 12, "rush_td": 13,
        "receptions": 15, "rec_yards": 16, "rec_td": 17,
    },
    "K": {
        "xp_made": 10, "xp_missed": 11, "fg_made": 13,
    },
    "DST": {
        "def_sacks": 9, "def_int": 10, "def_fumble_rec": 11, "def_td": 12,
        "kick_return_td": 13,  # see docstring -- combined punt+kick return TDs
    },
}

# Filenames this module expects inside a capture directory -- matches
# exactly what the "Download CSV" button produces per position, renamed
# on save (see this module's docstring for the capture procedure).
CAPTURE_FILES = {
    "QB": "qb.csv", "RB": "rb.csv", "WR": "wr.csv",
    "TE": "te.csv", "K": "k.csv", "DST": "dst.csv",
}


def parse_position_csv(position: str, path: str) -> pd.DataFrame:
    """Parse one position's captured CSV export into the canonical schema.
    `position` picks which POSITION_COLUMNS mapping (and therefore which
    stat columns) applies -- the file itself only says "Position" per row,
    which is redundant with this but used for a sanity check."""
    raw = pd.read_csv(path, skiprows=1)  # row 0 is the sparse group-label row
    mapping = POSITION_COLUMNS[position]

    rows = []
    for _, r in raw.iterrows():
        name = str(r.iloc[1]).strip()
        if not name or name.lower() == "nan":
            continue
        row = {
            "name": canonical_dst_name(name) if position == "DST" else name,
            "position": position,
            "nfl_team": str(r.iloc[3]).strip(),
            "games": float(r.iloc[6]) if pd.notna(r.iloc[6]) else 17,
        }
        for canonical_col, idx in mapping.items():
            val = r.iloc[idx]
            row[canonical_col] = float(val) if pd.notna(val) else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def load_capture_dir(dir_path: str) -> pd.DataFrame:
    """Load and concatenate all 6 positions' captured CSVs from a capture
    directory (see CAPTURE_FILES) into one canonical-schema DataFrame,
    ready to hand to manual_import.CANONICAL_COLUMNS-shaped blending (the
    same shape load_table() produces, just built from index-mapped columns
    instead of header aliasing -- see this module's docstring for why)."""
    frames = []
    for position, filename in CAPTURE_FILES.items():
        path = os.path.join(dir_path, filename)
        if not os.path.exists(path):
            continue
        frames.append(parse_position_csv(position, path))
    if not frames:
        raise FileNotFoundError(f"No FantasyPoints capture CSVs found in {dir_path}")
    return pd.concat(frames, ignore_index=True)


def fetch_position(position: str) -> pd.DataFrame:
    raise NotImplementedError(
        "FantasyPoints.com is login-gated (paid subscription) -- there is no "
        "plain-HTTP path to it. Use the 'Log in & refresh' button on the "
        "Projections page, which opens the site for a live Claude session to "
        "capture a fresh export via load_capture_dir()."
    )


def fetch_all() -> pd.DataFrame:
    raise NotImplementedError(
        "FantasyPoints.com is login-gated (paid subscription) -- there is no "
        "plain-HTTP path to it. Use the 'Log in & refresh' button on the "
        "Projections page, which opens the site for a live Claude session to "
        "capture a fresh export via load_capture_dir()."
    )
