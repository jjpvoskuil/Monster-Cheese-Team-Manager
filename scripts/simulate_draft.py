"""
Monte Carlo draft simulation harness.

Simulates full `rounds x teams` snake drafts against the REAL 2026 player
board and REAL historical draft tendencies, so the pick-suggestion logic
(src/pick_suggestion.py) can be validated/tuned against something closer
to an actual draft than a single hand-checked scenario:

  - Monster Cheese always picks by calling suggest_position() +
    top_available_players() -- the exact same functions the live Draft
    Board calls -- so a simulation result is a real prediction of what
    the app would tell you to do, not a separate reimplementation.
  - Every opponent picks a POSITION sampled from real historical per-round
    draft tendencies (src/draft_tendencies.counts_by_round, averaged
    across every year in data/draft_history/draft_history.csv), then
    takes the best-available (highest VOR) player at that position. This
    is a simplification (real opponents also have roster needs/strategy),
    but it's grounded in this league's actual multi-year draft behavior
    rather than an arbitrary assumption.
  - After each simulated draft, every one of the 10 teams' OPTIMAL
    starting-lineup projected points is computed (src/lineup_value.py --
    a proper weighted-bipartite-matching solve, not draft-order greedy
    fill) and Monster Cheese is ranked among them. This is what actually
    decides fantasy standings, so it's the metric this harness optimizes
    for -- not just "did every slot get filled legally."

This formalizes/replaces the prior ad hoc `/tmp/sim/simulate*.py` scripts
from earlier sessions (cloud-workspace scratch, never committed -- lost
between sessions each time). Same core methodology, now versioned with
the rest of the app so it survives across sessions and its results are
reproducible via git history instead of session logs alone.

Usage:
    python scripts/simulate_draft.py --trials 25
    python scripts/simulate_draft.py --trials 25 --seed 42 \\
        --value-weight 0.30 --need-weight 0.45 --scarcity-weight 0.25 \\
        --label need_heavy
    python scripts/simulate_draft.py --trials 25 --out /tmp/results.json

Same `--seed` across variants reproduces the exact same opponent-behavior
random draws for every trial (Monster Cheese's own decisions are the only
thing that can differ between two runs with the same seed), which is what
makes an A/B comparison between two configs/weightings fair.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.data_sources.draft_history import load_draft_history  # noqa: E402
from src.data_sources.manual_import import load_many  # noqa: E402
from src.draft_state import DraftState  # noqa: E402
from src.draft_tendencies import counts_by_round  # noqa: E402
from src.lineup_value import LineupPlayer, optimal_lineup_points  # noqa: E402
from src.pick_suggestion import suggest_position, top_available_players  # noqa: E402
from src.projections import build_draft_board, compute_tiers  # noqa: E402
from src.roster_needs import team_position_counts, unfilled_starter_slots  # noqa: E402
from src.scoring import load_config  # noqa: E402

CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
PROJECTIONS_DIR = os.path.join(ROOT, "data", "projections")
DRAFT_HISTORY_CSV = os.path.join(ROOT, "data", "draft_history", "draft_history.csv")
DATA_EXTENSIONS = (".csv", ".tsv", ".xlsx", ".xlsm", ".xltx", ".xls")
TMP_STATE_FILE = "/tmp/simulate_draft_state.json"


def _projection_files(data_dir: str) -> list[tuple[str, str]]:
    if not os.path.isdir(data_dir):
        return []
    names = sorted(
        n for n in os.listdir(data_dir) if os.path.splitext(n)[1].lower() in DATA_EXTENSIONS
    )
    return [(os.path.join(data_dir, n), os.path.splitext(n)[0]) for n in names]


def load_player_board(config: dict) -> pd.DataFrame:
    """The same real-2026-data pipeline the Draft Board page uses:
    load every source in data/projections/, blend with equal (1.0)
    per-source weight, score, and rank. Built ONCE and reused across every
    trial/variant -- only which players are still AVAILABLE changes
    during a simulated draft, not the underlying projections."""
    sources = _projection_files(PROJECTIONS_DIR)
    if not sources:
        raise SystemExit(f"No projection files found in {PROJECTIONS_DIR}")
    raw = load_many(sources)
    board = build_draft_board(raw, config)
    return board


@dataclass
class TrialResult:
    seed: int
    my_rank: int
    my_points: float
    all_points: dict[str, float] = field(default_factory=dict)
    my_position_counts: dict[str, int] = field(default_factory=dict)
    unmet_round20_requirements: int = 0
    second_qb_round: "int | None" = None


def _opponent_pick(
    rng: np.random.Generator, available: pd.DataFrame, round_num: int, hist_counts: pd.DataFrame
) -> pd.Series:
    """Sample a position from real historical per-round tendencies
    (restricted to positions still on the board, renormalized), then take
    the best-available (highest VOR) player at that position. Falls back
    to best-available overall VOR if history has nothing useful for this
    round or every historically-favored position is already gone."""
    positions_present = available["position"].unique()
    chosen_pos = None
    if round_num in hist_counts.index:
        row = hist_counts.loc[round_num]
        weights = {pos: max(0.0, float(row.get(pos, 0.0))) for pos in positions_present}
        total = sum(weights.values())
        if total > 0:
            positions = list(weights.keys())
            probs = [weights[p] / total for p in positions]
            chosen_pos = rng.choice(positions, p=probs)

    pool = available[available["position"] == chosen_pos] if chosen_pos is not None else available
    if pool.empty:
        pool = available
    return pool.sort_values("vor", ascending=False).iloc[0]


def simulate_one_draft(
    board: pd.DataFrame,
    config: dict,
    history_df: pd.DataFrame,
    hist_counts: pd.DataFrame,
    seed: int,
    value_weight: "float | None" = None,
    need_weight: "float | None" = None,
    scarcity_weight: "float | None" = None,
) -> TrialResult:
    my_team = config["league"]["team_name"]
    draft_state = DraftState(
        teams=config["draft"]["team_order"],
        rounds=config["draft"]["rounds"],
        my_team=my_team,
        state_file=TMP_STATE_FILE,
        reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
    )
    draft_state.reset()
    rng = np.random.default_rng(seed)
    drafted_names: set[str] = set()

    while not draft_state.is_draft_complete:
        team = draft_state.on_the_clock
        available = board[~board["name"].isin(drafted_names)]
        if available.empty:
            break

        if team == my_team:
            available_tiered = compute_tiers(available)
            suggestion = suggest_position(
                available_tiered,
                draft_state,
                config,
                history=history_df,
                value_weight=value_weight,
                need_weight=need_weight,
                scarcity_weight=scarcity_weight,
            )
            pick_row = None
            if suggestion.recommended_position is not None:
                top = top_available_players(available_tiered, suggestion.recommended_position, n=1)
                if not top.empty:
                    pick_row = top.iloc[0]
            if pick_row is None:
                pick_row = available.sort_values("vor", ascending=False).iloc[0]
        else:
            rnd, _ = draft_state.round_and_slot_for_pick(draft_state.next_overall_pick)
            pick_row = _opponent_pick(rng, available, rnd, hist_counts)

        draft_state.log_pick_on_the_clock(
            pick_row["name"], position=pick_row["position"], nfl_team=pick_row["nfl_team"]
        )
        drafted_names.add(pick_row["name"])

    # --- Score every team's OPTIMAL starting lineup ---
    score_lookup = board.set_index("name")["score_total"].to_dict()
    starters = config["roster"]["starters"]
    rosters = draft_state.roster_by_team()
    all_points: dict[str, float] = {}
    for tname, picks in rosters.items():
        players = [
            LineupPlayer(name=p.player_name, position=p.position, points=score_lookup.get(p.player_name, 0.0))
            for p in picks
        ]
        all_points[tname] = optimal_lineup_points(players, starters)

    ranked_teams = sorted(all_points, key=lambda t: all_points[t], reverse=True)
    my_rank = ranked_teams.index(my_team) + 1

    my_picks = rosters[my_team]
    my_counts = team_position_counts(my_picks)

    # Round-20 draft-requirement compliance (the real league sheet's
    # by-round-20 categories -- see config's round_based_fill_targets).
    targets = config.get("estimation_assumptions", {}).get("round_based_fill_targets", [])
    round20_targets = [t for t in targets if t.get("by_round") == 20]
    unmet = unfilled_starter_slots(my_counts, round20_targets) if round20_targets else {}
    unmet_count = sum(unmet.values())

    second_qb_round = None
    qb_picks = sorted((p for p in my_picks if p.position == "QB"), key=lambda p: p.overall_pick)
    if len(qb_picks) >= 2:
        second_qb_round = qb_picks[1].round

    return TrialResult(
        seed=seed,
        my_rank=my_rank,
        my_points=all_points[my_team],
        all_points=all_points,
        my_position_counts=my_counts,
        unmet_round20_requirements=unmet_count,
        second_qb_round=second_qb_round,
    )


def run_trials(
    board: pd.DataFrame,
    config: dict,
    history_df: pd.DataFrame,
    hist_counts: pd.DataFrame,
    trials: int,
    base_seed: int,
    value_weight: "float | None",
    need_weight: "float | None",
    scarcity_weight: "float | None",
    label: str,
) -> dict:
    results: list[TrialResult] = []
    t0 = time.time()
    for i in range(trials):
        seed = base_seed + i
        r = simulate_one_draft(
            board, config, history_df, hist_counts, seed,
            value_weight=value_weight, need_weight=need_weight, scarcity_weight=scarcity_weight,
        )
        results.append(r)
        print(
            f"[{label}] trial {i + 1}/{trials} (seed {seed}): rank {r.my_rank}, "
            f"{r.my_points:.1f} pts, unmet_req20={r.unmet_round20_requirements}, "
            f"2ndQB_rd={r.second_qb_round}",
            flush=True,
        )
    elapsed = time.time() - t0

    ranks = [r.my_rank for r in results]
    points = [r.my_points for r in results]
    top3 = sum(1 for r in ranks if r <= 3)
    got_2nd_qb = [r for r in results if r.second_qb_round is not None]
    perfect_req20 = sum(1 for r in results if r.unmet_round20_requirements == 0)

    summary = {
        "label": label,
        "trials": trials,
        "base_seed": base_seed,
        "weights": {"value": value_weight, "need": need_weight, "scarcity": scarcity_weight},
        "avg_rank": sum(ranks) / len(ranks),
        "best_rank": min(ranks),
        "worst_rank": max(ranks),
        "top3_rate": top3 / trials,
        "avg_points": sum(points) / len(points),
        "second_qb_rate": len(got_2nd_qb) / trials,
        "avg_second_qb_round": (
            sum(r.second_qb_round for r in got_2nd_qb) / len(got_2nd_qb) if got_2nd_qb else None
        ),
        "round20_requirements_fully_met_rate": perfect_req20 / trials,
        "elapsed_seconds": elapsed,
        "trial_results": [
            {
                "seed": r.seed,
                "rank": r.my_rank,
                "points": r.my_points,
                "unmet_round20_requirements": r.unmet_round20_requirements,
                "second_qb_round": r.second_qb_round,
                "position_counts": r.my_position_counts,
            }
            for r in results
        ],
    }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--value-weight", type=float, default=None)
    ap.add_argument("--need-weight", type=float, default=None)
    ap.add_argument("--scarcity-weight", type=float, default=None)
    ap.add_argument("--label", type=str, default="run")
    ap.add_argument("--out", type=str, default=None, help="write full JSON results here")
    args = ap.parse_args()

    config = load_config(CONFIG_PATH)
    board = load_player_board(config)
    history_df = load_draft_history(DRAFT_HISTORY_CSV)
    hist_counts = counts_by_round(history_df) if not history_df.empty else pd.DataFrame()

    summary = run_trials(
        board, config, history_df, hist_counts,
        trials=args.trials, base_seed=args.seed,
        value_weight=args.value_weight, need_weight=args.need_weight, scarcity_weight=args.scarcity_weight,
        label=args.label,
    )

    print("\n=== Summary ===")
    print(json.dumps({k: v for k, v in summary.items() if k != "trial_results"}, indent=2))

    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\nFull results written to {args.out}")


if __name__ == "__main__":
    main()
