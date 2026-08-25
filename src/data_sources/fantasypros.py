"""
FantasyPros season stat projections: parse + (attempted) live fetch.

IMPORTANT LIMITATION -- read before trusting this as a complete source:
FantasyPros' free/anonymous projections view caps every position table at
the top 10 players. The "print" view and any attempt to page/scroll past
that redirects to a sign-in wall (confirmed by navigating there directly in
a real browser session on 2026-08-25 -- see
data/projections/raw/fantasypros_2026_raw.json for the capture and note).
That means this source only ever contributes ~10 players per position to
the blend, unlike CBS (all rostered players) and FFToday (~50/position, all
32 teams for DST). It's still useful for the players it does cover (the
top of each position is exactly where 3-source agreement matters most for
early draft picks), but it is NOT a full-league replacement for CBS.

Two ways to get data into the canonical schema, mirroring fftoday.py:
  - parse_position_rows(pos, rows) parses the row-array table data already
    captured via Claude in Chrome DOM extraction (see
    data/projections/raw/fantasypros_2026_raw.json, captured_via field --
    deliberately NOT WebFetch, which fabricated wrong data for this exact
    site earlier in this project -- see SESSION_NOTES.md).
  - fetch_position(pos) attempts a live HTTP fetch + pandas.read_html
    parse. UNVERIFIED: this sandboxed Cowork session has no general
    internet egress (confirmed via curl 403s from the proxy itself, not the
    target site -- see SESSION_NOTES.md), so this path has never actually
    been exercised end-to-end. It's included because FantasyPros' table
    showed no XHR/JSON API in read_network_requests, suggesting (but not
    proving) the table markup is server-rendered and a plain requests.get()
    might work where it wouldn't for a client-rendered SPA. If this fails
    once deployed (e.g. the page turns out to be JS-rendered after all, or
    FantasyPros blocks non-browser user agents), the "Refresh from web"
    button should surface that error clearly rather than silently
    returning stale/empty data -- do not fall back to guessing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .team_names import canonical_dst_name

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

GAMES_PER_SEASON = 17  # used to convert FantasyPros' season-total DST PA/yards-allowed to per-game

# pos -> FantasyPros URL slug (used both for the raw-capture note above and
# for the live-fetch URL).
POSITION_SLUGS = {"qb": "qb", "rb": "rb", "wr": "wr", "te": "te", "k": "k", "dst": "dst"}

# pos -> ordered list of canonical column names (or None to skip -- e.g. raw
# pass attempts/completions and FPTS aren't in our canonical schema; our own
# scoring engine computes fantasy points from the raw stats instead of
# trusting a source's own point total) matching the value columns AFTER the
# "Player" column, in the exact order FantasyPros prints them. Confirmed
# against the header rows captured in fantasypros_2026_raw.json.
_COLUMN_MAP = {
    "qb": [None, None, "pass_yards", "pass_td", "pass_int", None, "rush_yards", "rush_td", "fumbles_lost", None],
    "rb": [None, "rush_yards", "rush_td", "receptions", "rec_yards", "rec_td", "fumbles_lost", None],
    "wr": ["receptions", "rec_yards", "rec_td", None, "rush_yards", "rush_td", "fumbles_lost", None],
    "te": ["receptions", "rec_yards", "rec_td", "fumbles_lost", None],
    "k": ["fg_made", None, "xp_made", None],
    # PA (index 6) and YDS AGN (index 7) are SEASON TOTALS here, unlike CBS's
    # own per-game figure -- converted to points_allowed_per_game /
    # yards_allowed_per_game below, not mapped directly.
    "dst": ["def_sacks", "def_int", "def_fumble_rec", None, "def_td", "def_safeties", None, None, None],
}


def _num(token: str) -> float:
    token = str(token).strip().replace(",", "")
    if token in ("", "-", "--"):
        return 0.0
    return float(token)


def _is_header_row(row: list[str]) -> bool:
    first = str(row[0]).strip()
    return first in ("", "Player")


def parse_position_rows(pos: str, rows: list[list[str]]) -> pd.DataFrame:
    """Parse FantasyPros' row-array table data (list of lists, one row per
    player, plus one or two leading header/category rows) for one position
    into the canonical schema. Header rows are auto-skipped: FantasyPros
    tables mark them by an empty or 'Player' first cell, never a real
    player/team name."""
    col_map = _COLUMN_MAP[pos]
    n_cols = len(col_map)
    out_rows = []

    for row in rows:
        if _is_header_row(row):
            continue
        if len(row) != n_cols + 1:  # +1 for the Player cell itself
            continue

        player_cell = str(row[0]).strip()
        if pos == "dst":
            name = canonical_dst_name(player_cell)
            team = name
        else:
            tokens = player_cell.split()
            if len(tokens) < 2:
                continue
            name, team = " ".join(tokens[:-1]), tokens[-1]

        rec = {"name": name, "position": pos.upper() if pos != "dst" else "DST", "nfl_team": team, "games": GAMES_PER_SEASON}
        pa_season = yds_season = None
        for i, canon_col in enumerate(col_map):
            raw_val = _num(row[i + 1])
            if pos == "dst" and i == 6:
                pa_season = raw_val
                continue
            if pos == "dst" and i == 7:
                yds_season = raw_val
                continue
            if canon_col is not None:
                rec[canon_col] = raw_val

        if pos == "dst":
            rec["points_allowed_per_game"] = (pa_season or 0.0) / GAMES_PER_SEASON
            rec["yards_allowed_per_game"] = (yds_season or 0.0) / GAMES_PER_SEASON

        out_rows.append(rec)

    return pd.DataFrame(out_rows)


def load_seed_json(path: str | Path = "data/projections/raw/fantasypros_2026_raw.json") -> pd.DataFrame:
    """Parse every position out of the raw JSON capture in one call."""
    data = json.loads(Path(path).read_text())
    frames = []
    for pos in POSITION_SLUGS:
        df = parse_position_rows(pos, data[pos])
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True)


def fetch_position_html(pos: str, session: "requests.Session | None" = None) -> str:
    """Live HTTP fetch of one position's FantasyPros projections page.
    UNVERIFIED from this sandbox -- see module docstring. Requires normal
    internet access; raises requests.RequestException if unreachable."""
    import requests

    slug = POSITION_SLUGS[pos]
    url = f"https://www.fantasypros.com/nfl/projections/{slug}.php?week=draft"
    sess = session or requests
    resp = sess.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return resp.text


def fetch_position(pos: str, session: "requests.Session | None" = None) -> pd.DataFrame:
    """Live fetch + parse for one position via pandas.read_html against the
    page's <table> markup. UNVERIFIED from this sandbox -- see module
    docstring. Raises ValueError if the table can't be found/parsed (e.g.
    the page turns out to require JS rendering after all)."""
    import io

    html = fetch_position_html(pos, session=session)
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError as exc:
        raise ValueError(
            f"FantasyPros {pos.upper()}: no parseable <table> found in the live page -- "
            "it may require JS rendering (use the browser-captured seed data instead via "
            "load_seed_json(), or re-capture via Claude in Chrome)"
        ) from exc

    # The projections table is the largest one on the page; smaller tables
    # are nav/ad/footer chrome.
    table = max(tables, key=len)
    rows = table.astype(str).values.tolist()
    df = parse_position_rows(pos, rows)
    if df.empty:
        raise ValueError(
            f"FantasyPros {pos.upper()}: fetched a table but found 0 parseable player rows -- "
            "site layout may have changed"
        )
    return df


def fetch_all(session: "requests.Session | None" = None) -> pd.DataFrame:
    """Live fetch + parse for every position, concatenated. UNVERIFIED from
    this sandbox -- see module docstring. Raises on the first position that
    fails; callers (the Streamlit refresh button) should catch and show a
    clear error, and should mention the top-10-per-position cap so the user
    isn't surprised by the small row count even on success."""
    import requests

    sess = session or requests.Session()
    frames = []
    for pos in POSITION_SLUGS:
        frames.append(fetch_position(pos, session=sess))
    return pd.concat(frames, ignore_index=True)
