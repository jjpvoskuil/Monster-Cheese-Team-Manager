"""
Parse a raw-captured FantasyPoints.com "Weekly Projections" page into a
canonical per-player weekly FPTS table, plus a name-matching join helper
so those numbers can be attached to a CBS-sourced weekly matchup (see
src/data_sources/weekly_matchup.py) as a second, independent projection
source for the Weekly Matchup page's CBS/FantasyPoints toggle.

Deliberately does NOT attempt to parse FantasyPoints' underlying raw stat
categories the way src/data_sources/fantasypoints.py does for season
projections -- this page's own FPTS column (PPR scoring, their own
projection model) is what the matchup page displays directly as
"FantasyPoints says". See src/scoring.py's ScoringEngine for this app's
own tiered-scoring formula if a raw-stat-based recomputation is ever
wanted instead.

CAPTURE METHOD (2026-09-09, first pull): the "2026 NFL Weekly
Projections" page (fantasypoints.com/nfl/projections, dropdown switched
to "Weekly"), filters left at Position=ALL, Scoring=PPR -- no explicit
week selector was found; the page just shows whatever week is next/
current (confirmed Week 1 on 2026-09-09, matching CBS). Captured via
get_page_text(), NOT their own per-position "Download CSV" button (used
for the season page in fantasypoints.py) -- the weekly page's virtualized
ag-Grid table renders far more players per screen and per-player search
would mean one page load per rostered player; get_page_text() at a large
max_chars pulls the whole table in two flat blocks in one shot instead
(see LAYOUT below). Saved to
data/weekly_projections/raw/fantasypoints/{year}_week{N}_all.txt.

LAYOUT: like the season page (see fantasypoints.py's docstring for the
general quirk), get_page_text renders this ag-Grid table as two SEPARATE
flat blocks in DOM order, not interleaved rows:
  Block 1: "RANK / NAME / POSITION / NFL_TEAM" repeated once per player,
           in rank order (best projected FPTS first).
  Block 2: "OPP / FPTS" repeated once per player, in the SAME order as
           block 1 -- so player i's opponent/FPTS is pair i in block 2,
           not adjacent to that player's own name in the raw text.
This parser zips the two blocks back together by position, not by name.

NAME MATCHING: FantasyPoints abbreviates first names ("J. Allen" for
Josh Allen; DST rows are "C. Bears" for the Chicago Bears, "J. Jaguars"
for Jacksonville, etc. -- a fake initial glued onto a truncated city
name, not a real player). match_key() below builds a join key from
(first-initial, everything-after-the-first-space) for skill players, and
from nfl_team ALONE for DST rows (position == "DST") since their
"names" don't correspond to anything on the CBS side at all. Team
abbreviations also differ from CBS's in-league site (BLT vs BAL, JAX vs
JAC, ARZ vs ARI, CLV vs CLE, HST vs HOU, LA vs LAR) -- TEAM_ABBR_ALIASES
below normalizes FantasyPoints' spelling to CBS's for both the join key
and the canonical nfl_team column, so this module's output lines up with
weekly_matchup.py's without either side needing to know about the other.
"""

from __future__ import annotations

import re

TEAM_ABBR_ALIASES = {
    "BLT": "BAL", "JAX": "JAC", "ARZ": "ARI", "CLV": "CLE", "HST": "HOU",
    "LA": "LAR",
}

# FantasyPoints prints DST rows as "<fake initial>. <partial city name>"
# with no relation to a real player name -- e.g. "C. Bears", "J. Jaguars".
# Matching those to CBS's own short DST names (see team_names.py) isn't
# attempted; DST rows are matched on nfl_team alone (see match_key()).

def canonical_team_abbr(raw: str) -> str:
    raw = raw.strip().upper()
    return TEAM_ABBR_ALIASES.get(raw, raw)


_SUFFIX_RE = re.compile(r"\s+(jr|sr|ii|iii|iv|v)\.?$", re.IGNORECASE)


def match_key(name: str, position: str, nfl_team: str) -> str:
    """Join key used on BOTH sides (this module's rows and
    weekly_matchup.py's CBS rows) to line a player up across sources.
    DST: team alone (see module docstring). Skill positions: CBS gives a
    full name ("Josh Allen") and FantasyPoints an abbreviated one
    ("J. Allen") -- normalize both to (first-initial, rest-of-name) so
    "Josh Allen" and "J. Allen" produce the same key regardless of which
    form was supplied. Punctuation-insensitive (periods stripped) so
    "Amon-Ra St. Brown" (CBS) and "A. St. Brown" (FantasyPoints) match.
    Suffix-insensitive too -- CBS's Scoring Preview drops "Jr."/"II"/etc.
    from some players' names ("Chris Godwin") while FantasyPoints keeps
    them ("C. Godwin Jr."); stripped from the "rest" half on both sides
    before comparing, same suffix list as manual_import.normalize_name."""
    team = canonical_team_abbr(nfl_team)
    if position == "DST":
        return f"DST|{team}"

    cleaned = name.replace(".", "").strip()
    if " " in cleaned:
        first, rest = cleaned.split(" ", 1)
        initial = first[0]
    else:
        initial, rest = cleaned[:1], ""
    rest = _SUFFIX_RE.sub("", rest).strip()
    return f"{initial.upper()}|{rest.lower()}|{team}"


def parse_weekly_capture(text: str) -> list[dict]:
    marker = "===== BLOCK 1:"
    if marker in text:
        text = text.split(marker, 1)[1]
        text = text.split("\n", 1)[1] if "\n" in text else text  # drop the rest of that comment line

    block2_marker = "===== BLOCK 2:"
    if block2_marker not in text:
        raise ValueError("Raw capture is missing the '===== BLOCK 2:' marker")
    block1_text, block2_text = text.split(block2_marker, 1)
    block2_text = block2_text.split("\n", 1)[1] if "\n" in block2_text else block2_text

    block1_lines = [ln.strip() for ln in block1_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    block2_lines = [ln.strip() for ln in block2_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]

    if len(block1_lines) % 4 != 0:
        raise ValueError(f"Block 1 line count ({len(block1_lines)}) isn't a multiple of 4 (rank/name/pos/team)")
    if len(block2_lines) % 2 != 0:
        raise ValueError(f"Block 2 line count ({len(block2_lines)}) isn't a multiple of 2 (opp/fpts)")

    n_players = len(block1_lines) // 4
    if n_players != len(block2_lines) // 2:
        raise ValueError(
            f"Block 1 has {n_players} players but block 2 has {len(block2_lines) // 2} -- "
            "capture may be truncated or corrupted"
        )

    rows = []
    for i in range(n_players):
        rank, name, position, nfl_team = block1_lines[i * 4:i * 4 + 4]
        opp, fpts = block2_lines[i * 2:i * 2 + 2]
        rows.append({
            "rank": int(rank),
            "name": name,
            "position": position,
            "nfl_team": canonical_team_abbr(nfl_team),
            "opp": opp,
            "fpts": float(fpts),
            "match_key": match_key(name, position, nfl_team),
        })
    return rows


def load_raw_file(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return parse_weekly_capture(f.read())


def build_lookup(rows: list[dict]) -> dict[str, float]:
    """match_key -> fpts, for O(1) lookup when joining against a CBS
    weekly matchup table. Later rows win on a duplicate key (shouldn't
    happen in practice -- FantasyPoints doesn't list a player twice --
    but silently overwriting beats crashing on a data quirk)."""
    return {r["match_key"]: r["fpts"] for r in rows}
