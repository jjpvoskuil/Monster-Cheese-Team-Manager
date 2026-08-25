"""
Canonical NFL team-name normalization for defense/special-teams (DST) rows.

Different projection sources spell out DST identity differently:
  - CBS (data/projections/cbs_2026.csv, our first/original source) uses a
    short "city" form: "Houston", "L.A. Rams", "N.Y. Giants", "Green Bay".
  - FantasyPros and FFToday both use the full "City Nickname" form:
    "Houston Texans", "Los Angeles Rams", "New York Giants".

src/projections.py's blend_projections() joins rows across sources on
(name_key, position), where name_key comes from
src/data_sources/manual_import.py's normalize_name() -- which only strips
punctuation and player-suffix tokens (Jr./Sr./III), not team nicknames. Left
alone, "Houston Texans" and "Houston" produce different name_keys and never
join, silently treating one DST as two separate "players" with partial
per-source data. canonical_dst_name() maps every known spelling to the same
CBS-style short form so all sources line up.
"""

from __future__ import annotations

# full "City Nickname" -> CBS-style short city form already baked into
# data/projections/cbs_2026.csv. Keys are the full team name as FantasyPros/
# FFToday print it; values match cbs_2026.csv exactly (verified against the
# 32 rows currently in that file).
_FULL_NAME_TO_CBS = {
    "Arizona Cardinals": "Arizona",
    "Atlanta Falcons": "Atlanta",
    "Baltimore Ravens": "Baltimore",
    "Buffalo Bills": "Buffalo",
    "Carolina Panthers": "Carolina",
    "Chicago Bears": "Chicago",
    "Cincinnati Bengals": "Cincinnati",
    "Cleveland Browns": "Cleveland",
    "Dallas Cowboys": "Dallas",
    "Denver Broncos": "Denver",
    "Detroit Lions": "Detroit",
    "Green Bay Packers": "Green Bay",
    "Houston Texans": "Houston",
    "Indianapolis Colts": "Indianapolis",
    "Jacksonville Jaguars": "Jacksonville",
    "Kansas City Chiefs": "Kansas City",
    "Las Vegas Raiders": "Las Vegas",
    "Los Angeles Chargers": "L.A. Chargers",
    "Los Angeles Rams": "L.A. Rams",
    "Miami Dolphins": "Miami",
    "Minnesota Vikings": "Minnesota",
    "New England Patriots": "New England",
    "New Orleans Saints": "New Orleans",
    "New York Giants": "N.Y. Giants",
    "New York Jets": "N.Y. Jets",
    "Philadelphia Eagles": "Philadelphia",
    "Pittsburgh Steelers": "Pittsburgh",
    "San Francisco 49ers": "San Francisco",
    "Seattle Seahawks": "Seattle",
    "Tampa Bay Buccaneers": "Tampa Bay",
    "Tennessee Titans": "Tennessee",
    "Washington Commanders": "Washington",
}

# The CBS short forms themselves map to their own name -- lets us run any
# source's value through this function unconditionally without first
# checking which convention it's already in.
_CBS_NAMES = set(_FULL_NAME_TO_CBS.values())


def canonical_dst_name(raw: str) -> str:
    """Normalize a DST team name to the short CBS-style form used across
    data/projections/*.csv. Unknown strings pass through unchanged (with a
    stripped) so a new/renamed team doesn't crash ingestion -- it just
    won't join with other sources until this table is updated."""
    name = str(raw).strip()
    if name in _CBS_NAMES:
        return name
    return _FULL_NAME_TO_CBS.get(name, name)
