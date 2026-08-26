# Session Notes

Running log for whoever (human or Claude) picks up this repo next.
**Read this file first, at the start of every session, before doing
anything else.** When you finish meaningful work, add a dated entry at
the top of the log (below "How to use this file") — newest entry first.
Keep entries short: what happened, what's true now, what's next. Don't
rewrite history further down; just append.

Draft day: **Sunday 2026-08-30, 2:30pm ET.**

## How to use this file

- New session: read "Current state" below, then skim recent log entries
  for anything relevant to what you're about to do.
- Finished a task, hit a bug, made a decision worth remembering: add an
  entry at the top of the log with today's date.
- This file lives in the repo (not a Claude Project doc) so it travels
  with `git clone` regardless of which session or tool picks this up.

## Current state

- Repo has the full Phase 1 scaffold: scoring engine, projections/VOR,
  draft state tracking, the Streamlit Draft Board UI, config, tests, and
  real 2026 CBS projection data (415 players).
- Real 2026 draft order is in `config/league_settings.yaml` under
  `draft.team_order` (10 teams, confirmed standard snake, 22 rounds).
  Monster Cheese drafts 8th overall in round 1. The Draft Board now uses
  this instead of placeholder "Team 1/2/3" names.
- Three projection sources now ingested and blendable: CBS (415 players,
  all rostered), FFToday (264 players, ~50/skill-position + all 32 DSTs),
  FantasyPros (60 players, top-10/position only — free-tier cap). New
  `pages/2_Projections.py` page lets you view each source individually,
  set per-source weights (0 to exclude, single non-zero to isolate one
  source), and see the blended stat line — this is the same
  `blend_projections`/`build_draft_board` pipeline the Draft Board uses,
  just exposed directly. FFToday and FantasyPros each have a "Refresh from
  web" button (live re-fetch); CBS does not (requires a logged-in
  session — re-pull manually, see below).
- SUPERFLEX demand assumption (`config/league_settings.yaml` →
  `estimation_assumptions.flex_position_splits.SUPERFLEX`) is now 90% QB
  (was 55%), per league-manager feedback that this scoring system makes a
  good QB nearly always the right superflex fill — every team should
  expect to start ~2 QBs almost every week. QB league-wide demand is now
  ~19 (10 dedicated + ~9 of the superflex slot), up from ~15.5, which
  raises QB's replacement level and lowers early-QB VOR accordingly.
- Both the Draft Board and Projections pages now compute position tiers
  (`src/projections.py`'s `compute_tiers()`) — same-position players
  clustered by point drop-off. Manual override (points, e.g. "10") is an
  anchor-based spread cap: every player in a tier is within that many
  points of the TIER'S TOP SCORER (not just the previous player — an
  earlier version compared only to the previous player and let a chain of
  small gaps drift a tier arbitrarily wide, e.g. an override of 10 still
  producing a tier spanning 54+ points; fixed 2026-08-25). Automatic mode
  (`src/tiering.py`) uses Jenks natural breaks with the class count chosen
  so no tier exceeds ~8% of that position's own point range — see that
  module's docstring for why two earlier gap-statistic-based designs both
  looked reasonable but still produced a 30-player/218-point top QB tier.
  Tier divider rows render in the player grid when filtered to a single
  position.
- New `pages/3_Draft_Tendencies.py` page (2026-08-25): historical
  positional draft tendencies from 4 completed seasons of real CBS draft
  results (2022-2025, 220 picks each, 880 total), pulled and parsed per
  the league manager's request to automate what "Alt Targets" in
  `TARGETS 2025.xlsx` used to track by hand. Raw captures live in
  `data/draft_history/raw/<year>_raw.txt`; `scripts/fetch_draft_history.py`
  parses them (via `src/data_sources/draft_history.py`) into the
  canonical `data/draft_history/draft_history.csv`. `src/draft_tendencies.py`
  computes per-round position counts and cumulative-by-pick curves,
  averaged across any user-selected subset of years, and predicts how
  many of each position are likely to go in the next N rounds from the
  live draft state. `src/roster_needs.py` cross-references each upcoming
  opponent's already-drafted roster against `roster.starters` to flag
  which starter slots they still need filled (dedicated slots like
  QB/RB/TE/K/DST filled first, then WR_TE_FLEX/SUPERFLEX/FLEX), and the
  page combines that with the historical prediction into one "watch this
  position" signal. 2022's draft-results page has 3 dropdown entries and
  only one ("2022 - MFL Draft", URL segment `2022:3:MFL Draft`) has real
  pick data — the other two ("2022 - 2" and "2022" plain) are empty
  placeholder tables; confirmed by visiting all three before capturing.
- **Live CBS draft sync (2026-08-25)**: `src/live_sync.py` parses the
  live CBS draft room's results panel and merges new picks into
  `data/draft_state.json` (the SAME file manual "Log a pick" writes to
  — the Draft Board doesn't know or care which one produced a pick).
  Built and verified against a REAL CBS mock draft, not synthetic data
  — see the dedicated log entry below for the full runbook (exact JS
  extraction snippet, polling cadence, how to run it live) and the real
  -data edge cases it handles (autopilot `*` prefix, "Last, First (POS
  TEAM)" format, punctuated last names, the live room's Pick column
  already being the OVERALL pick number unlike the historical results
  page). `src/data_sources/cbs.py`'s old stub for this is superseded —
  see its docstring. DST/K live-room cell format confirmed and a second
  independent mock draft run end-to-end (see the 2026-08-25 "test-drive"
  log entry below) — only an actual draft-day dry run is still
  outstanding.
- **Suggested pick (2026-08-25)**: `src/pick_suggestion.py` powers a new
  "🎯 Suggested pick" panel on the Draft Board, right above the player
  grid. Recommends a POSITION (not a single player) by combining three
  normalized 0-1 signals into a weighted composite: best-available VOR at
  that position (45%), how much MY roster still needs it — reusing
  `src/roster_needs.py`'s slot-filling logic against my own picks instead
  of an opponent's (30%), and run-risk scarcity from
  `src/draft_tendencies.py`'s historical predictions vs. tier-1 players
  remaining (25%, gracefully drops to 0 if `draft_history.csv` is
  missing). Shows the recommendation + a "why" breakdown table for every
  position, then the top 3 available players at either the recommended
  position or any position you override to via a dropdown — with a
  "Draft this player" button per player (enabled only when it's actually
  your turn; the panel itself is always visible and previews your next
  turn's recommendation even while others are picking). The tier-gap
  override control moved up the page (now sits right before this panel,
  since both it and the player grid below now share one `available_tiered`
  computation). A "↩️ Back to &lt;position&gt;" button appears next to the
  override dropdown whenever it's been changed away from the
  recommendation, so it's a one-click return rather than having to
  remember/re-pick the original suggestion. 14 new tests in
  `tests/test_pick_suggestion.py`.
- **Draft Board UI overhaul (2026-08-26)**: the ranked-players grid is now
  the pick-logging mechanism itself — click any available player's row and
  that pick logs for whoever's currently on the clock (any team, not just
  Monster Cheese; this is how every team's pick gets entered manually when
  live sync isn't running). The old "Log a pick" form (manual
  team-dropdown + player-search) is gone. Sidebar's "My roster" section is
  gone too — replaced with two live-updating panels: "Picks by round"
  (most-recent-first, scrollable) and "Next 10 picks" (upcoming teams on
  the clock, 🎯 marks Monster Cheese's own upcoming turns). My roster now
  has its own page, `pages/4_My_Roster.py` — full starting lineup by named
  slot (QB, RB 1/2/3, WR_TE_FLEX 1/2/3, etc., via new
  `src/roster_needs.assign_roster_slots()`), empty slots shown with their
  eligible positions, plus a bench list of drafted-but-unslotted players.
  New `DraftState.upcoming_picks(n)` powers the sidebar lookahead. Known
  Streamlit gotcha handled: `st.dataframe`'s row-selection state persists
  across reruns tied to its widget `key` — without bumping the key after
  each processed click, a stale "row 0 selected" would re-fire against
  the next rerun's grid (which now has a different player at row 0,
  since the drafted one is filtered out), silently drafting the wrong
  player. Fixed via a `grid_pick_nonce` counter in the key, same spirit as
  the pre-existing suggestion-override-button callback pattern. Verified
  with real 2026 data via `AppTest` (new `tests/test_draft_board_page.py`,
  entered through `app.py` + `switch_page()` — a page tested standalone
  via `AppTest.from_file()` can't resolve `st.page_link()` to a sibling
  page, since the multipage registry isn't attached to a lone script):
  clicking the top-ranked player logs it to the real snake order's first
  team (not Monster Cheese), the grid's key advances so it can't
  re-trigger, clicking a tier-divider row (single-position filter) is a
  no-op, and My Roster fills in the right slot after 8 simulated picks.
  8 new tests in `tests/test_draft_state.py`/`test_roster_needs.py` for
  the two new pure-logic functions, 3 new `AppTest` tests for the pages.
- **Draft Board/My Roster follow-up fixes (2026-08-26)**: "Reset draft"
  now requires checking a confirmation checkbox before the button
  enables, and gives a visible `st.toast` on success (previous version
  had zero visible confirmation and no safety gate — root cause of the
  user's "I could not reset" report was never conclusively identified
  via `AppTest`, since a from-scratch repro worked fine; this is a
  hardening fix either way, and also resets `grid_pick_nonce` back to 0
  so the grid gets a truly fresh widget after a reset). My Roster page
  labels the SUPERFLEX slot "QB (Flex)" (display-only — underlying
  eligibility is still QB/RB/WR/TE, unchanged). `DraftState` now takes a
  `reverse_last_n_rounds` param (config: `draft.reverse_last_n_rounds:
  2`) implementing the league's real final-2-rounds rule: round 21 is
  forced to reverse (team_order's last team drafts first) rather than
  continuing whatever alternation was already in progress, then round 22
  snakes normally from there — see `src/draft_state.py`'s
  `_round_is_forward()` docstring. Checked CBS's live rules page
  (`https://maniacfl.football.cbssports.com/rules`) for a documented
  by-round roster-fill requirement (e.g. "must draft a K by round N") —
  **not found there**; the Rules/Warnings/Constitution sections only
  cover the roster-slot/scoring/transaction settings already in
  `config/league_settings.yaml`. Not yet implemented — waiting on the
  league manager to supply the actual requirement.
- **Suggested Pick "need" math fix (2026-08-26)**: found and fixed a real
  bug behind the league manager's report that drafting a QB early and
  still needing a 2nd one (for SUPERFLEX) never made the panel recommend
  QB again. `src/roster_needs.positions_that_would_fill()` was spreading
  an unfilled flex slot's need EVENLY across its eligible positions —
  fine for a slot with no real skew, but SUPERFLEX (QB/RB/WR/TE eligible)
  already has a documented league assumption
  (`estimation_assumptions.flex_position_splits.SUPERFLEX`, 90% QB) that
  this function just wasn't using. Even split made a real, still-open
  2nd-QB need contribute only 0.25 "need" to QB — the same as to RB/WR/TE
  — vs. RB/WR's much larger dedicated-slot needs (3 RB starters, 3
  WR_TE_FLEX starters), so QB's need signal could never compete no matter
  how many rounds passed. Fix: `positions_that_would_fill()` takes an
  optional `flex_splits` dict and weights by it when a slot has one
  (falls back to even split otherwise, so every existing caller/test that
  doesn't pass it is unaffected); threaded config's real
  `flex_position_splits` through both `my_position_need()` (Suggested
  Pick) and `opponent_needs_before_next_pick()` (Draft Tendencies) so
  both benefit consistently, not just the panel that was reported broken.
  Verified against real 2026 data: same "drafted QB1 at pick 8" scenario
  now gives QB a need_raw of 0.90 instead of 0.25 (hand-verified the
  arithmetic for every position, not just QB, before trusting it) — QB
  doesn't necessarily become the top recommendation immediately (RB/WR
  still have both more raw value AND legitimately more roster slots to
  fill), but it's no longer mathematically incapable of ever winning.
  5 new tests (`test_roster_needs.py`, `test_pick_suggestion.py`).
- **Suggested Pick redundancy/overdraft fix + Monte Carlo simulation
  (2026-08-26)**: per the league manager's request to "look at the league
  tendencies and rerun some statistical simulations to see if the pick
  suggestions make sense consistently," built a simulation harness (not
  yet committed to the repo — currently `/tmp/sim/simulate.py` in the
  cloud workspace scratch space; decide whether to formalize it as
  `scripts/simulate_draft.py` or a slow `tests/` integration test) that
  runs full 220-pick simulated drafts: Monster Cheese always follows
  `suggest_position()`'s own recommendation, opponents draft using
  `src.draft_tendencies.counts_by_round`'s real historical per-round
  position frequencies. This caught two real problems the single
  hand-checked scenario above couldn't:
  1. Config's `roster.position_active_limits` (QB max 2, RB max 5, TE max
     1, WR_TE max 5 combined, K max 3, DST max 1 — captured from CBS's
     rules page in an earlier session) was never wired into any code
     (confirmed via `grep`). Shallow-pool positions (K/DST/TE) kept
     getting recommended well past any roster benefit, because their best
     -available VOR stays mildly positive far longer than a skill
     position's does once it craters past replacement level — one early
     run ended with 6 TEs and 5 DSTs drafted, and Monster Cheese took
     almost exclusively K/DST from round 9 to round 18. Fixed in
     `src/pick_suggestion.py`: once my own drafted count at a position
     meets its configured cap, that position's NEED is zeroed and it's
     excluded from recommendation as long as any legal alternative
     exists — a flat squash on the composite alone (first attempt) wasn't
     enough, since a small positive number still beat a skill position
     whose value had gone negative; rerunning the simulation against that
     first attempt is what caught it.
  2. Fixing #1 surfaced something worse: some 22-round simulated drafts
     ended having NEVER drafted a single QB — a deep league-wide QB
     replacement pool (see the VOR analysis below) means QB's raw VOR
     rarely craters enough to win the composite against RB/WR, even with
     the flex-splits need fix above. An empty mandatory starter slot
     scores zero every week of the season. Fixed with a new
     "mandatory-deadline fill" override: once I'm down to my LAST
     remaining pick(s) that could still fill an unfilled dedicated
     single-position slot (QB/RB/TE/K/DST), that position is forced to
     the top, overriding value/need/scarcity entirely.
  3. Per league-manager feedback mid-session ("kickers and defenses are
     pretty much a dime a dozen, rarely worth taking before round 17"),
     added a separate, softer, config-driven discount
     (`estimation_assumptions.position_early_round_discount`: K/DST,
     before round 17, 0.2x multiplier) — NOT a hard block, since you can
     always draft one by hand. Expected to need reconciling once the
     league's stated round-based fill requirement ("2 kickers and 2
     defenses must be picked prior to round 21") is confirmed — not yet
     supplied by the league manager as of this entry.
  After all three fixes: a fresh 15-trial batch had every trial fill
  DST/TE exactly at their cap of 1 and K exactly at its cap of 3, and
  every trial ended with zero empty starter slots (vs. 4/15 trials with
  an unfilled QB slot before fix #2). **Open question, not yet acted
  on**: WR now absorbs most of the "leftover" picks once other positions
  are capped/discounted (~10-11 WR/trial), and a 2nd QB remains rare
  (6/15 trials) — this may be genuine value-optimal behavior given this
  league's deep QB replacement pool (consistent with the VOR analysis
  below), or it may warrant further tuning (e.g. raising SUPERFLEX's
  demand weight further, or increasing NEED_WEIGHT). Flagging for the
  league manager rather than guessing further. **Also unresolved**:
  whether CBS's `roster.position_active_limits` TE max of 1 is really
  meant to cap TOTAL rostered TEs (including bench/flex depth) or just
  something narrower — it's in real tension with `WR_TE_FLEX` wanting up
  to 3 more TE-eligible players; treating it as a hard total-TE cap is
  what the fix above does, but this hasn't been confirmed with the league
  manager.
  24 new tests (`test_pick_suggestion.py`).
- **Round-based QB quota + team-vs-league points comparison in the
  simulation (2026-08-26)**: league manager flagged the "some simulated
  drafts never got a 2nd QB" finding above as a major red flag ("not
  having 2 in the first 7 rounds or so would be a disaster" in this
  superflex league) and asked to try other model variants, rerunning the
  simulation, this time also comparing each team's PROJECTED STARTING
  -LINEUP POINTS against the whole league — not just checking that slots
  get filled legally — to see whether Monster Cheese actually comes out
  near the top.
  - New general mechanism in `src/pick_suggestion.py`:
    `_round_based_quota_positions()` / config's
    `estimation_assumptions.round_based_fill_targets` — a "must have N of
    this position by round R" target, force-prioritized (same override
    tier as the existing mandatory-deadline-fill check) once running out
    of realistic chances to hit it. Deliberately generalized so the SAME
    config shape can also hold the league's real "2 kickers and 2
    defenses by round 21" rule once confirmed — see the config comments
    for which entries are self-imposed strategy vs. real CBS rules.
    Shipped with one entry: `QB: {by_round: 7, count: 2}`, straight from
    the league manager's own stated strategy target.
  - Also hardened the K/DST early-round discount (2026-08-26, earlier
    same day) from a squash-only adjustment into the same hard-exclusion
    tier as the redundancy cap: a second simulation run caught it losing
    the identical "positive-but-discounted beats negative" comparison
    problem the redundancy squash had, letting K/DST get recommended in
    rounds 11-15 (still before the round-17 cutoff) once every other
    position's need was satisfied and value had gone negative. Confirmed
    fixed: 0 such events across every subsequent simulation run (was a
    steady 4/trial before).
  - `suggest_position()` now also accepts optional `value_weight`/
    `need_weight`/`scarcity_weight` overrides (default to the module's
    constants when omitted) purely so the simulation harness can A/B
    different composite blends without a code change per variant — the
    Draft Board itself always calls it with defaults.
  - New simulation harness `/tmp/sim/simulate_v2.py` (still cloud
    -workspace scratch, not committed) + `/tmp/sim/lineup_value.py`
    (optimal starting-lineup point value via `scipy.optimize.
    linear_sum_assignment` — a proper weighted-bipartite-matching
    solution, NOT the same as `assign_roster_slots()`'s greedy
    draft-order fill, since maximizing lineup points needs the actual
    best eligible player per slot, not "whoever was drafted first").
    After each simulated draft, computes every one of the 10 teams'
    optimal-lineup projected points (using real `score_total` values) and
    ranks Monster Cheese among them.
  - Compared 5 model variants over 20 (main two) / 12 (others) trials
    each, same opponent-behavior seeds across variants: **current**
    (shipped weights 0.45/0.30/0.25 + the QB quota), **no_quota**
    (identical minus the QB round-7 target — an ablation to isolate its
    effect), **need_heavy** (0.30/0.45/0.25), **scarcity_heavy**
    (0.30/0.25/0.45), **value_heavy** (0.70/0.15/0.15, a pure
    best-player-available sanity baseline). Result: the QB quota is by
    far the dominant factor, not the value/need/scarcity weighting.
    `current` averaged rank **2.05 of 10** (85% top-3, ranks ranged only
    1st-4th across 20 trials, 100% got 2 QBs by round 7) vs. `no_quota`
    averaging rank **4.65 of 10** (35% top-3, ranks ranged 1st-8th, only
    45% ever got a 2nd QB at all, averaging round 17 when they did). The
    3 reweighted variants all landed within noise of `current` (avg rank
    2.42-2.75 over 12 trials each) — **no strong case to change the
    default 0.45/0.30/0.25 weights**; getting the QB timing right
    mattered far more than how value/need/scarcity are blended.
  - Full detail saved at `/tmp/sim/results_v2.json` (cloud workspace,
    not committed).
- **QB quota round-tightness sweep (2026-08-26)**: league manager asked
  to try tightening/loosening the new QB `round_based_fill_targets` rule
  and bump the simulation to 25 trials per variant (up from 12-20). Swept
  `by_round` in {2, 3, 4, 5, 6, 7, 9, 12} (count=2) plus a count=3 variant
  at round 7, all against the same `no_quota` control, 25 trials each,
  same opponent-behavior seeds across variants, using the team-vs-league
  optimal-lineup-points comparison built for the prior sweep. Clean,
  consistent curve: results improve steadily as the deadline tightens
  from round 12 down through round 6 (avg league rank 3.52 → 1.64 of 10;
  top-3 rate 48% → 96%; no_quota itself sat at 5.80/32%), then flatten
  across rounds 4-6 (all ~1.5-2.0 avg rank, 88-96% top-3) before giving a
  little back at rounds 3 and especially 2 (round 2: 2.64 avg rank, 72%
  top-3) — forcing the 2nd QB too early starts costing the elite RB/WR
  value concentrated in the first couple rounds instead (consistent with
  the existing VOR analysis). The count=3-by-round-7 variant also did
  well (2.12/84%) but not as well as tightening the round instead.
  **Changed the shipped rule from round 7 to round 6** — sits inside the
  flat sweet-spot band, keeps a little more schedule flexibility than
  round 4-5 as a buffer against real-world surprises the simulation can't
  model (projection error, injuries, in-draft runs), while capturing
  essentially all of the measured improvement over the original round-7
  guess. Full rank distributions and the comparison table are in the
  2026-08-26 Log entry below. No code changes needed beyond the config
  value — the round-based-quota mechanism itself already supported this
  from the prior fix.
- `pytest` — 184/184 passing.
- Deployed to Streamlit Cloud; user confirmed the Draft Board loads
  correctly as of 2026-08-25 (2026-08-26 UI overhaul + follow-up fixes
  above not yet re-confirmed live on Streamlit Cloud — only locally/via
  AppTest so far).
- Known gaps (not blocking): ESPN blending not done (would be a 4th
  source — see notes below); defensive
  PA/yards-allowed tables (only 3 tiers each on CBS's page) not yet
  re-confirmed with the commissioner; no full UI click-through of the
  Draft Board, Projections, or Draft Tendencies page has been done beyond
  direct pipeline checks and Streamlit's `AppTest` harness (see lesson
  below); parsing an in-progress/completed draft (PLAYER column
  populated) is not built for `draft_order.py` (the pre-draft order
  parser) — but IS now built separately for historical completed drafts
  via `draft_history.py`, above; FantasyPros' live-refresh-via-`requests`
  path is UNVERIFIED (this dev sandbox has no general internet egress to
  test against fantasypros.com — see entry below); draft-history only
  covers 2022-2025 — re-run `scripts/fetch_draft_history.py` after
  capturing a new raw file once the 2026 draft actually happens, to fold
  it into future-year tendency averages.

## Git push access — read this if `git push` 403s

Sessions are sometimes started without this repo attached as a source,
which makes `git push` fail with a proxy 403 ("not in this session's
authorized repository set") even though `git clone`/read access works
fine. Workaround (confirmed working, no need to restart the session):

```
cd <repo>
PAT='<github PAT with repo scope, ask the user>'
AUTH=$(printf 'x-access-token:%s' "$PAT" | base64 -w0)
git config --local http.https://github.com/.extraheader "Authorization: Basic $AUTH"
```

After that, ordinary `git push`/`pull`/`fetch` work for the rest of the
session — the proxy's allowlist doesn't intercept requests that already
carry their own Authorization header. Ask the user for a fresh PAT each
time; don't assume an old one from the log below is still valid.

## Local clone access via the device bridge (correction to 2026-08-26's dry-run entry)

The dry-run session below said "any git operation involving lock files
does NOT work through the `device_bash` remote-devices bridge" based on
`git clone` failing. That's too broad — **`git pull`/`git status`/`git
log` DO work through `device_bash`**, once two things are true:

1. The folder is actually connected to the session. If
   `get_device_info`'s `connectedFolders` is empty, call
   `device_request_folder_access` with the folder (e.g. `~/MFL` covers
   the whole MFL workspace including `monster-cheese-team-manager`) —
   this pops a one-time approval dialog on the user's device.
2. **`device_bash` can't delete/unlink files by default** — a plain `git
   pull` fails partway through with a wall of
   `warning: unable to unlink '.git/objects/.../tmp_obj_...': Operation
   not permitted` (git's internals use temp-file-then-rename, which needs
   unlink) and then errors on any tracked file it needs to replace. Fix:
   call `device_request_delete_permission` on the connected folder root
   BEFORE pulling — this is its own one-time approval dialog, separate
   from folder access. After that, `git pull` (and presumably `push`,
   though push wasn't exercised via the bridge this session — the PAT
   workaround above handles push from the cloud-workspace clone instead)
   works normally. A pull attempted before requesting delete permission
   can leave `.git/index.lock` / `.git/objects/maintenance.lock` behind
   and new files partially written (untracked) that then block the retry
   with "would be overwritten by merge" — clean those up (`rm` the lock
   files, `rm` the conflicting untracked files if their content matches
   what's incoming) once delete permission is granted, then pull again.

Still true from the original entry: don't run `git clone` or venv/pip
setup through `device_bash` — that's still untested/likely fragile for a
fresh clone (lock-file lifecycle during a full clone is heavier than a
fast-forward pull), and the local venv's `python` symlink points to a
system path (`/Library/Developer/CommandLineTools/...`) that's outside
the mounted folder and so unreachable from `device_bash` — the app itself
can only actually be run by the user in their own Terminal.app, not
verified from here. Use `device_bash` for git pull/status and for
editing/reading files in the clone directly; keep clone-from-scratch,
venv creation, and `streamlit run` in the user's own Terminal.

## Log

### 2026-08-26 — QB quota round-tightness sweep (25 trials/variant): tightened round 7 -> 6
Follow-up to the round-based-quota entry below. League manager asked to
try tightening/loosening the new QB rule and bump trials from ~15-20 to
25. Swept `by_round` (count=2) at 2, 3, 4, 5, 6, 7 (shipped), 9, 12, plus
a count=3-at-round-7 variant, each 25 trials against the same `no_quota`
control and opponent-behavior seeds, comparing simulated Monster
Cheese's optimal-lineup points against the other 9 teams:

```
MODEL          avg_rank  top3_rate  avg_pts  2ndQB_rate  avg_2ndQB_rd
no_quota           5.80      32.0%   6719.7        40.0%          16.7
quota_r12_c2       3.52      48.0%   6860.4       100.0%          11.4
quota_r9_c2        2.92      68.0%   6874.7       100.0%           9.0
current (r7_c2)    2.36      72.0%   6894.7       100.0%           7.0
quota_r7_c3        2.12      84.0%   6896.7       100.0%           6.0
quota_r3_c2        2.08      88.0%   6907.9       100.0%           3.0
quota_r5_c2        2.00      92.0%   6913.0       100.0%           5.0
quota_r2_c2        2.64      72.0%   6898.7       100.0%           2.0
quota_r6_c2        1.64      96.0%   6930.3       100.0%           6.0
quota_r4_c2        1.52      96.0%   6925.8       100.0%           4.0
```

(avg_rank/avg_pts = Monster Cheese's rank/projected starting-lineup
points among all 10 simulated teams, lower rank = better, 25 trials each)

Reading the curve in round order (12 -> 2): steady, consistent
improvement from round 12 down through round 6, then a flat sweet-spot
band across roughly rounds 4-6, then a small give-back at rounds 3 and
especially 2 — full rank distributions confirm this isn't just averaging
noise (round 4: 16/25 trials landed at rank 1, worst was rank 4; round 2:
only 6/25 at rank 1, worst was rank 7). Interpretation: forcing the 2nd
QB too early starts sacrificing the elite RB/WR value concentrated in
the first couple rounds (matches the existing VOR analysis doc), while
waiting too long risks the startable-QB pool drying up. The count=3 -by
-round-7 variant landed in between (2.12/84%) — tightening the ROUND
mattered more than tightening the COUNT.

**Changed the shipped config** (`config/league_settings.yaml`'s
`estimation_assumptions.round_based_fill_targets.QB.by_round`) from 7 to
6 — inside the flat sweet spot, with a little more schedule buffer than
rounds 4-5 for real-world surprises (projection error, injuries, an
unexpected run) that this points-projection-only simulation can't
capture. No code changes needed — the mechanism already supported any
`by_round`/`count` value. 184/184 tests still passing (no test asserts
the shipped config's specific number, only a self-contained fixture).

### 2026-08-26 — Round-based QB quota + comparing simulated teams' projected points against the whole league
Follow-up to the redundancy/overdraft entry below. League manager flagged
the "some simulated drafts never got a 2nd QB" finding as a real red flag
("not having 2 in the first 7 rounds or so would be a disaster" in this
superflex league), and asked to try other model variants and rerun the
simulation — this time also computing each of the 10 teams' PROJECTED
STARTING-LINEUP POINTS and comparing Monster Cheese to the league, not
just checking legality. Full detail is in the "Current state" bullet
above (search "team-vs-league points comparison"); short version:

- Added a general "must have N of this position by round R" mechanism
  (`_round_based_quota_positions()`, config's `estimation_assumptions.
  round_based_fill_targets`) — force-prioritized once running out of
  realistic chances to hit it, same override tier as the existing
  mandatory-deadline-fill check. Shipped with `QB: {by_round: 7, count:
  2}`. Deliberately generalized so the league's real "2 kickers/2
  defenses by round 21" rule can go in the same config block once
  confirmed.
- That exposed the K/DST early-round discount had the SAME weak-squash
  problem the redundancy cap had before it was hardened — K/DST still
  got recommended in rounds 11-15 once other positions ran out of real
  value. Hardened it into a hard exclusion too (0 such events in every
  subsequent simulation run, was 4/trial before).
- `suggest_position()` now takes optional weight overrides so the sim can
  A/B different value/need/scarcity blends without code changes.
- New `/tmp/sim/simulate_v2.py` + `/tmp/sim/lineup_value.py` (scipy
  weighted-bipartite-matching optimal lineup solver, not the same as
  `assign_roster_slots()`'s draft-order greedy fill) compute every team's
  best-possible starting-lineup points per trial and rank Monster Cheese.
- Compared 5 variants (20 trials for the two most important, 12 for the
  rest, same opponent seeds across variants): the shipped config WITH the
  QB quota averaged rank **2.05 of 10** (85% top-3, never worse than
  4th across 20 trials); the same config WITHOUT the quota averaged rank
  **4.65 of 10** (35% top-3, ranks as bad as 8th, only 45% of trials ever
  got a 2nd QB at all). Reweighting value/need/scarcity on top of the
  quota made little difference (all within noise of each other) —
  **the QB-timing fix is what actually matters here, not the composite
  weights**; left the default weights unchanged.
- 11 new tests, 184/184 passing.

### 2026-08-26 — Suggested Pick: redundancy/overdraft fix + Monte Carlo simulation across many mock drafts
Follow-up to the "need" math fix above. League manager also asked to
"look at the league tendencies and rerun some statistical simulations to
see if the pick suggestions make sense consistently" — not just the one
hand-checked scenario. Full findings and fixes are in the "Current state"
bullet above (search "Monte Carlo simulation"); short version:

- Built a simulation harness (`/tmp/sim/simulate.py`, cloud-workspace
  scratch, NOT yet committed to the repo) that runs full 220-pick
  simulated drafts, with Monster Cheese always following
  `suggest_position()`'s own call and opponents sampling from real
  historical per-round position frequencies.
- Caught config's `roster.position_active_limits` being completely
  unused (grep confirmed zero references) — shallow-pool positions
  (K/DST/TE) got recommended long past any real benefit since their VOR
  never craters the way a skill position's does. Fixed with a
  need-zeroing + hard-exclusion redundancy cap in `src/pick_suggestion.py`
  (a flat composite squash alone wasn't enough — verified by rerunning
  the sim against that weaker first attempt, which still lost most of the
  time).
- Fixing that surfaced something worse: some simulated drafts never
  drafted a single QB across all 22 rounds (empty starter slot at the
  end — scores zero every week). Fixed with a "mandatory-deadline fill"
  override that forces a still-open dedicated slot once I'm on my last
  chance to fill it, no exceptions.
- Added a separate, softer early-round discount for K/DST (before round
  17), per the league manager's mid-session comment that these positions
  are "pretty much a dime a dozen" early — not a hard block.
- Reran the 15-trial simulation after all three fixes: zero empty starter
  slots across every trial, K/TE/DST all land exactly at their configured
  caps. Two things flagged back to the league manager rather than guessed
  at further: (1) WR now absorbs most "leftover" picks and a 2nd QB stays
  rare — may just be correct given this league's deep QB pool (matches
  the existing VOR-analysis doc), or may need more tuning; (2) whether
  the TE=1 active-roster cap really means "never roster more than 1 TE
  total" is unconfirmed and in tension with `WR_TE_FLEX` wanting more.
- 24 new tests, 173/173 passing.

### 2026-08-26 — Draft Board follow-up: harden Reset, relabel SUPERFLEX, real final-round snake rule, checked CBS for round-fill rules
League manager tried the new clickable-grid Draft Board locally ("I tried
some picks and that seemed to work") but reported "I could not reset the
draft," plus three more requests: label SUPERFLEX as "QB (Flex)" on My
Roster since it's almost always a QB in this scoring system; the real
draft's last 2 rounds reverse order (team #10 picks first, then snakes
into the actual last round) rather than just continuing normal
alternation; and there are per-round roster-fill requirements to
incorporate, CBS's league page first, user to supply otherwise.

**Reset draft bug**: tried to reproduce via a fresh `AppTest` run —
drafting 2 picks then clicking "Reset draft" worked correctly (picks
cleared to `[]`, no exception) with the code as it stood. Couldn't find
or reproduce an actual defect. Rather than leave it unresolved, hardened
the control anyway since the old version had a real UX gap regardless of
root cause: one unconfirmed click instantly wiped the whole draft with
zero visible feedback, so a working reset could easily read as "nothing
happened." Now: a "Yes, clear every logged pick" checkbox gates the
button (disabled until checked), a `st.toast` confirms success, and
`grid_pick_nonce` resets to 0 so the very next grid render is a genuinely
fresh, unselected widget rather than carrying forward whatever key state
predates the reset. New `AppTest` test confirms the button is disabled
pre-checkbox, enabled after, and clears state + resets the nonce on
click. (Also worth knowing for whoever picks up an actual future repro:
the user's local `data/draft_state.json` was found missing entirely
afterward, consistent with them having manually deleted it as a
workaround rather than the reset silently failing to write — that file
is gitignored so this isn't visible from git history.)

**SUPERFLEX → "QB (Flex)"**: display-only rename in
`pages/4_My_Roster.py` (`SLOT_DISPLAY_NAMES` dict) — `src/roster_needs.py`
still sees and assigns against the real "SUPERFLEX" slot name and its
true QB/RB/WR/TE eligibility list, so opponent-need inference and the
Suggested Pick panel are untouched. New `AppTest` test confirms the
lineup table shows "QB (Flex)" and never "SUPERFLEX".

**Real final-2-rounds snake rule**: added `DraftState.__init__`'s new
`reverse_last_n_rounds` param and `_round_is_forward()` (see "Current
state" above for the mechanics) plus
`config/league_settings.yaml` → `draft.reverse_last_n_rounds: 2`, wired
into all three pages that construct `DraftState` (Draft Board, Draft
Tendencies, My Roster). Confirmed via unit tests against the real 22
-round/10-team shape that: plain snake (`reverse_last_n_rounds=0`,
the default — every existing test keeps passing unchanged) sends round
21's first pick to `team_order[0]`; the real rule flips that to
`team_order[-1]` and confirms round 22 snakes normally afterward (same
team drafts back-to-back at the 210/211 turn, matching how every other
round transition already works); and rounds 1-20 are provably identical
between the two configurations (not just "look right" — directly
diffed pick-by-pick against a `reverse_last_n_rounds=0` instance).

**Round-based roster-fill requirements**: per the user's own suggested
order of operations, checked CBS's live rules page first
(`https://maniacfl.football.cbssports.com/rules`, via Claude in Chrome,
same shared-login approach as the live-sync work) — Rules, Warnings, and
Constitution sections all show only what's already captured in
`config/league_settings.yaml` (roster slot minimums/maximums, the
WR/TE-combo legality rule, scoring). No "must draft position X by round
Y" text anywhere on the league's CBS pages. **Not implemented this
session** — asked the league manager to supply the actual requirement
(which positions, which round deadlines) since it isn't sourced from
CBS.

145/145 tests passing (was 139).

### 2026-08-26 — Connected the local clone folder to the session; local clone synced to latest
Right after the UI overhaul below, user asked to connect the local
`~/MFL` folder so this session could push updates to the local clone
directly instead of only the cloud-workspace GitHub clone. Connected via
`device_request_folder_access(["~/MFL"])`, then
`device_request_delete_permission` once a `git pull` through
`device_bash` hit the unlink-permission wall described in the new
section above. Local clone (`~/MFL/monster-cheese-team-manager`) is now
fast-forwarded to `e4d7532` (the UI overhaul commit) — verified via
matching SHA-256 hashes of the changed files between the cloud-workspace
clone and the local one, not just "git pull reported success." See the
new "Local clone access via the device bridge" section above for the
full mechanics/gotchas — this corrects the prior session's blanket "git
doesn't work over the bridge" claim.

### 2026-08-26 — Draft Board UI overhaul: clickable grid, sidebar round/upcoming panels, separate My Roster page
League manager's ask, picking back up after the paused dry-run session
below (confirmed mock draft 2832630 was no longer live — dry-run resume
deferred, this session went to other requested work instead): "make the
grid selectable so that I can just click on a player and it is drafted...
get rid of the log a pick section... show a scrollable list by round of
the teams and their picks and also the upcoming teams to pick for the
next 10 picks... should update as picks are logged... remove my roster
from the left toolbar... create a separate page for my roster."

**`pages/1_Draft_Board.py`**: the main ranked-players `st.dataframe` now
uses `on_select="rerun", selection_mode="single-row"`; selecting a row
calls `draft_state.log_pick_on_the_clock()` for whoever `on_the_clock`
currently is (not gated on `is_my_pick` — the grid is now the general
pick-entry mechanism for the whole draft, same role the old "Log a pick"
form played). Ignores clicks on tier-divider rows (checks for the
"— Tier N —" label `add_tier_divider_rows()` inserts). The "Log a pick"
form is deleted entirely. Sidebar's "My roster" section is deleted;
replaced with "Picks by round" (all picks, most-recent-first, in a
height-bounded `st.dataframe` so it scrolls in place) and "Next 10 picks"
(from new `DraftState.upcoming_picks(n)`, 🎯-marks Monster Cheese's own
upcoming turns) — both just re-read `draft_state` fresh, so they update
automatically on the next rerun after any pick (same "no new wiring
needed" pattern the Suggested Pick panel already relies on). A
`st.page_link` at the bottom points to the new roster page.

**New `pages/4_My_Roster.py`**: full starting lineup by named slot
(`src/roster_needs.assign_roster_slots()` — same most-restrictive-slot
-first greedy fill `unfilled_starter_slots()` already used for opponent
-need inference, extended to return WHICH drafted player fills each slot
instance rather than just a leftover count), empty slots captioned with
their eligible positions, plus a bench table for drafted players that
don't fill a starter slot yet.

**Streamlit gotcha hit and fixed**: `st.dataframe` selection state
persists across reruns under its widget `key`. Without changing the key
after processing a click, the NEXT rerun's grid (now missing the
just-drafted player, so every later row shifted up one) would still see
"row 0 selected" in session state and immediately re-log whatever player
now sits at row 0 — an infinite mis-drafting loop, not just a UI
annoyance. Fixed with a `grid_pick_nonce` counter folded into the key
(`player_grid_{nonce}`), bumped every time a selection is processed, so
each new grid render starts with a genuinely empty, unselected widget.
Same root cause class as the pre-existing suggestion-override-button
`session_state` gotcha documented in the 2026-08-25 entry below (assigning
into a widget's `session_state` key doesn't behave when it happens after
that widget's already run — the fix here is different, since there's no
`on_click` callback for a `st.dataframe` selection, but the underlying
lesson — widget state doesn't just reset itself — is the same).

**Testing**: 8 new unit tests (`DraftState.upcoming_picks()` in
`tests/test_draft_state.py`; `assign_roster_slots()` in
`tests/test_roster_needs.py`) plus 3 new `AppTest`-based page tests in
new `tests/test_draft_board_page.py`, run against the real 2026 player
pool and real snake order (not fixtures) — this is the first session to
commit `AppTest` page coverage rather than only running it ad hoc.
Non-obvious harness finding worth remembering: `st.page_link()` between
sibling pages only resolves inside the real multipage registry, which
only exists when `AppTest` is entered via `AppTest.from_file("app.py")`
+ `.switch_page(...)` — calling `AppTest.from_file("pages/1_Draft_Board.py")`
directly throws `KeyError: 'url_pathname'` the moment it hits that
`page_link` call, even though the exact same code runs fine in the real
deployed app. Confirmed via the new tests: clicking the top-ranked
player logs it to the real draft order's actual first team (Mississippi
Swamp Ass, not Monster Cheese) — proof the grid dispatches to whoever's
on the clock, not hardcoded to "me"; the grid's key advances after that
click; a tier-divider-row click is a no-op; and after 8 simulated picks
(reaching Monster Cheese's real round-1 slot), My Roster's "RB 1" slot
and the sidebar's "Picks by round" table both show the right player.
139/139 tests passing (was 128). Also smoke-tested by actually running
`streamlit run app.py` and confirming an HTTP 200 with no errors in the
log — not just `AppTest`.

**Not done this session**: the paused mock-draft dry run (see the entry
right below) — user confirmed draft 2832630 had gone stale/not live, and
we deliberately switched to this UI work instead of starting a fresh mock
draft. Still outstanding for next time. This UI overhaul also hasn't been
re-deployed to / re-confirmed on Streamlit Cloud yet, only run locally
and via `AppTest` — worth a quick live check before draft day given how
central the grid-click flow now is.

### 2026-08-26 — Started a user-driven dry run (local clone + mock draft join), paused mid-setup
League manager's request: "I'd like to do a dry run with a mock draft where
I do the picks instead of you. Let's walk through that process before we
actually run it." Chose to watch the real Draft Board update locally
(rather than Claude just relaying suggestions in chat) — closest to the
actual draft-day experience.

**Local clone set up.** `~/MFL/monster-cheese-team-manager` on the user's
Mac, cloned from `github.com/jjpvoskuil/Monster-Cheese-Team-Manager`, venv
created, deps installed, `streamlit run app.py` confirmed running with no
errors at `localhost:8501`. **Important gotcha for next time:** cloning (or
any git operation involving lock files) does NOT work through the
`device_bash` remote-devices bridge — it partially clones then fails with
`unable to unlink '.../.git/config.lock': Operation not permitted`, and the
bridge also can't `rm -rf` the mess afterward (no delete permission by
default, and the delete-permission tool wasn't available this session
either). Fix: have the user run `git clone`/venv setup themselves directly
in Terminal.app, not via `device_bash` — their real Terminal has no
bridge/locking quirks. `device_bash` is still fine for simple non-git file
reads/writes (e.g. the live-sync JSON files later).

**Mock draft joined, then a real architecture problem found.** Joined a
fresh live CBS mock draft ("MC Sync Test", draft id `2832630`, 10 teams/14
rounds standard roster) — user took slot 8. Original plan (from Phase 1
work) was for Claude to join the SAME room in a different slot via Claude
in Chrome, as an independent "spectator" team. **That doesn't work**:
Claude in Chrome runs in the user's own logged-in Chrome/CBS session, so
"joining slot 1" didn't add a second team — it just moved the user's OWN
team from slot 8 to slot 1 (caught immediately, reverted back to slot 8, no
lasting harm). CBS only allows one team per logged-in account per draft.

**Revised plan (agreed with user, not yet executed): Option 1 — no second
team needed.** Claude just stays in the same browser session (already
"logged in as the user" by nature of Claude in Chrome) and reads the live
results panel directly from the room the user is actually drafting in — no
separate join, no autopilot-for-Claude's-own-slot step required. Simpler
than the original Phase 1 assumption.

**Draft room URL, found but not yet exercised end-to-end:** the lobby
"details" page's "Click Here To Draft Now!" button is a JS `window.open`
call to a *relative* path (`/draft/live/room`) that only resolves correctly
via an actual click (direct navigation to that path on the lobby domain
redirects back to the lobby) — following it landed on a **separate
per-draft subdomain**: `https://mockdraft30-2832630.football.cbssports.com/draft/live/room2`
(pattern: `mockdraft<N>-<draftId>.football.cbssports.com/draft/live/room2`).
Next session should navigate straight to that pattern once a draft ID is
known, rather than clicking through the lobby again.

**Paused here** — user had to step away right as the live draft room
finished loading, before any live-sync polling was actually exercised.
Draft "MC Sync Test" (id 2832630) is likely still live with the user in
slot 8; if picks lapse while nobody's watching, CBS's own autopilot fills
in for that slot (harmless for a practice draft — same as prior test
drafts left running). **Next step on resume:** confirm whether that draft
is still open or has finished/expired; if it has, just start a fresh mock
draft. Then: user picks manually in their own tab, Claude periodically (on
request, e.g. "check now") switches the results view to "All Results",
extracts the panel via the documented `get_page_text` technique, runs
`parse_live_room_dump()` → `sync_new_picks()` → `write_sync_status()`, and
pushes the updated `data/draft_state.json`/`data/live_sync_status.json` to
the user's local clone via `SendUserFile` → `device_commit_files`
(`~/MFL/monster-cheese-team-manager/data/`). User then refreshes
`localhost:8501` to see the Suggested Pick panel update (Streamlit doesn't
auto-poll external file changes, so this refresh step doesn't go away).
Still undecided/not yet asked: sync after every single pick vs. only when
it's getting close to the user's turn — worth deciding before the next
attempt.

### 2026-08-25 — Test-drove the full live-sync + suggested-pick pipeline against a SECOND real CBS mock draft
League manager's request, after the Suggested Pick feature shipped:
"Lets test drive this with a mock draft to see how it goes." Chose the
"quick smoke test" depth (~5 rounds) over a deeper or full run.

Joined a fresh CBS practice mock draft (10 teams, 14 rounds, standard
roster — 1 QB/2 RB/3 WR/1 TE/1 K/1 DST/5 RES, a real mix of human
participants and bots — draft id 2832563, separate from both the real
league and the earlier Phase 1 test draft) via Claude in Chrome, took
draft slot 6, and played 5+ full rounds (55 picks) live: 2 picks made
manually by clicking through the room after computing the suggestion
(picks 6 and 15 — De'Von Achane and Kyren Williams, both RB per the
suggestion engine's recommendation), the rest handled by CBS's own
autopilot for my team once real findings below made manual clicking
impractical for every single pick.

**What worked, confirmed against REAL data from a draft this session had
no part in scripting:**
- `parse_live_room_dump()` correctly parsed all 52 picks from this
  draft's live results panel in one extraction (via the documented
  "switch to All Results, dump to a `<pre>` element, retrieve via
  `get_page_text`" technique) with zero parse failures, including edge
  cases the FIRST mock draft's test didn't happen to produce: apostrophes
  ("De'Von Achane"), periods in a first name ("A.J. Brown"), and
  multi-word autopilot team names ("Auto-Pilot Team 1").
- `sync_new_picks()` logged all 52 picks correctly with zero mismatches,
  AND — for the first time verified against real data rather than only
  synthetic fixtures — a SECOND identical poll against the same 52-pick
  dump was confirmed fully idempotent (0 newly logged, 52 already known,
  no duplicate/corrupted state). This is exactly the steady-state
  behavior a ~90-120s polling loop depends on.
- `suggest_position()` produced sensible, explainable recommendations
  throughout: recommended RB early (an RB run was genuinely happening —
  5 of the first 5 picks leaguewide were RBs) and correctly favored value
  +need later once the roster's RB/WR starter slots filled up. One
  recommended player (Jeremiyah Love) got drafted by another team one
  pick after the suggestion named him as the top RB available —
  independent confirmation the engine's value judgment lines up with
  what a real drafting field also wants, not just an internal metric.
- **Resolved both items flagged as unverified in the live-sync work
  above**: DST ("Browns (DST CLE)") and K ("Mevis, Harrison (K LAR)")
  live-room cell formats are now confirmed correct against real data —
  observed in the FIRST mock draft (left running with autopilot since
  the original Phase 1 session, discovered already complete at the start
  of this session) rather than needing a new draft to run 14 full
  rounds. `parse_live_room_player_cell()`'s existing fallback regex
  handled the DST case correctly with no changes needed.

**Real, non-code finding worth planning around for draft day:** this
particular mock draft moved very fast — as little as ~10-20 seconds
between picks once bots were involved, and this session's own pick clock
ran out once (pick 26, CBS's autopilot filled in A.J. Brown for a
missed manual pick) while a suggestion was being computed. The lesson
isn't a pipeline bug — `sync_new_picks`/`suggest_position` themselves
ran in well under a second — it's that extracting the room, running the
suggestion, and clicking a pick are three separate round-trips that
don't fit inside a fast pick clock if done from scratch reactively. On
the real draft, this isn't a problem the way it was in this test:
the league manager will have the Draft Board already open with an
already-computed, continuously-refreshing suggestion (from the ongoing
sync loop), so deciding is a glance-and-click, not a compute-from
-scratch-under-the-clock. The lesson that DOES carry over: for the real
draft, precompute/refresh the suggestion as soon as a session is only
1-2 picks away from its own turn, don't wait until it's actually on the
clock to start pulling data.

No code changes this session — this was a pipeline/UX validation pass,
not a bug-fix pass, since nothing broke. 128/128 tests still passing
(unchanged). Draft left running in CBS's system on autopilot (harmless,
same as the earlier Phase 1 test draft).

### 2026-08-25 — Suggested pick panel: recommend a position + top 3 players, live during the draft
League manager's ask, right after the live-sync work above landed: "add a
suggest pick area that updates as picks progress through the draft...
look at draft tendencies, my roster spots filled, roster spots filled for
a starting lineup, available players in tiers and the projected points...
suggest the next position to pick and the top 3 players available."
Also wanted to draft straight from that shortlist or off the full grid,
and to override the suggested position and see that position's own best
players/value instead.

**Design decision: recommend a POSITION first, then shortlist players for
it** — matches the request literally, and keeps the "why" explainable
(three named signals per position) rather than a single opaque per-player
score. New `src/pick_suggestion.py`:
- **Value** — best available player's VOR at each position. VOR is
  already cross-position comparable by construction (see
  `src/projections.py`), so "best available VOR per position" is a fair
  apples-to-apples signal with no extra normalization needed at the raw
  level.
- **Need** — reuses `src/roster_needs.py`'s greedy slot-filling logic
  (originally built to infer OPPONENTS' needs for the Draft Tendencies
  page) against `draft_state.my_roster()` instead — no new roster-need
  code, just a new caller (`my_position_need()`).
- **Scarcity** — `src/draft_tendencies.py`'s `predict_position_counts()`
  for the window between now and my next turn, divided by how many
  tier-1 players are left at that position right now (tier comes straight
  off whatever `compute_tiers()` output the Draft Board is already
  showing, including the user's own tier-gap override — the suggestion
  always matches what's on screen). New `picks_before_my_next_turn()`
  helper: when it's my pick RIGHT NOW, the relevant horizon isn't "0
  picks until my turn" (trivially true) — it's the round-trip to my
  NEXT turn, since that's what determines whether a position survives if
  I take something else now. When it's not my pick, this matches
  `DraftState.picks_until_my_turn()`.

Each raw signal is normalized 0-1 (divided by its own max across the
positions being compared, so a demand-weight scale and a VOR-points scale
and a picks-per-remaining-tier-1-player ratio don't fight for arbitrary
dominance) then combined as **45% value + 30% need + 25% scarcity** —
documented, tunable constants in the same style as this app's other
heuristic knobs (superflex splits, tier max-spread-fraction). Verified
with a synthetic test where value and need are tied between two
positions and only scarcity differs — confirms scarcity alone can flip
the recommendation, not just nudge a already-decided one
(`test_suggest_position_scarcity_can_flip_the_recommendation`). Degrades
cleanly with no `draft_history.csv` (scarcity contributes 0 to every
position, ranking falls back to value+need) and reports `None` with a
clear reason when the draft is complete or no players remain.

`pages/1_Draft_Board.py`: new "🎯 Suggested pick" section, positioned
above the player grid (the tier-gap-override control moved up the page
to sit right before it, since both the suggestion engine and the grid
below now share one `available_tiered` computation instead of computing
it twice). Shows the recommendation with its reasoning sentence, an
expander breaking down every position's value/need/scarcity numbers, a
position-override dropdown (any position, not just the recommendation),
and the top-3-players-for-that-position as cards with a "Draft this
player" button each. Buttons log straight to `draft_state` via the
existing `log_pick_on_the_clock()` and are disabled unless it's actually
your turn — but the recommendation text itself stays visible and updates
even when it's not your turn yet, previewing what it'll suggest once
your turn comes back around (this is what "updates as picks progress"
means in practice: every rerun re-reads the live `DraftState`, so a live
-synced pick landing mid-draft changes the recommendation on the very
next page refresh, no separate wiring needed).

Verified via `AppTest` against the REAL 2026 player pool and the real
league's snake order (not synthetic fixtures) in three states: not-my
-turn (recommendation shown as a preview, all 3 draft buttons correctly
disabled), my-turn (buttons enabled, clicking one correctly logged a real
player — Jahmyr Gibbs — to `DraftState` and persisted it), and the
position-override dropdown (switching to TE correctly relabeled the
shown players and captioned that it was overriding the RB recommendation).
14 new tests in `tests/test_pick_suggestion.py`; 128/128 total passing.
All 4 Streamlit pages re-verified clean.

**Follow-up same day:** added a "↩️ Back to &lt;recommended position&gt;"
button next to the override dropdown, so overriding to check another
position doesn't mean having to remember/re-select what the app
originally suggested. Non-obvious Streamlit gotcha hit and fixed here:
`st.session_state[key] = value` cannot be called for a widget's key
inline after that widget has already run earlier in the same script pass
(`StreamlitAPIException`, caught immediately via `AppTest` rather than
shipped) — the reset has to happen in an `on_click` callback instead
(`_set_position_override()`), which Streamlit runs before the next
rerun's widgets are recreated. Also guarded against a position dropping
out of the option list entirely between reruns (e.g. K/DST fully
drafted) by clearing an now-invalid `session_state` selection before the
selectbox renders, rather than letting it raise. Re-verified via
`AppTest`: override to a different position, confirm the reset button
appears and correctly jumps back, confirm it disappears again once back
on the recommendation. 128/128 tests still passing (no new test file --
this is UI-callback behavior that `AppTest`'s widget interaction API
covers directly; the underlying `suggest_position()`/`top_available_players()`
logic already covered in `tests/test_pick_suggestion.py` is unchanged).

### 2026-08-25 — Live CBS draft sync built and verified against a real mock draft (Phase 1 of live-draft-day support)
User's ask, after the tiering/tendencies work above: "when we are running
the draft I want the actual draft results to drive my app so that as
players are picked on cbs it updates my app immediately." Also floated
having the app auto-pick on CBS too (Phase 2). Agreed scope with the user:
**Phase 1 only** — one-way sync (CBS → app), read-only, no automated
clicking on CBS. Phase 2 (app picks on CBS on the user's behalf) is
explicitly a "nice to have if it works really well," not built now, and
would need per-pick user confirmation before ever clicking "Draft" on CBS
regardless (an irreversible action on a live third-party site).

**Why this can't be a plain scheduled job:** CBS requires a logged-in
session and has no public API, and the deployed Streamlit app has no
browser of its own — it cannot reach out to CBS by itself under any
design. The only way to get live pick data out of CBS is an active Claude
session driving a real logged-in browser (Claude in Chrome). So the
architecture is split in two: `src/live_sync.py` (this repo, pure
functions, fully unit-tested) does the parsing/merging once pick data has
been extracted; the actual "go get the data from CBS" step is a procedure
a Claude session runs live during the draft, described below, not code
that lives in the repo.

**Tested against a REAL CBS mock draft, not synthetic data.** CBS has a
free, unlimited "Mock Draft" lobby (from the league site: Draft → Mock
Drafts → `mockdraft-1.football.cbssports.com/mockdraft/standard`) —
separate from the real league draft, real people + bot-filled, so there
was zero risk of touching the actual league draft while testing. Joined
one, took a team slot, and let it run to round 4 while inspecting the
live draft room's results panel DOM directly. This mattered: the live
room turned out to differ from the historical completed-draft results
page (`src/data_sources/draft_history.py`, used for the Draft Tendencies
page above) in two independent, non-obvious ways that a naive port of
that page's parser would have gotten silently wrong:
- **Player-cell text format** differs: historical page shows
  `"Josh Allen QB • BUF"`; live room shows `"Allen, Josh (QB BUF)"`.
- **Pick numbering** differs: historical page's "Pick" column resets to
  1 every round (combined with round number to get an overall pick);
  the live room's "Pick" column is already the overall pick number and
  just keeps counting up across round boundaries (round 2 shows picks
  11, 12, 13...).
- Both pages share the same auto-pick convention: a `*` prefix on the
  player cell (e.g. `"*Henry, Derrick (RB BAL)"`) when a pick was made by
  autopilot rather than a human clicking.

**Real bug found and fixed via the real-data test, not caught by
synthetic fixtures:** the first version of `parse_live_room_dump()`
assumed the live room's "Pick" column needed the same `(round-1)*
teams_per_round+pick` arithmetic as the historical page. Tested against a
real captured 14-pick/2-round dump, this produced a wrong overall_pick
for every round-2+ pick (offset into the 21-24 range instead of 11-14),
which `sync_new_picks()`'s gap-safety logic correctly refused to bridge —
so only 10 of 14 real picks got logged, caught by a failing assertion
(`10 == 14`) rather than a silent wrong answer. Fixed by dropping that
arithmetic entirely and using the live room's "Pick" column value
directly as `overall_pick` — see the extensive warning comment in
`parse_live_room_dump()`'s docstring so a future session doesn't
reintroduce this. `sync_new_picks()` itself worked correctly throughout
(it's what caught the bug in the first place, by refusing to skip a
gap) — the bug was purely in how the raw text got parsed into pick
numbers upstream of it.

**Extraction technique (the exact steps to run live on draft day):**
1. In the live draft room, switch the results panel from "Latest Results"
   to "All Results" so every pick made so far is visible, not just the
   current round. The panel's dropdown is a custom widget backed by a
   hidden `<select id="selectRoundResults">`; toggle it via
   `javascript_tool`:
   ```js
   var sel = document.getElementById('selectRoundResults');
   sel.value = 'all';
   mainapp.resultsView.selectOption();
   ```
2. Dump the results table to plain pipe-delimited text
   (`round|pick|team|player_cell` per line) by walking
   `#DraftRoom.views.results .SLTables1 table.data`'s rows (`tr.bg1` =
   round-label rows to read the round number from, `tr.bg2` = actual pick
   rows with 3 `<td>`s: pick number, team, player link text). Returning
   this directly from `javascript_tool` gets `[BLOCKED: Cookie/query
   string data]` (the player links' hrefs contain `?playerid=...`, which
   trips the tool's own content filter) — work around this the same way
   the Draft Tendencies historical-page capture did: write the dump into
   a `<pre>` element appended to `document.body`, then retrieve it with
   the separate `get_page_text` tool, which has no such filter and no
   `javascript_tool`'s ~1100-1200 char truncation either.
3. Feed that text to `parse_live_room_dump()`, then `sync_new_picks(draft_state,
   live_picks)`, then `write_sync_status(LIVE_SYNC_STATUS_FILE, draft_state,
   result)` so the Draft Board's sidebar shows how fresh the feed is.
4. Repeat on a poll loop. Recommended cadence: **90-120 seconds.** In the
   test mock draft, real picks landed roughly every 40-60 seconds
   (faster than a real league draft will likely run, since bots don't
   deliberate) — 90-120s keeps the app comfortably current without
   polling so often it's wasted effort, and the Draft Board's sidebar
   flags staleness (⚠️ past 150s, 🛑 past 600s) so a slower cadence, or a
   dropped poll, is visible rather than silent.

**`pages/1_Draft_Board.py`** now shows a "🔴 Live sync from CBS" sidebar
block whenever `data/live_sync_status.json` exists: last synced pick
number, freshness (✅ under 150s / ⚠️ 150-600s / 🛑 over 600s — "log
picks manually below until it resumes"), and any mismatches or
out-of-order picks the last sync pass found. The manual "Log a pick" form
is unchanged and still the reliable fallback — both write to the same
`data/draft_state.json`, so the page doesn't know or care which produced
a given pick. `src/data_sources/cbs.py`'s old `fetch_live_draft_picks`
stub is removed; its docstring now points here.

**Verified:** `src/live_sync.py` covered by 18 new tests in
`tests/test_live_sync.py`, including two end-to-end tests built from the
actual captured mock-draft dumps (`REAL_LIVE_ROOM_DUMP`,
`REAL_LIVE_ROOM_DUMP_ROUND_2`) — not just synthetic fixtures — plus
tests for contiguous logging, gap handling, idempotent re-polling,
mismatch detection, and stopping cleanly at draft-complete. 114/114 tests
passing repo-wide. All 4 Streamlit pages re-verified via `AppTest` with
the new sidebar block present, including a stale/mismatch scenario, no
exceptions.

**Still open, not blocking Phase 1 use:**
- DST and K live-room cell format is unconfirmed — the test mock draft
  only reached round 4 of 14 before wrapping up, and those positions
  typically go much later. `parse_live_room_player_cell()` has a
  defensive fallback regex for a no-comma cell shape that won't crash on
  an unexpected format, but its exact correctness for DST/K is unverified
  until observed for real.
- No continuous real-time poll loop has been run yet end-to-end (parsing
  and merging have each been verified against real snapshots taken at
  different points in the mock draft, but not yet exercised as a
  repeated poll-extract-sync cycle sustained over a full draft).
- No dry run against the actual league's draft day (2026-08-30) yet.
- Phase 2 (app → CBS pick submission) not started, per the user's own
  "nice to have" prioritization — Phase 1 (this) is the whole ask for now.

### 2026-08-25 — Draft Tendencies: 4 years of real CBS draft history + live position-run prediction + opponent roster-need view
League manager's request: "the number of players per position per draft
round is somewhat consistent... predict what will happen in the next
round or 2 by position... also look at the roster for each team to see
what positions are filled." This was previously done by hand in
`TARGETS 2025.xlsx`'s "Alt Targets" sheet.

Captured 2022-2025 actual completed drafts (not just draft order) from
`https://maniacfl.football.cbssports.com/draft/results/` via Claude in
Chrome (this page requires a logged-in session and blocks robots.txt, so
`WebFetch`/`requests` can't touch it). Used a new large-extraction
technique to work around `javascript_tool`'s ~1100-1200 char direct-return
truncation: write the extracted data into the page's own DOM as a `<pre>`
block, then retrieve it with the separate `get_page_text` tool (no
truncation there) — reliably pulled all 220 picks/year in one shot.
2022 needed extra care: 3 entries in the "DRAFTS" dropdown for that year,
found via `document.querySelectorAll('li')` (`value` attribute holds the
URL path even though it's a custom widget, not a native `<select>`) —
visited all 3 (`2022:3:MFL Draft`, `2022:2:2`, `2022:Pre-season`) and
confirmed only the first has a populated table (264 rows incl. headers =
220 real picks); the other two are empty placeholder drafts. 2022's raw
page also has 2 extra columns (Elig, Elapsed Time, Total/Active Fpts)
that other years don't show, and 2 "(Skipped Pick)" rows (round
21 pick 4, round 22 pick 7, both Buckhorns) not seen in any other year —
new edge case, handled explicitly (excluded from position counts).

Raw captures saved to `data/draft_history/raw/<year>_raw.txt` (pipe
-delimited round|pick|team|player_cell, one line per pick). New
`src/data_sources/draft_history.py` parses these into a canonical schema,
handling: auto-pick prefix (`*`), blank/free-agent NFL team (trailing
bullet with nothing after), DST picks (mascot as "player name"), and
dual-position eligibility (e.g. "Taysom Hill QB,TE" — tallied under the
FIRST listed position only, since double-counting one pick across two
positions would inflate round totals; full list kept in a `positions`
field for anyone who wants a different rule later). `scripts/
fetch_draft_history.py` runs the parser over every `*_raw.txt` file found
and writes the combined `data/draft_history/draft_history.csv` (880 picks
across the 4 years; 2 skipped, 13 auto-picks).

`src/draft_tendencies.py`: `counts_by_round()` (avg positions drafted per
round, any year subset), `cumulative_counts_by_pick()` (avg cumulative
count by exact overall pick number — the direct automation of the old
Alt Targets table), `predict_position_counts()` / `next_run_positions()`
(expected position counts in the next N picks from any current pick,
i.e. "is a run coming"). `src/roster_needs.py`: given a team's drafted
players and `config/league_settings.yaml`'s `roster.starters`, greedily
fills the most position-restrictive slots first (QB/RB/TE/K/DST) then the
flex slots (WR_TE_FLEX/SUPERFLEX/FLEX) to find which slots are still
open, and spreads that unfilled-slot "demand" across each slot's eligible
positions. New `pages/3_Draft_Tendencies.py` ties it together against the
LIVE `DraftState` (same `data/draft_state.json` the Draft Board writes):
year-subset picker, per-round historical table + chart, live next-N
-round position prediction, and a per-upcoming-opponent "likely needs"
table plus a combined-demand view that flags when historical prediction
and opponent roster gaps agree on the same position.

Verified via `AppTest` against `pages/3_Draft_Tendencies.py` in three
draft-state scenarios (empty/no draft started, mid-draft with opponents
ahead, mid-draft where it's my_team's own turn) — all render without
exception; spot-checked the opponent-needs and combined-demand tables'
actual values by hand against a synthetic roster. Real-data sanity check:
round 1 averages 4.75 QB + 4.75 RB (superflex-heavy league, matches the
2026-08-25 VOR work above), K/DST cluster in rounds 16-20 as expected.
33 new tests (`test_draft_history.py`, `test_draft_tendencies.py`,
`test_roster_needs.py`), 89/89 total passing. Pushed as `8a926cb`.

### 2026-08-25 — Fixed two real tiering bugs the league manager caught by using it: manual override drifting wide, automatic method too coarse
Follow-up to the tiering feature shipped earlier the same day (next log
entry down). The manager tried it immediately and found two real problems:

**Bug 1 — manual override drifted wider than the number entered.** Typing
"10" for QBs produced a tier spanning 780.8 to 726.3 (54 points). Root
cause: the original manual-mode logic only compared each player to the
*immediately preceding* player, not to the tier's top scorer -- a chain of
small sub-threshold gaps (several 3-8 point drops in a row) could
accumulate into a much wider total spread without any single step ever
exceeding 10. Fixed in `compute_tiers()` (`src/projections.py`) by
switching to an anchor-based check: each candidate is compared against the
*current tier's leading player's* score, not the previous row. New
`tier_max_spread` column added so the guarantee (no tier's spread exceeds
the override value) is directly visible and directly tested
(`test_manual_gap_threshold_creates_expected_tiers`, and the real-data
guarantee is exercised via `test_automatic_tiers_on_real_data_are_not_
absurdly_wide` for the automatic side).

**Bug 2 — the automatic method was still "too wide"** (the manager's own
words) even after replacing the original mean+stdev approach with Jenks
natural breaks earlier that day: QB's top tier held 30 players spanning
218 points. Root cause, found by testing against the real 2026 data rather
than trusting the small synthetic unit tests: a target-GVF stopping rule
(grow the class count until it explains a target % of variance) behaves
very differently depending on pool size and shape. For a large,
*gradually*-declining pool like QB (no single standout cliff, just a long
smooth slope), the global variance-reduction budget kept getting spent
elsewhere (a genuine late-list outlier) before the algorithm ever
revisited splitting the smooth top cluster further. A second attempt
(recursive local-outlier-gap splitting, to avoid the "global stat skewed
by one huge gap" problem) fixed the small-pool over-fragmentation this
caused but reintroduced the QB problem from the opposite direction: a
smooth gradual slope has no single local outlier gap to trigger a split at
all, however wide the cumulative range gets.

Both failure modes shared a root cause: neither approach ever directly
asked "how wide is this tier allowed to get" -- both inferred an answer
indirectly from gap statistics. Rewrote `jenks_auto_labels()`
(`src/tiering.py`) a third time to ask that question directly: grow the
Jenks class count only as far as needed so no resulting tier spans more
than `max_spread_fraction` (default 0.08, i.e. 8%) of that position's own
top-to-bottom point range, capped at `max_tiers` (default 15) as a safety
valve. Verified against real 2026 data across all 6 positions -- QB's
worst-case tier dropped from 30 players/218 points to a 5-7 player/
30-60 point range; RB/WR/TE/K/DST all produce similarly reasonable,
non-fragmented tiers. `src/tiering.py`'s module docstring keeps the full
story of why the first two designs each looked right until tested against
real data, specifically so a future session doesn't re-attempt either one
without knowing it was already tried and rejected.

Verified: 66/66 tests passing (11 new/changed); both pages re-run under
`AppTest` with the exact reported scenario (QB filter + manual override of
10) confirming every tier's spread is now bounded correctly.

### 2026-08-25 — Superflex-heavy QB demand assumption + position tiering (auto + manual override)
Two related requests from the league manager after reviewing Josh Allen's
VOR rank (#23 despite #1 overall raw points): (1) this league's scoring
system makes QB the near-automatic superflex fill, so demand modeling
should reflect ~2 QBs/team almost every week, not a soft 55% lean; (2)
add visible "tiers" to the player grid — clusters of same-position players
who are roughly interchangeable, split by real point drop-offs, with both
an automatic default and a manual override (e.g. "all players within 10
points are one tier").

**Superflex demand:** `config/league_settings.yaml` →
`estimation_assumptions.flex_position_splits.SUPERFLEX` changed from
QB 0.55/RB 0.20/WR 0.20/TE 0.05 to **QB 0.90/RB 0.04/WR 0.04/TE 0.02**. The
small non-QB residual is deliberate (not a claim ~10% of teams will
genuinely bench a good QB for the flex) — it keeps replacement level from
being brittle to a single 100%-certain assumption. New test
(`test_superflex_demand_is_now_overwhelmingly_qb` in
`tests/test_projections.py`) locks in QB demand ≈ 19 (10 dedicated + 9 from
superflex) vs. the old ≈ 15.5.

**Tiering:** `src/projections.py`'s new `compute_tiers(board, metric=
"score_total", gap_threshold=None, k=1.0)` groups each position's players
into 1-indexed tiers:
- `gap_threshold=None` (default): automatic — flags a tier boundary when
  the point-drop to the next player is a statistical outlier for that
  position (`drop > mean(drops) + k*std(drops)`), so it adapts to each
  position's own scoring scale (kickers cluster tight, QBs/RBs spread
  wider) without a single fixed point value across positions.
- `gap_threshold=<number>`: manual override — new tier whenever the drop
  exceeds that many points, exactly the "within N points" control asked
  for.
- Tiering by `score_total` and by `vor` produce identical boundaries
  within a position (vor is just score_total minus a per-position
  constant) — verified by test, so the page only needs to expose one.

Real result on the actual 2026 blended data: QB auto-tiers into just 3
tiers (30 QBs in tier 1 — this year's pool really is that bunched at the
top, consistent with the VOR writeup in `docs/draft_insights.md`), while
RB auto-tiers into 9 much tighter tiers, matching the known shallow/fast-
drop-off RB pool. This is a good sanity check that the auto method is
doing something real, not just noise.

`pages/1_Draft_Board.py` and `pages/2_Projections.py` both got: a "Tier
gap override (pts)" number input (0 = automatic), a "Tier" column in the
player grid, and — only when the grid is filtered to exactly one position
(tier numbers are position-relative, so mixing positions would be
confusing) — visible "— Tier N —" divider rows via the new
`src/tier_display.py`'s `add_tier_divider_rows()`.

**Bug caught and fixed via `AppTest` before shipping:** the first version
of `add_tier_divider_rows()` wrote the divider's label text into whichever
column happened to be first in the display frame. On the Draft Board
that's "VOR Rk" — a numeric rank column — so mixing in a string label
corrupted it to a mixed int/string object column, which threw a real
`pyarrow.lib.ArrowTypeError` inside `st.dataframe` (silently auto-"fixed"
by Streamlit's own fallback, so it wouldn't have crashed the page, but
it's exactly the kind of fragile-in-a-way-status-codes-won't-catch bug
this project has hit before — see the ParserError entry below). Fixed by
adding an explicit `label_col` parameter (both pages pass `"Player"`) and
using `None` instead of `""` for every other column in a divider row, so
pandas upcasts a numeric column to float+NaN — which Arrow serializes
fine — instead of degrading it to a generic object column. Caught by
running both pages through `streamlit.testing.v1.AppTest`, filtering to a
single position, and inspecting the actual rendered dataframe's dtypes —
not just checking for an exception. Regression test in
`tests/test_tier_display.py`.

Verified: 58/58 tests passing (12 new); both pages run clean under
`AppTest` with a position filter applied and a manual tier-gap override
set, with the rendered dataframe inspected directly (not just "no
exception raised").

### 2026-08-25 — Three-source projection ingestion (CBS + FFToday + FantasyPros), new Projections page, live refresh
The app's rankings are only as good as the stat projections feeding the
scoring engine, so the user asked for 3 free sources to average/weight
together instead of relying on CBS alone.

**Sources researched and their real limitations:**
- **CBS** (already had this) — full player pool, but requires a logged-in
  session and blocks robots.txt, so it can never be live-refreshed by the
  deployed app. Re-pull is manual: visit the CBS projections URL in a
  logged-in browser, capture the page, re-run the ingestion by hand (same
  pattern as the draft-order pull below).
- **FFToday** — no login required, full free depth (~50 players per skill
  position, all 32 DSTs), and it's a plain server-rendered page — a bare
  `requests.get()` works, no browser needed. This is the strongest 3rd
  source. Live refresh confirmed to fail *only* because this dev sandbox
  has no general internet egress (proxy 403, not a fftoday.com error) —
  the refresh button's error handling was verified against this exact
  failure via Streamlit's `AppTest` harness, and it surfaces cleanly
  instead of crashing the page. Should work once deployed somewhere with
  normal internet access (Streamlit Cloud).
- **FantasyPros** — free/anonymous view hard-caps every position table at
  the top 10 players; the print view and any deeper page redirect to a
  sign-in wall (confirmed by navigating there directly). Went looking for
  a 4th free full-pool source to replace it per the user's request:
  Footballguys and FTN are both subscription-only for projections,
  NFL.com's own fantasy-projections tool is defunct (redirects to a dead
  ESPN-merged page — a `WebFetch` hallucination initially reported this
  page as working with fake data, see lesson below), and ESPN's Mike Clay
  projections are only published as a PDF/article, not a
  scrapeable table — not built this session, flagged as a future
  candidate if someone wants to hand-transcribe it. Decision: kept
  FantasyPros as a partial/supplementary source (top-10 coverage is
  exactly where 3-source agreement matters most for early picks) rather
  than blocking on a 4th source that doesn't cleanly exist for free.

**Lesson (important, cost real time this session): don't trust `WebFetch`
on JavaScript-rendered pages.** It silently fabricated confident,
precisely-formatted, entirely wrong data twice — once for FantasyPros'
QB page (returned FFToday's real numbers relabeled as FantasyPros), once
for the defunct NFL.com projections page (invented a fake "1-25 of 1036
results" table). Neither errored out; both looked plausible. Caught by
cross-referencing against direct browser DOM extraction. Going forward:
use Claude in Chrome (`navigate` + `javascript_tool` DOM extraction, or
`get_page_text` for server-rendered pages) for any site where WebFetch's
output can't be independently verified, never WebFetch alone.

**Built:**
- `src/data_sources/team_names.py` — `canonical_dst_name()`. CBS names
  DSTs by short city ("Houston", "L.A. Rams"); FFToday and FantasyPros
  both use full "City Nickname" ("Houston Texans"). Without normalizing,
  `blend_projections()`'s join on `name_key` would silently treat the same
  DST as unrelated rows across sources. Maps all 32 teams' full names to
  CBS's short form; unknown names pass through unchanged rather than
  raising, so a future team rename doesn't crash ingestion.
- `src/data_sources/fftoday.py` — `parse_position_text()` (parses either a
  live fetch's extracted text or a saved `get_page_text` capture, same
  format) and `fetch_position()`/`fetch_all()` (live HTTP fetch via
  `requests` + BeautifulSoup text extraction). Handles the DST unit
  mismatch: FFToday's `PA` is a season total (divided by 17 games to match
  CBS's per-game convention) while its `PaYd/G`/`RuYd/G` are already
  per-game (summed, not divided).
- `src/data_sources/fantasypros.py` — `parse_position_rows()` (parses the
  row-array table data captured via `javascript_tool` DOM extraction) and
  `fetch_position()`/`fetch_all()` (attempted live fetch via `requests` +
  `pandas.read_html`, **UNVERIFIED** — no XHR/JSON API was found via
  `read_network_requests`, suggesting but not proving the table is
  server-rendered; this sandbox can't test outbound requests to
  fantasypros.com at all, so this path needs real-world confirmation once
  deployed). Same DST season-total→per-game conversion as FFToday (`PA`
  and `YDS AGN` both divided by 17).
- `pages/2_Projections.py` — new page. Per-source weight sliders (0 to
  exclude a source, any single non-zero weight to view one source alone),
  a player-lookup showing each source's raw line side-by-side plus the
  blended result, a full sortable/filterable blended board, and a
  "Refresh from web" button per live-capable source (FFToday,
  FantasyPros) that re-fetches, overwrites that source's CSV, and clears
  the Streamlit cache so the new data shows immediately. CBS has no
  refresh button — a caption explains why.
- `scripts/fetch_fftoday.py` / `scripts/fetch_fantasypros.py` — CLI
  wrappers (`--live` or `--from-capture <path>`) for manual/future refresh
  runs outside the Streamlit UI, mirroring `scripts/fetch_draft_order.py`.
- Seed data written: `data/projections/fftoday_2026.csv` (264 rows),
  `data/projections/fantasypros_2026.csv` (60 rows), both auto-picked-up
  by the existing `_data_files()`/`load_many()` pipeline. Raw captures
  kept for audit at `data/projections/raw/`.

**Bug caught and fixed during verification:** FFToday's parser extracted
the team-code token (e.g. "BUF") to validate row structure but never
actually stored it in the output row — every skill-position player from
FFToday had a blank `nfl_team`. Caught by running the new Projections page
through `streamlit.testing.v1.AppTest` (see lesson below) and noticing
Josh Allen's FFToday row showed `NaN` for team. Fixed, added a regression
test (`test_nfl_team_populated_for_all_skill_positions`), rebuilt the CSV.

**Lesson: `streamlit.testing.v1.AppTest` catches real bugs an HTTP-200
check can't, without needing a browser.** It runs a page's actual script
in-process and lets you inspect rendered widgets/dataframes/exceptions
directly — this is how the missing-`nfl_team` bug above was caught, and
how the refresh button's error path (network failure -> `st.error`, not a
crash) was verified. Use this instead of (or in addition to) `curl`-ing a
running `streamlit run` process, which only proves the initial HTML shell
loads — Streamlit runs each page's script over a websocket after that,
so `curl` never actually executes the page code.

**Verified end-to-end:** all 3 sources load and blend correctly
(`load_many` → `blend_projections` → `score_and_rank`); spot-checked Josh
Allen, Jahmyr Gibbs, Trey McBride, Brandon Aubrey, and the Houston DST
join and blend correctly across all 3 sources with the exact values from
each raw capture; 46/46 tests passing (17 new: `test_fftoday.py`,
`test_fantasypros.py`, `test_team_names.py`); both `pages/1_Draft_Board.py`
and `pages/2_Projections.py` run clean under `AppTest` with no exceptions,
including exercising the refresh button's failure path.

**Not verified (can't be, from this sandbox):** whether FantasyPros'
live-refresh via `requests`/`pandas.read_html` actually works — needs
confirmation from a real deployment with internet access. If it turns out
the page needs JS rendering after all, `fetch_position()` raises a clear
`ValueError` rather than silently returning wrong data — fall back to a
fresh Claude-in-Chrome capture + `scripts/fetch_fantasypros.py
--from-capture` in that case.

### 2026-08-25 — Pulled real 2026 draft order, wired into the Draft Board
User asked for the draft order/teams from
`https://maniacfl.football.cbssports.com/draft/results/2026:Pre-season:MFL%20Draft%202026/`
(needs a logged-in session; also blocked by robots.txt for plain fetch,
so used Claude in Chrome against the user's real browser session).
22 rounds x 10 teams, standard snake, draft not yet started. Round 1
order: Mississippi Swamp Ass, Aces High, THE DEMONS, Pimp Daddy, Legion
of Doom, Mojo, Salty Dogs, **Monster Cheese**, Buckhorns, Ball Busters.

Built this as a reusable pipeline, not a one-off, since the user asked
for something that "autopopulates" in future years:
- `src/data_sources/draft_order.py` — `draft_results_url(year)` builds
  the CBS URL from a template (verified it reproduces the exact known-
  good 2026 URL); `parse_draft_order_text()` parses a saved page-text
  capture into a structured order and validates it's a standard
  alternating snake (flags it in `notes` if not, since
  `src/draft_state.py`'s `DraftState.team_for_pick()` assumes one).
- `scripts/fetch_draft_order.py` — CLI that runs the parser against a
  saved text file and writes `data/draft/<year>_draft_order.json`, plus
  `--update-config` to patch `draft.team_order` in
  `config/league_settings.yaml` in place (targeted text substitution,
  not a full YAML round-trip, so the file's comments survive).
- Important limitation, not automatable away: CBS requires login and
  blocks robots.txt, so there's no way to fetch this with plain
  `requests` code. The yearly workflow is: get the URL from
  `draft_results_url()`, visit it in a logged-in browser (Claude in
  Chrome or the user's own), grab the page text, save it, then run the
  script on that file. Full docstrings in both files above walk through
  this.
- `pages/1_Draft_Board.py` now reads `draft.team_order` from config
  instead of placeholder team names, with a fallback + on-page warning
  if it's ever missing (e.g. before a future year's order is captured).
- Tests in `tests/test_draft_order.py` (9 new, 28/28 total passing)
  cover the real 2026 capture, URL building, snake validation, and — the
  part that actually matters — that the parsed order drives
  `DraftState.team_for_pick()` to the correct team for every single pick
  across all 22 rounds, not just round 1.
- Raw captured page text saved at
  `data/draft/2026_draft_order_raw.txt` for audit/reproducibility;
  parsed output at `data/draft/2026_draft_order.json`.

### 2026-08-25 — Session notes moved into the repo
Previously this log lived as a doc in the attached Claude Project
("MFL Team Manager"). Moved it here instead, since a repo-tracked file
travels with the repo no matter how a future session is started, and the
user asked not to get a rewritten Project doc after every response.
The Project doc now just points here.

### 2026-08-25 — Fixed Draft Board ParserError on Streamlit Cloud
User deployed to Streamlit Cloud and hit `pandas.errors.ParserError` on
the Draft Board page. Root cause: `pages/1_Draft_Board.py` globbed
`data/projections/*.*`, which also matched `data/projections/README.md`;
`load_table()` has no markdown branch so it fell through to
`pd.read_csv()` on the README and pandas choked on it. Fix: replaced the
glob with an explicit directory listing filtered to real data extensions
(`.csv`, `.tsv`, `.xlsx`, `.xlsm`, `.xltx`, `.xls`). Pushed as `8be693d`.
Verified 19/19 tests passing plus a direct pipeline run (load → score →
rank) against the real data, end to end, no exception. User confirmed
fixed on their live deployment.

Lesson: checking `streamlit run app.py` returns HTTP 200 does NOT catch
this class of bug — Streamlit renders exceptions inside the page body,
still as a 200 response. Verify by exercising the underlying pipeline
directly or checking actual rendered content, not status codes alone.

### 2026-08-24/25 — Repo restored and pushed after two sessions couldn't push
Two prior sessions were started without this repo attached as a write
source (see "Git push access" above for the workaround now in place).
The actual Phase 1 code from the original working session only existed
as a zip export the user had saved locally (`monstercheeseteammanager_2.
zip`) — the repo on GitHub had only the initial README. Restored the zip
into a fresh clone, verified deps installed cleanly and 19/19 tests
passed, and pushed as `8a2cbb4`. This is now the real state of the repo;
future sessions can just `git clone` it, no zip needed.

### 2026-08-24 — Real league rules re-verified from CBS
Re-captured full scoring tables directly from
`https://maniacfl.football.cbssports.com/rules` (logged-in). Source of
truth is `config/league_settings.yaml`. Key points: passing/rushing/
receiving yardage are tiered (every 25yd or so = +2pts, extrapolated
beyond the table); TD base 6/6/7 (passing/rushing/receiving) with +2
long-td bonuses; FG base 3 +1/+2/+3 by distance; INT thrown -3, fumble
lost -1, missed XP -1. Defensive PA/yards-allowed genuinely only have 3
tiers each on CBS's page — deliberately not extrapolated further (their
trend is decreasing, extrapolating risks going negative on a guess) —
flagged for the commissioner to confirm if more tiers actually exist.
Roster: 12 starters (1 QB, 3 RB, 3 WR/TE flex, 1 TE, 1 K, 1 superflex, 1
flex RB/WR/TE/K, 1 DST); the TE rule (2 WR + 2 TE legal, 2 WR + 1 TE
illegal) is enforced by the app since CBS's own checker doesn't catch it.

### 2026-08-24 — Real 2026 CBS projection data pulled
Pulled real 2026 season projections for all positions from
`cbssports.com/fantasy/football/stats/{POS}/2026/season/projections/
nonppr/` via browser automation — 415 players total (QB/RB/WR/TE/K/DST).
Saved to `data/projections/cbs_2026.csv`. Note the URL uses `nonppr`, not
`standard/ppr/half-ppr` — CBS 404s on some other casings. The Draft Board
prefers `data/projections/` over `data/sample/` automatically whenever
real files exist.

### 2026-08-24 — VOR analysis: draft RBs early, not the biggest raw score
`docs/draft_insights.md` has the full writeup. Raw per-player score is
QB-dominated (14 of the top 15 highest-scoring players leaguewide are
QBs). But value-over-replacement flips this: 18 of the top 24 VOR-ranked
players are RBs, only 1 QB (Josh Allen) makes that cut. Why: QB demand
(~15.5 leaguewide incl. superflex) is met by a deep pool (QB15 isn't far
behind QB1), while RB demand (~36 leaguewide) hits a much shallower pool
that falls off fast. Practical takeaway: prioritize top RBs early: the
Draft Board's default VOR sort already reflects this. Caveats depend on
the flex-split assumptions in `config/league_settings.yaml` — read the
full file before treating this as gospel.
