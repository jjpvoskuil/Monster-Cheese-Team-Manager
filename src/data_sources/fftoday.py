"""
FFToday season stat projections: fetch + parse.

Unlike CBS, FFToday does not require a login for its base projection
tables (only its custom-scoring calculator is login-gated), and it gives
full free-tier depth per position (no top-N cutoff the way FantasyPros
does -- see fantasypros.py). It's also a plain server-rendered page (no
client-side JS rendering required), which means -- unlike FantasyPros --
a plain `requests.get()` actually works here without a browser.

Two ways to get data into the canonical schema:
  - fetch_position(pos) does a live HTTP fetch + parse. This is what the
    Draft Board's "Refresh from web" button calls, and it only works from
    an environment with normal internet access (this sandboxed Cowork
    session does NOT have that -- see SESSION_NOTES.md -- so it can't be
    tested from here, but Streamlit Cloud does have normal internet
    access, so it should work there).
  - parse_position_text(pos, text) parses already-captured page text
    (e.g. from data/projections/raw/fftoday_2026_raw.txt, captured via
    Claude in Chrome's get_page_text when this session built the initial
    seed data). Both a live fetch and a browser capture end up as
    similar whitespace-delimited lines, so one parser handles both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from .team_names import canonical_dst_name

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# pos -> (PosID query param, stat column names in the order FFToday prints
# them, canonical-schema column each maps to). "name_only" positions (DEF)
# have no separate team-abbreviation column -- the full team name IS the
# player-equivalent identifier.
POSITION_CONFIG = {
    "qb": {
        "pos_id": 10,
        "has_team_code": True,
        "stat_cols": ["cmp", "att", "pass_yards", "pass_td", "pass_int", "rush_att", "rush_yards", "rush_td", "fpts"],
        "canonical": {
            "pass_yards": "pass_yards", "pass_td": "pass_td", "pass_int": "pass_int",
            "rush_yards": "rush_yards", "rush_td": "rush_td",
        },
    },
    "rb": {
        "pos_id": 20,
        "has_team_code": True,
        "stat_cols": ["rush_att", "rush_yards", "rush_td", "rec", "rec_yards", "rec_td", "fpts"],
        "canonical": {
            "rush_yards": "rush_yards", "rush_td": "rush_td",
            "rec": "receptions", "rec_yards": "rec_yards", "rec_td": "rec_td",
        },
    },
    "wr": {
        "pos_id": 30,
        "has_team_code": True,
        "stat_cols": ["rec", "rec_yards", "rec_td", "rush_att", "rush_yards", "rush_td", "fpts"],
        "canonical": {
            "rec": "receptions", "rec_yards": "rec_yards", "rec_td": "rec_td",
            "rush_yards": "rush_yards", "rush_td": "rush_td",
        },
    },
    "te": {
        "pos_id": 40,
        "has_team_code": True,
        "stat_cols": ["rec", "rec_yards", "rec_td", "fpts"],
        "canonical": {"rec": "receptions", "rec_yards": "rec_yards", "rec_td": "rec_td"},
    },
    "k": {
        "pos_id": 80,
        "has_team_code": True,
        "stat_cols": ["fgm", "fga", "fgpct", "epm", "epa", "fpts"],
        "canonical": {"fgm": "fg_made", "epm": "xp_made"},
    },
    "def": {
        "pos_id": 99,
        "has_team_code": False,
        "stat_cols": ["sack", "fr", "int", "def_td", "pa", "pa_yd_g", "ru_yd_g", "safety", "kick_td", "fpts"],
        "canonical": {
            "sack": "def_sacks", "fr": "def_fumble_rec", "int": "def_int", "def_td": "def_td",
            "safety": "def_safeties",
            # pa_yd_g / ru_yd_g are passing+rushing yards allowed PER GAME already
            # (FFToday's own column names say so) -- summed below into our single
            # yards_allowed_per_game field. "pa" here is SEASON TOTAL points
            # allowed, unlike CBS's own per-game figure -- divided by games below.
        },
    },
}

GAMES_PER_SEASON = 17  # used to convert FFToday's season-total DEF points-allowed to per-game


def _num(token: str) -> float:
    token = token.strip().rstrip("%")
    token = token.replace(",", "")
    if token in ("", "-", "--"):
        return 0.0
    return float(token)


_TEAM_CODE_RE = re.compile(r"^[A-Z][A-Za-z.]{1,4}$")


def parse_position_text(pos: str, text: str) -> pd.DataFrame:
    """Parse FFToday page text (from a live fetch's extracted text, or a
    saved get_page_text capture) for one position into the canonical
    schema. Skips header/nav/footer lines automatically -- only lines
    that match "<name...> [team] <bye#> <stat> <stat> ..." are kept."""
    cfg = POSITION_CONFIG[pos]
    stat_cols = cfg["stat_cols"]
    n_stats = len(stat_cols)
    rows = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        tokens = line.split()
        if len(tokens) < n_stats + 2:  # need at least: name-word, bye, N stats (team code optional)
            continue

        team_tok = None
        if cfg["has_team_code"]:
            # Walk backward n_stats + bye(1) + team(1) tokens to find the split.
            tail = tokens[-(n_stats + 2):]
            team_tok, bye_tok, stat_toks = tail[0], tail[1], tail[2:]
            name_toks = tokens[: -(n_stats + 2)]
            if not (_TEAM_CODE_RE.match(team_tok) and _is_int_token(bye_tok)):
                continue
        else:
            tail = tokens[-(n_stats + 1):]
            bye_tok, stat_toks = tail[0], tail[1:]
            name_toks = tokens[: -(n_stats + 1)]
            if not _is_int_token(bye_tok):
                continue

        if not name_toks:
            continue
        try:
            stat_vals = [_num(t) for t in stat_toks]
        except ValueError:
            continue
        if len(stat_vals) != n_stats:
            continue

        name = " ".join(name_toks)
        row = {"name": name, "games": GAMES_PER_SEASON, "team": team_tok}
        for col, val in zip(stat_cols, stat_vals):
            row[col] = val
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    out = pd.DataFrame({"name": df["name"], "games": df["games"]})
    for src_col, canon_col in cfg["canonical"].items():
        out[canon_col] = df[src_col]

    if pos == "def":
        out["points_allowed_per_game"] = df["pa"] / GAMES_PER_SEASON
        out["yards_allowed_per_game"] = df["pa_yd_g"] + df["ru_yd_g"]
        out["position"] = "DST"
        # FFToday prints "Houston Texans" (full City Nickname); normalize to
        # CBS's short "Houston" form so blend_projections() can join this
        # source against cbs_2026.csv on name_key -- see team_names.py.
        out["name"] = df["name"].map(canonical_dst_name)
        out["nfl_team"] = out["name"]
    else:
        out["position"] = pos.upper()
        out["nfl_team"] = df["team"]

    return out


def _is_int_token(tok: str) -> bool:
    return tok.isdigit() and len(tok) <= 2


def fetch_position_html(pos: str, session: "requests.Session | None" = None) -> str:
    """Live HTTP fetch of one position's FFToday page. Requires normal
    internet access -- will raise requests.RequestException if the
    environment can't reach fftoday.com (e.g. this sandboxed session)."""
    import requests

    cfg = POSITION_CONFIG[pos]
    url = f"https://www.fftoday.com/rankings/playerproj.php?PosID={cfg['pos_id']}&LeagueID="
    sess = session or requests
    resp = sess.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return resp.text


def _html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text("\n")


def fetch_position(pos: str, session: "requests.Session | None" = None) -> pd.DataFrame:
    """Live fetch + parse for one position. Used by the Draft Board's
    'Refresh from web' button."""
    html = fetch_position_html(pos, session=session)
    text = _html_to_text(html)
    return parse_position_text(pos, text)


def fetch_all(session: "requests.Session | None" = None) -> pd.DataFrame:
    """Live fetch + parse for every position, concatenated. Raises on the
    first position that fails to fetch or comes back empty -- callers
    (the Streamlit refresh button) should catch and show a clear error
    rather than silently writing partial/empty data."""
    import requests

    sess = session or requests.Session()
    frames = []
    for pos in POSITION_CONFIG:
        df = fetch_position(pos, session=sess)
        if df.empty:
            raise ValueError(f"FFToday {pos.upper()}: fetched page but found 0 parseable rows -- site layout may have changed")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)
