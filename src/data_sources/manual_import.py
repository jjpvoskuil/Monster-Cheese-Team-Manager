"""
Load season stat projections from CSV/Excel into the canonical schema used
by src/scoring.py and src/projections.py.

Different projection sources (CBS export, FantasyPros export, ESPN export,
a hand-built spreadsheet) use different column headers. This module maps a
best-effort set of common aliases onto our canonical column names rather
than requiring every input file to be pre-formatted.

Canonical columns (any column not present in the source file is filled
with 0, except name/position/nfl_team/games which are required or default
sensibly):
  name, position, nfl_team, games,
  pass_yards, pass_td, pass_int, pass_two_pt,
  rush_yards, rush_td, rush_two_pt,
  receptions, rec_yards, rec_td, rec_two_pt,
  fumbles_lost, off_fumble_rec_td, fumble_rec_two_pt,
  fg_made, xp_made, xp_missed,
  kick_return_td, punt_return_td,
  def_sacks, def_int, def_fumble_rec, def_td, def_blocked_fg,
  def_blocked_punt, def_blocked_xp, def_safeties,
  points_allowed_per_game, yards_allowed_per_game
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

CANONICAL_COLUMNS = [
    "name", "position", "nfl_team", "games",
    "pass_yards", "pass_td", "pass_int", "pass_two_pt",
    "rush_yards", "rush_td", "rush_two_pt",
    "receptions", "rec_yards", "rec_td", "rec_two_pt",
    "fumbles_lost", "off_fumble_rec_td", "fumble_rec_two_pt",
    "fg_made", "xp_made", "xp_missed",
    "kick_return_td", "punt_return_td",
    "def_sacks", "def_int", "def_fumble_rec", "def_td", "def_blocked_fg",
    "def_blocked_punt", "def_blocked_xp", "def_safeties",
    "points_allowed_per_game", "yards_allowed_per_game",
]

# alias -> canonical. Keys are lowercased/space-stripped for matching.
_ALIASES = {
    "player": "name", "player name": "name", "name": "name",
    "pos": "position", "position": "position",
    "team": "nfl_team", "nfl team": "nfl_team", "tm": "nfl_team",
    "g": "games", "gp": "games", "games": "games", "games played": "games",
    "pass yds": "pass_yards", "passing yards": "pass_yards", "py": "pass_yards",
    "paYd".lower(): "pass_yards", "pass_yards": "pass_yards",
    "pass td": "pass_td", "passing tds": "pass_td", "ptd": "pass_td", "pass_td": "pass_td",
    "int": "pass_int", "ints": "pass_int", "interceptions": "pass_int", "pass_int": "pass_int",
    "rush yds": "rush_yards", "rushing yards": "rush_yards", "ry": "rush_yards", "rush_yards": "rush_yards",
    "rush td": "rush_td", "rushing tds": "rush_td", "rtd": "rush_td", "rush_td": "rush_td",
    "rec": "receptions", "receptions": "receptions", "rec_yards".lower(): "rec_yards",
    "rec yds": "rec_yards", "receiving yards": "rec_yards", "recy": "rec_yards",
    "rec td": "rec_td", "receiving tds": "rec_td", "retd": "rec_td", "rec_td": "rec_td",
    "fum lost": "fumbles_lost", "fumbles lost": "fumbles_lost", "fl": "fumbles_lost",
    "fg": "fg_made", "fgm": "fg_made", "field goals made": "fg_made", "fg_made": "fg_made",
    "xp": "xp_made", "xpm": "xp_made", "extra points made": "xp_made", "xp_made": "xp_made",
    "xp missed": "xp_missed", "xpmiss": "xp_missed",
    "sack": "def_sacks", "sacks": "def_sacks", "def_sacks": "def_sacks",
    "dint": "def_int", "def int": "def_int", "def_int": "def_int",
    "fr": "def_fumble_rec", "fum rec": "def_fumble_rec", "def_fumble_rec": "def_fumble_rec",
    "dtd": "def_td", "def td": "def_td", "def_td": "def_td",
    "safety": "def_safeties", "safeties": "def_safeties", "def_safeties": "def_safeties",
    "pa": "points_allowed_per_game", "pts allowed": "points_allowed_per_game",
    "points allowed": "points_allowed_per_game", "points_allowed_per_game": "points_allowed_per_game",
    "ya": "yards_allowed_per_game", "yds allowed": "yards_allowed_per_game",
    "yards allowed": "yards_allowed_per_game", "yards_allowed_per_game": "yards_allowed_per_game",
}


def _normalize_header(col: str) -> str:
    key = re.sub(r"\s+", " ", str(col)).strip().lower()
    return _ALIASES.get(key, key.replace(" ", "_"))


def normalize_name(name: str) -> str:
    """Normalize a player name for cross-source joining: lowercase, strip
    punctuation and common suffixes (Jr./Sr./II/III/IV)."""
    if not isinstance(name, str):
        return ""
    n = name.lower().strip()
    n = re.sub(r"[.\']", "", n)
    n = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", n)
    n = re.sub(r"\s+", " ", n)
    return n


def load_table(path: str, source: str = "manual") -> pd.DataFrame:
    """Load a CSV or Excel file of season projections into the canonical
    schema. Unmapped source columns are dropped; missing canonical stat
    columns default to 0."""
    p = Path(path)
    if p.suffix.lower() in (".xlsx", ".xlsm", ".xltx", ".xls"):
        df = pd.read_excel(p)
    else:
        df = pd.read_csv(p)

    df = df.rename(columns={c: _normalize_header(c) for c in df.columns})

    if "name" not in df.columns:
        raise ValueError(f"{path}: could not find a player-name column among {list(df.columns)}")

    for col in CANONICAL_COLUMNS:
        if col not in df.columns:
            df[col] = 0 if col not in ("name", "position", "nfl_team", "games") else (
                "" if col != "games" else 17
            )

    df["position"] = df["position"].astype(str).str.upper().str.strip()
    df["name_key"] = df["name"].apply(normalize_name)
    df["source"] = source

    keep = ["name", "name_key", "source"] + CANONICAL_COLUMNS[1:]
    return df[keep]


def load_many(paths_and_sources: list[tuple[str, str]]) -> pd.DataFrame:
    """Load and concatenate several projection files, tagging each with its
    source name for later blending in src/projections.py."""
    frames = [load_table(path, source) for path, source in paths_and_sources]
    return pd.concat(frames, ignore_index=True)
