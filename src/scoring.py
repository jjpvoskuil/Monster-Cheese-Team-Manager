"""
Scoring engine for Monster Cheese / Maniac Football League.

Implements CBS's bucketed "yardage bonus" scoring system as captured in
config/league_settings.yaml. This is NOT a flat per-yard/per-reception
scoring system: a player's total in a stat category for a single GAME maps
to a single tier's points (e.g. 100-124 rushing yards in a game = 9 points),
not a per-yard rate.

APPROXIMATION NOTE (read this before trusting exact numbers):
Season projections (from CBS/FantasyPros/ESPN/etc.) give season TOTALS, not
a per-game distribution and not per-play distances. Two things in this
engine are therefore estimates, not exact league-rule application:

1. Yardage/reception tiers are genuinely nonlinear per game. We approximate
   a season's tiered-bonus points by computing the player's AVERAGE per-game
   production (season total / games) once, looking that average up against
   the bucket table, and multiplying by games played. This is good for
   RELATIVE ranking (better players still score higher) but will differ from
   the true season total, which depends on how production was distributed
   game to game (a boom/bust player scores differently than a steady one
   with the same season total).

2. TD "long bonus" and FG distance bonus depend on per-play distance, which
   projections don't provide. We apply the `estimation_assumptions` section
   of the config (assumed share of TDs that are "long", assumed FG distance
   distribution) to estimate expected bonus points. These are documented,
   tunable assumptions — edit config/league_settings.yaml, not this file,
   to adjust them as better data becomes available.

Everything else here (TD base points, INT, fumbles, XP, defensive per-event
stats) is a flat per-event rate straight from the league rules and is exact,
not estimated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import yaml


def load_config(path: str = "config/league_settings.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _tier_lookup(value: float, tiers: list[list[float]], extrapolate: bool = True) -> float:
    """Look up `value` against a sorted [min, max, points] tier table.

    - Below the lowest tier's min: 0 points.
    - Inside a listed tier: that tier's points.
    - In a gap between two listed tiers (the league's tables do have real
      gaps, e.g. the defensive PA table jumps 0 -> 2): 0 points, per the
      literal league rule.
    - Above the highest listed tier's max: extrapolated using the point
      delta of the last two tiers, projected forward in same-size brackets.
      This is an ESTIMATE — the league's page simply didn't render further
      tiers, but real single-game performances can exceed what's listed
      (see config metadata.notes).
    """
    if value is None or not tiers:
        return 0.0

    tiers = sorted(tiers, key=lambda t: t[0])

    if value < tiers[0][0]:
        return 0.0

    for lo, hi, pts in tiers:
        if lo <= value <= hi:
            return float(pts)

    top_lo, top_hi, top_pts = tiers[-1]
    if value > top_hi:
        if not extrapolate:
            # Caller has explicitly said not to guess past the known table
            # (see defense PA/yards-allowed callers) -> unknown, score 0
            # rather than assume the last tier's value holds forever.
            return 0.0
        if len(tiers) < 2:
            return float(top_pts)
        prev_lo, prev_hi, prev_pts = tiers[-2]
        bracket_points_delta = top_pts - prev_pts
        bracket_size = max(top_hi - top_lo + 1, 1)
        brackets_beyond = math.ceil((value - top_hi) / bracket_size)
        return float(top_pts + brackets_beyond * bracket_points_delta)

    # Falls in a gap between two tiers (only possible for tables with real
    # gaps, e.g. defensive PA/yards-allowed) -> 0 per literal league rule.
    return 0.0


@dataclass
class ScoreBreakdown:
    passing: float = 0.0
    rushing: float = 0.0
    receiving: float = 0.0
    kicking: float = 0.0
    fumbles: float = 0.0
    individual_special_teams: float = 0.0
    defense: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.passing
            + self.rushing
            + self.receiving
            + self.kicking
            + self.fumbles
            + self.individual_special_teams
            + self.defense
        )

    def as_dict(self) -> dict:
        d = {
            "passing": round(self.passing, 2),
            "rushing": round(self.rushing, 2),
            "receiving": round(self.receiving, 2),
            "kicking": round(self.kicking, 2),
            "fumbles": round(self.fumbles, 2),
            "individual_special_teams": round(self.individual_special_teams, 2),
            "defense": round(self.defense, 2),
        }
        d["total"] = round(self.total, 2)
        return d


class ScoringEngine:
    def __init__(self, config: dict):
        self.config = config
        self.scoring = config["scoring"]
        self.est = config.get("estimation_assumptions", {})
        self.games_per_season = self.est.get("games_per_season", 17)

    # ---------------------------------------------------------------
    # Single-game scoring (exact application of the tier tables)
    # ---------------------------------------------------------------

    def score_passing_game(self, yards: float = 0, td: float = 0, interceptions: float = 0,
                            two_pt: float = 0) -> float:
        s = self.scoring["passing"]
        pts = _tier_lookup(yards, s["yardage_tiers"])
        pts += td * s["td_base"]
        # long bonus applied per-TD via long_td_share at the season level
        # (see score_passing_season) — a single game's TD-long status isn't
        # knowable from totals alone, so game-level scoring here uses the
        # base rate only unless a `long_td_count` is supplied by the caller.
        pts += interceptions * s["interception_thrown"]
        pts += two_pt * s["two_point_conversion"]
        return pts

    def score_rushing_game(self, yards: float = 0, td: float = 0, two_pt: float = 0) -> float:
        s = self.scoring["rushing"]
        pts = _tier_lookup(yards, s["yardage_tiers"])
        pts += td * s["td_base"]
        pts += two_pt * s["two_point_conversion"]
        return pts

    def score_receiving_game(self, yards: float = 0, receptions: float = 0, td: float = 0,
                              two_pt: float = 0) -> float:
        s = self.scoring["receiving"]
        pts = _tier_lookup(yards, s["yardage_tiers"])
        pts += _tier_lookup(receptions, s["reception_tiers"])
        pts += td * s["td_base"]
        pts += two_pt * s["two_point_conversion"]
        return pts

    def score_fumbles(self, fumbles_lost: float = 0, off_fumble_rec_td: float = 0,
                       fumble_rec_two_pt: float = 0) -> float:
        s = self.scoring["fumbles"]
        pts = fumbles_lost * s["fumble_lost"]
        pts += off_fumble_rec_td * s["offensive_fumble_recovery_td"]
        pts += fumble_rec_two_pt * s["fumble_recovery_two_point"]
        return pts

    def score_kicking_game(self, fg_made: float = 0, xp_made: float = 0, xp_missed: float = 0,
                            fg_bonus_points: float = 0) -> float:
        """fg_bonus_points lets a caller pass an exact per-kick distance bonus
        when known (e.g. real box scores); otherwise use score_kicking_season
        which estimates it from the assumed distance distribution."""
        s = self.scoring["kicking"]
        pts = fg_made * s["fg_base"]
        pts += fg_bonus_points
        pts += xp_made * s["extra_point"]
        pts += xp_missed * s["missed_extra_point"]
        return pts

    def score_individual_return_tds(self, kick_return_td: float = 0, punt_return_td: float = 0) -> float:
        s = self.scoring["individual_special_teams"]
        return kick_return_td * s["kick_return_td"] + punt_return_td * s["punt_return_td"]

    def score_defense_game(self, sacks: float = 0, interceptions: float = 0, fumble_rec: float = 0,
                            def_td: float = 0, blocked_fg: float = 0, blocked_punt: float = 0,
                            blocked_xp: float = 0, safeties: float = 0, st_two_pt: float = 0,
                            st_one_pt_safety: float = 0, points_allowed: Optional[float] = None,
                            yards_allowed: Optional[float] = None) -> float:
        s = self.scoring["defense_special_teams"]
        pts = sacks * s["sack"]
        pts += interceptions * s["interception"]
        pts += fumble_rec * s["fumble_recovery"]
        pts += def_td * s["defensive_st_td"]
        pts += blocked_fg * s["blocked_field_goal"]
        pts += blocked_punt * s["blocked_punt"]
        pts += blocked_xp * s["blocked_extra_point"]
        pts += safeties * s["safety"]
        pts += st_two_pt * s["st_two_point_return"]
        pts += st_one_pt_safety * s["st_one_point_safety"]
        # extrapolate=False here deliberately: these two tables are the ones
        # flagged in config metadata as likely-incomplete (CBS only renders
        # 3 tiers each) and their trend is DECREASING bonus as more is
        # allowed. Linearly extrapolating that trend would eventually go
        # negative, which is a much bigger unverified leap than the offense
        # yardage tables' extrapolation (a clean, safely-increasing linear
        # pattern). Values beyond the last known tier score 0 until the
        # commissioner confirms whether further tiers exist.
        if points_allowed is not None:
            pts += _tier_lookup(points_allowed, s["points_against_tiers"], extrapolate=False)
        if yards_allowed is not None:
            pts += _tier_lookup(yards_allowed, s["yards_allowed_tiers"], extrapolate=False)
        return pts

    # ---------------------------------------------------------------
    # Season-total scoring (the approximation described in the module
    # docstring — this is what src/projections.py calls for ranking)
    # ---------------------------------------------------------------

    def _expected_fg_bonus_per_kick(self) -> float:
        dist = self.est.get("fg_distance_distribution", {})
        tiers = self.scoring["kicking"]["fg_distance_bonus_tiers"]
        # tiers: [[40,49,1],[50,59,2],[60,100,3]]
        share_keys = ["40_49", "50_59", "60_plus"]
        expected = 0.0
        for (lo, hi, bonus), key in zip(tiers, share_keys):
            expected += dist.get(key, 0.0) * bonus
        return expected

    def score_player_season(self, row: dict, games: Optional[float] = None) -> ScoreBreakdown:
        """Score a player from season-total projected stats.

        `row` keys used if present (missing keys default to 0):
          pass_yards, pass_td, pass_int, pass_two_pt,
          rush_yards, rush_td, rush_two_pt,
          rec_yards, receptions, rec_td, rec_two_pt,
          fumbles_lost, off_fumble_rec_td, fumble_rec_two_pt,
          fg_made, xp_made, xp_missed,
          kick_return_td, punt_return_td,
          def_sacks, def_int, def_fumble_rec, def_td, def_blocked_fg,
          def_blocked_punt, def_blocked_xp, def_safeties, def_st_two_pt,
          def_st_one_pt_safety, points_allowed_per_game, yards_allowed_per_game
        `games` overrides row.get('games', games_per_season default).
        """
        g = games or row.get("games") or self.games_per_season
        g = max(g, 1)

        bd = ScoreBreakdown()
        est = self.est
        pass_s = self.scoring["passing"]
        rush_s = self.scoring["rushing"]
        rec_s = self.scoring["receiving"]

        # --- Passing ---
        avg_pass_yards = row.get("pass_yards", 0) / g
        bd.passing += _tier_lookup(avg_pass_yards, pass_s["yardage_tiers"]) * g
        pass_td = row.get("pass_td", 0)
        bd.passing += pass_td * pass_s["td_base"]
        bd.passing += pass_td * est.get("long_td_share", {}).get("passing", 0) * pass_s["td_long_bonus"]["bonus"]
        bd.passing += row.get("pass_int", 0) * pass_s["interception_thrown"]
        bd.passing += row.get("pass_two_pt", 0) * pass_s["two_point_conversion"]

        # --- Rushing ---
        avg_rush_yards = row.get("rush_yards", 0) / g
        bd.rushing += _tier_lookup(avg_rush_yards, rush_s["yardage_tiers"]) * g
        rush_td = row.get("rush_td", 0)
        bd.rushing += rush_td * rush_s["td_base"]
        bd.rushing += rush_td * est.get("long_td_share", {}).get("rushing", 0) * rush_s["td_long_bonus"]["bonus"]
        bd.rushing += row.get("rush_two_pt", 0) * rush_s["two_point_conversion"]

        # --- Receiving ---
        avg_rec_yards = row.get("rec_yards", 0) / g
        avg_receptions = row.get("receptions", 0) / g
        bd.receiving += _tier_lookup(avg_rec_yards, rec_s["yardage_tiers"]) * g
        bd.receiving += _tier_lookup(avg_receptions, rec_s["reception_tiers"]) * g
        rec_td = row.get("rec_td", 0)
        bd.receiving += rec_td * rec_s["td_base"]
        bd.receiving += rec_td * est.get("long_td_share", {}).get("receiving", 0) * rec_s["td_long_bonus"]["bonus"]
        bd.receiving += row.get("rec_two_pt", 0) * rec_s["two_point_conversion"]

        # --- Fumbles ---
        bd.fumbles = self.score_fumbles(
            fumbles_lost=row.get("fumbles_lost", 0),
            off_fumble_rec_td=row.get("off_fumble_rec_td", 0),
            fumble_rec_two_pt=row.get("fumble_rec_two_pt", 0),
        )

        # --- Kicking ---
        fg_made = row.get("fg_made", 0)
        kick_s = self.scoring["kicking"]
        bd.kicking += fg_made * kick_s["fg_base"]
        bd.kicking += fg_made * self._expected_fg_bonus_per_kick()
        bd.kicking += row.get("xp_made", 0) * kick_s["extra_point"]
        bd.kicking += row.get("xp_missed", 0) * kick_s["missed_extra_point"]

        # --- Individual return TDs ---
        bd.individual_special_teams = self.score_individual_return_tds(
            kick_return_td=row.get("kick_return_td", 0),
            punt_return_td=row.get("punt_return_td", 0),
        )

        # --- Defense/Special Teams (DST) ---
        def_s = self.scoring["defense_special_teams"]
        bd.defense += row.get("def_sacks", 0) * def_s["sack"]
        bd.defense += row.get("def_int", 0) * def_s["interception"]
        bd.defense += row.get("def_fumble_rec", 0) * def_s["fumble_recovery"]
        bd.defense += row.get("def_td", 0) * def_s["defensive_st_td"]
        bd.defense += row.get("def_blocked_fg", 0) * def_s["blocked_field_goal"]
        bd.defense += row.get("def_blocked_punt", 0) * def_s["blocked_punt"]
        bd.defense += row.get("def_blocked_xp", 0) * def_s["blocked_extra_point"]
        bd.defense += row.get("def_safeties", 0) * def_s["safety"]
        bd.defense += row.get("def_st_two_pt", 0) * def_s["st_two_point_return"]
        bd.defense += row.get("def_st_one_pt_safety", 0) * def_s["st_one_point_safety"]
        pa_pg = row.get("points_allowed_per_game")
        ya_pg = row.get("yards_allowed_per_game")
        if pa_pg is not None:
            bd.defense += _tier_lookup(pa_pg, def_s["points_against_tiers"], extrapolate=False) * g
        if ya_pg is not None:
            bd.defense += _tier_lookup(ya_pg, def_s["yards_allowed_tiers"], extrapolate=False) * g

        return bd
