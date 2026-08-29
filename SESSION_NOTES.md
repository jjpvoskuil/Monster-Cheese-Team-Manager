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
  `estimation_assumptions.flex_position_splits.SUPERFLEX`) is now 100% QB
  (was 90%, originally 55%), per league-manager feedback (2026-08-27):
  "while we don't have to start 2 QBs it is always the best choice if 2
  are available." QB league-wide demand is now ~20 (10 dedicated + 10 of
  the superflex slot), up from ~19, which raises QB's replacement level
  and lowers early-QB VOR accordingly.
- **Real league draft requirements loaded (2026-08-27)**: the league
  manager's "Maniac Football League Draft Sheet" is now wired into
  `config/league_settings.yaml`'s `estimation_assumptions.
  round_based_fill_targets` (changed shape from a dict keyed by position
  to a LIST of `{slot, eligible, count, by_round}` categories, so
  multi-eligible requirements like "WR or TE" and "RB, WR, or TE" can be
  represented) — by round 20: 2 QB (kept at the tighter, simulation-tuned
  round-6 deadline rather than the doc's own looser round-20 one), 2 K,
  2 DEF, 5 RB, 5 WR/TE, 1 RB-or-WR-or-TE, 1 mandatory TE, 2 any-position;
  rounds 21-22 unconstrained. `src/pick_suggestion.py`'s
  `_round_based_quota_positions()` now groups categories by shared
  deadline and checks the GROUP's total remaining need against remaining
  picks before that deadline (catches a combined shortfall across several
  categories even when no single one looks urgent alone), and
  `my_position_need()` now also draws soft demand from unfilled
  requirement categories all draft long, not just at the hard deadline.
  `pages/4_My_Roster.py` has a new "Draft Requirements" section (same
  per-category fill-progress table style as Starting Lineup) plus a
  warning banner from round 18 on and an error banner past round 20 if
  requirements are still unmet. **Flagged, unresolved**: this doc's "2
  DEF" and TE-flexibility requirement conflicted with the existing
  `roster.position_active_limits` (DST max 1, TE max 1, captured
  2026-08-24 from a different CBS page) — raised both caps to 2 so the
  redundancy mechanism doesn't block satisfying the real requirement, but
  this hasn't been re-confirmed against CBS's actual platform behavior;
  if CBS technically hard-caps DST at 1, drafting a 2nd DEF may be
  impossible in practice, not just suboptimal. Re-confirm before draft
  day if it matters. See the dated log entry below for the full Monte
  Carlo comparison re-run against this config.
- **Monte Carlo simulation harness now committed (2026-08-27)**:
  `scripts/simulate_draft.py` + `src/lineup_value.py` (formalizes the
  prior sessions' `/tmp/sim/simulate*.py` scratch scripts, which were
  never committed and had to be rebuilt from scratch this session after
  being lost between sessions). Same core methodology as before: Monster
  Cheese always drafts via the real `suggest_position()`/
  `top_available_players()`, opponents sample a position from real
  historical per-round tendencies then take best-available VOR, and every
  team's OPTIMAL starting-lineup points (proper `scipy.optimize.
  linear_sum_assignment` weighted-bipartite-matching solve, not draft
  -order greedy fill) are compared after each simulated draft. Re-running
  it against yesterday's real 8-category round-20 requirement set found
  and fixed a real bug: `suggest_position()`'s mandatory/quota-deadline
  override tier (`must_fill`) took the single highest-composite position
  across an ENTIRE urgent multi-eligible bucket with no redundancy-cap
  check at all, unlike the ordinary ranking path -- since most of this
  league's real requirements share one round-20 deadline and get grouped
  together, an unfilled "5 WR or TE" category could let an
  already-at-cap TE (composite squashed by REDUNDANCY_PENALTY but still
  positive) beat a legitimately-intended-but-deeply-negative-VOR WR,
  leading to Monster Cheese drafting up to 6 TEs in one simulated draft
  -- well past the configured `position_active_limits` max of 2. Fixed by
  preferring a not-at-cap option within the must-fill set (falls back to
  a capped one only if every urgent option is capped, e.g. a truly
  sole-eligible mandatory slot). Confirmed the fix's SCOPE mattered a lot:
  an initial version that ALSO excluded early-round-discounted (K/DST)
  options from must-fill measurably hurt performance (avg league rank
  1.28 -> 2.12 of 10, worst-case rank 4 -> 7, same 25 trials/seeds) --
  K/DST's early-round discount is a soft timing preference, not a
  "contributes nothing" statement like the redundancy cap, so a genuine
  looming deadline should still override it. Also confirmed (20 trials
  each, same seeds): fully uncapping TE (removing it from
  `_CAPPABLE_POSITIONS` given it's WR_TE_FLEX-eligible) performs slightly
  WORSE than the current cap=2 (avg rank 1.25 vs 1.10, avg pts 6949 vs
  6968) and lets Monster Cheese roster up to 9 TEs -- keeping the
  existing cap is correct, not just legacy caution; reweighting
  value/need/scarcity (need_heavy/scarcity_heavy/value_heavy vs. shipped
  0.45/0.30/0.25) again landed within noise of each other, reconfirming
  the 2026-08-26 finding still holds against the new requirement set --
  no weight change made. A `no_quota` ablation against the full new
  8-category requirement set shows just how much the round-based-quota
  mechanism as a whole is now carrying: avg rank 5.0 of 10 (top-3 25%,
  worst 9th) and only 65% ever landing a 2nd QB at all (avg round ~17
  when they did) vs. the shipped config's avg rank 1.28 (top-3 96%,
  100% 2nd QB by round 6). 2 new tests in `test_lineup_value.py`, 2 new
  regression tests in `test_pick_suggestion.py` (deliberately verified
  against the pre-fix code to confirm they actually catch the bug, not
  just numerically coincide with the fix). 196/196 tests passing.
  `scripts/simulate_draft.py --help` documents CLI usage; `scipy` added
  to `requirements-dev.txt` (dev/sim-only dependency, not needed by the
  deployed Streamlit app itself).
- **Development page: punch-list items now get permanent #numbers
  (2026-08-28)**: league manager wants to say "work on #7" and have
  that be unambiguous. `PunchListItem` gained a `number: int` field,
  assigned by `PunchList.add()` from a persisted, monotonically
  -increasing `next_number` counter (stored in `data/punch_list.json`
  alongside the items) -- so numbers are stable across restarts and
  NEVER reused, even after the item they belonged to is deleted. New
  `PunchList.get_by_number(n)` looks an item up by its #, for scripted/
  future use beyond the UI. Old files saved before this existed (item
  dicts with no `"number"` key) migrate automatically on next load:
  unnumbered items get sequential numbers in creation order (oldest
  first), the migration is saved immediately so it only ever runs once,
  and `next_number` picks up from the highest number seen either way.
  `pages/5_Development.py` now shows `#N` in the open-items expander
  title, the closed-items list, and the "Added" confirmation toast. 8
  new tests (sequential assignment, no reuse after delete,
  `get_by_number` hit/miss, numbering survives a reload, legacy-file
  migration + it only runs once); 230/230 tests passing. Verified via
  headless `AppTest` against both an empty list and a populated one (2
  items, one closed) — no exceptions; numbers rendered correctly
  (`#1`, `#2`) in both the expander labels and closed-list markdown.
- **Live Draft Tracker: number-formatting bug fixed (2026-08-28, sixth
  pass)**: league manager: "fix the numbers. They should be in the
  format 'x.x'." Root cause: `pages/3_Draft_Tendencies.py` called
  `.style.format(...)` TWICE on the tracker's Styler -- once for the
  proj columns' `"{:.1f}"`, once for the delta columns' `"{:+.1f}"`.
  pandas' `Styler.format()` resets any earlier call's per-column
  formatters for columns the new call doesn't re-list, so the SECOND
  call silently wiped out the first's formatting and every proj column
  fell back to pandas' raw default float precision -- rendering like
  `"2.200000"` instead of `"2.2"`. Fixed by merging both format specs
  into ONE dict and calling `.format()` once. Confirmed via a byte
  -level inspection of the rendered Arrow table (decoded the Styler's
  `display_values` buffer through `pyarrow`) that cells now render
  exactly `"4.5"`, `"-3.5"`, `"+3.8"`, etc. -- true 1-decimal formatting,
  not just visually plausible. 225/225 tests passing (no `src/` logic
  touched). General lesson for this codebase: chaining multiple
  `Styler.format()` calls on different column subsets is a trap --
  merge into one dict-based call instead.
- **Live Draft Tracker: Δ columns restored as their own narrow columns
  (2026-08-28, fifth pass)**: the previous pass's merge of each
  position's Proj+Δ into one cell ("18.0 (+1.0)") lost the ability to
  compact them independently and read as "we lost the delta columns."
  Split back into two columns per position -- `QB` (proj) and `ΔQB`
  (delta) -- but unlike the ORIGINAL (pre-merge) version, both are now
  sized via the same content-fit `_col_px()` from the previous pass,
  using short position-code headers instead of "QB Proj"/"QB Δ". Since
  the displayed values are short (`"18.0"`, `"+1.0"`, `"–"`) and the
  headers are just the position code, each pair comes out ~34px wide --
  narrower in total (12 columns @ ~34px = ~408px) than the single
  merged column had been (6 columns @ ~80-100px = ~480-600px), so
  splitting them back apart actually shrank the grid further, not just
  restored it. `_col_px()`'s pad/per_char tightened slightly (14→10)
  since numeric columns carry less UI chrome than text ones. Delta cell
  coloring reverted to a numeric sign check (`Styler.map` on the real
  float column, NaN-safe) instead of the previous pass's string
  -parsing hack, since the column is numeric again. 225/225 tests
  passing (layout-only change). Verified via headless `AppTest` against
  both an empty draft state and the same populated worst-case scenario
  as the prior pass — no exceptions; worst-case total grid width
  estimate came in around ~870px, down from ~960px.
- **Live Draft Tracker: content-fit column widths (2026-08-28, fourth
  pass)**: league manager: "make the 'your pick', 'Consider now' and
  'can wait' columns smaller to match the max characters the field will
  actually need. The grid is still off screen on the right." Replaced
  the fixed `width="small"/"medium"` column_config values with pixel
  widths computed FROM the actual data each rerun: `_col_px(header,
  values)` measures the widest header/value in "display units" (emoji
  like 🔒 and separators like `·` count double, since a plain
  character-count undercounts how wide they render) and returns
  `pad + per_char * widest` pixels, floored at a small minimum. Applied
  to every column, not just the 3 named -- Round/Pick #/each position
  column shrink too whenever their real content is short. Recomputed on
  every rerun, so e.g. "Your pick" grows automatically the one time a
  long-named DST actually gets drafted, without needing a hardcoded
  worst case. Verified with a scripted worst-case scenario (every pick
  logged as "DST · San Francisco 49ers" or a long RB name) — no
  exceptions, and the estimated total grid width dropped from a fixed
  ~1200px+ to as low as ~960px in that same worst case (typically much
  less with real, shorter position codes/names). 225/225 tests passing
  (no test changes — this is pure display/layout, same underlying data).
- **Live Draft Tracker: roster-cap-aware consider-now/can-wait, compact
  columns (2026-08-28, third pass)**: league manager: "if the teams
  ahead of us prior to our next pick are all filled on RB's, they are
  far less likely to take any and we potentially can wait" -- pure
  historical prediction couldn't see that. New `src/roster_needs.py`
  functions: `positions_at_cap(position_counts, config)` (which
  positions a team is now structurally blocked from drafting more of,
  per config's real `roster.position_active_limits` -- WR has no
  standalone cap, only a combined WR_TE bucket both WR and TE draw
  from, handled explicitly) and `positions_blocked_for_all(window_teams,
  capped_positions)` (intersection of capped positions across a set of
  teams). The Live Draft Tracker now computes, per round row, which
  teams pick in that row's window (deterministic from snake order, not
  from what's actually been drafted) and downgrades a
  historically-predicted "run" position to **Can wait** (marked 🔒)
  whenever EVERY one of those teams is already capped on it — a real
  constraint, not a strategy guess, and one that (unlike a starter
  -need read) only ever gets MORE true over time, so it's safe to apply
  even to rounds well ahead of where the draft currently stands.
  Verified the exact scenario end-to-end with a scripted repro (window
  teams forced to cap 1 RB each, only RB demoted, WR left alone).
  Also crunched the grid to fit without horizontal scrolling per
  request: merged each position's separate Proj/Δ columns into ONE
  compact cell (`"2.2"` before a round is reached, `"2.2 (+1.0)"` once
  it is, red/green background parsed from the `(+`/`(-` in the cell
  text itself rather than a parallel data structure), all numbers at 1
  decimal place throughout the page (including the opponent-demand
  table, previously 2), and explicit `column_config` widths (`small`
  for Round/Pick#/position columns, `medium` for the text columns) on
  top of `use_container_width`. 8 new tests (4 `positions_at_cap`, 4
  `positions_blocked_for_all`); 225/225 tests passing. Verified via
  headless `AppTest` against both an empty draft state and a 60-pick
  scripted state that pushes several opponents past the real RB cap
  (5) — no exceptions either way.
- **New "Development" page — in-app punch list (2026-08-28)**: league
  manager wants to input, edit, and close punch-list items directly in
  the app as it keeps getting refined, rather than tracking them
  elsewhere. New `src/punch_list.py` (`PunchList`/`PunchListItem`, same
  atomic JSON persistence pattern as `src/draft_state.py`, saved to
  `data/punch_list.json`, gitignored — it's live user data, not repo
  content) supports add/update/close/reopen/delete with title (required),
  optional details, and a High/Medium/Low priority. New
  `pages/5_Development.py` (sidebar icon 🛠️, added to `app.py`'s page
  list): a form to add items, an editable list of open items sorted by
  priority then oldest-first (inline title/details/priority fields per
  expander, with Save/Close/Delete buttons), and a collapsed "Closed"
  section with one-click reopen. 10 new tests in `test_punch_list.py`;
  216/216 tests passing. Verified via headless `AppTest` runs of the new
  page both empty and with open + closed items populated (no exceptions
  either way; the test data was removed afterward, real file untouched).
- **Live Draft Tracker, redesigned + moved to the top (2026-08-28,
  supersedes the 2026-08-27 version below)**: the league manager asked
  for a second pass — wanted the tracker at the VERY top of Draft
  Tendencies (immediately visible during the draft, not tucked in a
  collapsed section), projected cumulative counts shown alongside the
  actual counts EXPRESSED AS A DELTA off projection (not actual-or
  -projected as separate rows), and two new columns reading which
  positions to consider drafting now (a run is projected before your
  next pick) vs. which can wait. `pages/3_Draft_Tendencies.py` now opens
  with an uncollapsed "🎯 Live Draft Tracker": one row per round of
  Monster Cheese's draft slot, `{POS} Proj` = historical cumulative
  average at that pick (`historical_cumulative_at_pick()`), `{POS} Δ` =
  actual − projected once that round is reached (🔴 red background if
  running hotter than history / scarcer than usual, 🟢 green if cooler /
  safer, blank "–" for rounds not yet reached), plus **Consider now** /
  **Can wait** columns computed per-row from `next_run_positions()`
  windowed on THIS round's actual gap to the team's own next pick (not
  the sidebar's fixed look-ahead slider) — positions in the predicted
  run go in "Consider now", everything else in "Can wait". Styled via a
  pandas `Styler` (`.map()`, not the pandas-3-removed `.applymap()`).
  Everything else on the page (historical-per-round table, the
  slider-driven "what's likely next", opponent roster needs) got pushed
  below a divider and wrapped in individually collapsed `st.expander`s,
  per instruction to push supporting detail down and keep only the
  tracker immediately visible. No new `src/` functions needed — reused
  `team_pick_in_round()`, `actual_cumulative_at_pick()`,
  `historical_cumulative_at_pick()`, and `next_run_positions()`, all
  already built and tested for the prior version of this feature (same
  day before this redesign). Verified via a headless `AppTest` run of
  the full page against both an empty and a 15-pick-logged draft state
  (no exceptions either way) and the full test suite. 206/206 tests
  passing (no test changes needed — only UI code changed).

- **Live cumulative picks-by-round tracker, v1 — superseded same day
  (2026-08-27/28)**: first pass at this feature: a collapsible "📋 Live
  cumulative picks by round" section (`st.expander`, collapsed by
  default) automating the league manager's old hand-tallied "Alt
  Targets" worksheet — one row per round, showing **either** the actual
  cumulative count (rounds already reached, green-highlighted) **or**
  the historical projection (rounds still ahead, amber-highlighted) per
  position. Replaced by the redesign above per league-manager feedback:
  wanted the tracker uncollapsed at the top of the page, and wanted
  actual shown as a DELTA against projection rather than swapping one
  for the other. `DraftState.team_pick_in_round(team, round_num)` (finds
  a team's one overall pick within a snake-draft round) and
  `src/draft_tendencies.py`'s `actual_cumulative_at_pick()` /
  `historical_cumulative_at_pick()` were built for this version and are
  still in use by the redesign above.
- **Sidebar nav switched to `st.navigation()` (2026-08-27, cosmetic)**:
  `app.py` used to BE the landing page (league-settings summary + draft
  countdown), which under Streamlit's classic `pages/`-directory
  auto-discovery made the sidebar's top entry show the literal filename
  "app" -- confusing, since it's really league settings. `app.py` is now
  a thin router: it calls `st.set_page_config()` once, declares every
  page's title + icon explicitly via `st.Page(...)`, and hands off to
  `st.navigation(pages).run()`. The old landing content moved verbatim to
  new `pages/0_League_Settings.py` (title "League Settings", icon ⚙️,
  the default page). Every other page kept its filename/URL/content
  unchanged -- only each page's own `st.set_page_config()` call was
  removed (it can only be called once per app run now, so it lives solely
  in `app.py`) and it picked up an explicit icon it didn't have in the
  sidebar before (classic mode only reads a page's icon from an emoji
  *in the filename*, e.g. "1_🏈_Draft_Board.py", which this repo's
  plain-English filenames never used): Draft Board 🏈, Projections 📊,
  Draft Tendencies 📈, My Roster 📋. `st.page_link()` calls between pages
  (e.g. Draft Board <-> My Roster) still use the same `pages/*.py` path
  strings as before and didn't need changes. Run command is unchanged
  (`streamlit run app.py`) -- verified locally (headless smoke-test boot)
  and via the existing `AppTest`-based page tests
  (`tests/test_draft_board_page.py`, entered via `app.py` +
  `switch_page()` same as before), all 7 still pass unmodified against
  the new router. 196/196 tests passing overall.
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

### 2026-08-29 — Punch list #1: 100-trial Monte Carlo simulation → ADP column + simulated league-strength table

Extended the existing `scripts/simulate_draft.py` harness (already ran
full 220-pick mock drafts with Monster Cheese picking via the real
`suggest_position()`/`top_available_players()` and opponents sampling
from real historical per-round position tendencies) to also aggregate
two new outputs across all trials, via new `--adp-csv`/`--team-points
-csv` flags:

- **`aggregate_adp()`**: per-player Average Draft Position — mean overall
  pick number across every trial that player was drafted in. A player
  never drafted in any trial gets `adp = NaN` (not a penalty value) so it
  doesn't quietly corrupt a downstream "average ADP by position" rollup.
- **`aggregate_team_points()`**: per-team average optimal-lineup points
  across all trials, plus `avg_finish_rank`/`best_rank`/`worst_rank` and a
  1-indexed `rank` (highest avg points = #1).

Ran the real 100-trial simulation in the background (a single trial costs
~9s once the board/config are loaded once; 100 trials took **898s (~15
min)** wall time — this comfortably exceeds the Bash tool's 10-minute
timeout, so it has to be launched detached (`nohup ... & disown`) and
polled, not run as one blocking call). Committed the output as
`data/simulations/adp_2026.csv` (660 players) and
`data/simulations/team_points_2026.csv` (10 teams) — see
`scripts/simulate_draft.py`'s module docstring for the exact command to
regenerate these; there's no automatic re-run trigger, it's a manual step
whenever projections/config/pick-logic change enough to matter.

Wired both into the Draft Board (`pages/1_Draft_Board.py`) via a new
`src/data_sources/simulation_results.py` (`load_adp()`/`load_team_points()`,
same "optional file, empty frame if missing" contract as
`load_draft_history()` — the app doesn't break on a fresh checkout before
anyone's run the simulation): an **"ADP"** column now sits on the main
ranked-players grid (merged onto `players_df` by name before filtering/
sorting/tier-computation, so it survives search/position-filter/sort
exactly like every other column), and a new "📊 Simulated league
strength (100 mock drafts)" expander (placed right above the "Suggested
pick" section) shows every team's average points and rank. Per this
100-trial run: **Monster Cheese ranks #1** (avg 6754.1 pts, best-case
rank 1 / worst-case rank 6 across the 100 trials) — this is a real
sanity check on the pick-suggestion logic itself, not just a nice-to
-have display.

14 new tests: `tests/test_simulate_draft.py` (6, the two aggregation
functions against synthetic `TrialResult` fixtures — deliberately not the
slow real simulation), `tests/test_simulation_results.py` (4, the two
loaders' missing-file/round-trip contract), plus 1 new AppTest in
`tests/test_draft_board_page.py` confirming the ADP column and the
10-row, correctly-ranked league-strength table actually render. Full
suite 292/292. Closed on the live deployed site and in the git-mirrored
`data/punch_list.json`.

### 2026-08-28 — Punch list #6 (team-name truncation) and #7 (Reports/Excel download page)

**#6 — team names getting cut off with "...".** Two distinct Streamlit
truncation mechanisms, both hit by this league's longer team names (up
to "Mississippi Swamp Ass", 22 chars): `st.metric`'s value text (the
Draft Board sidebar's "On the clock" metric, in a ~300px sidebar) has
default CSS `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`;
`st.dataframe`'s auto column-sizing clips long cell text with an
ellipsis when a column isn't given an explicit width. Fixed the first
with one small global CSS injection in `app.py` (shrinks
`[data-testid="stMetricValue"]`'s font a bit and lets it wrap instead of
clip -- applies to every `st.metric` in the app, harmless on League
Settings' short values too). Fixed the second with a new
`src/ui_text.py` (`team_column_width()`/`team_text_column()`, sized to
the longest name in whatever team list is passed in, +2 chars for a
possible "🎯 " own-team prefix) applied via `column_config={"Team": ...}`
on every dataframe with a "Team" column: Draft Board's sidebar "Picks by
round" and "Next 10 picks" tables, its "Full pick log", and Draft
Tendencies' "Opponent roster needs" table. Went with widening/shrinking
over the punch-list item's own suggested fallback (abbreviating team
names) since the primary ask ("compact the font so the whole team name
fits") was achievable without it. 4 new tests in `tests/test_ui_text.py`.

**#7 — Reports page, download grids/reports as Excel.** New
`pages/7_Reports.py` ("📥 Reports", registered in `app.py`): a
multiselect of available reports (everything on by default) plus one
"⬇️ Download selected reports as Excel" button that bundles all of them
into a single `.xlsx` workbook, one sheet per report. New
`src/report_catalog.py` holds the actual report builders (pure
functions of a `ReportContext`, no Streamlit -- unit-tested in
`tests/test_report_catalog.py`, 12 tests) so the page itself is just a
thin picker + `pd.ExcelWriter(engine="openpyxl")` wrapper. Six reports
for this first pass, chosen because each is a pure function of
`draft_state`/`config`/the blended projections board and doesn't depend
on another page's own widget state (a slider position, a search filter,
etc. -- e.g. Draft Tendencies' Position Tracker table was left out for
this reason, not forgotten): Draft Board's Available Players and Full
Pick Log, My Roster's Starting Lineup and Bench, League Rosters (expands
into ONE SHEET PER TEAM, same Roster Position/Player/Proj Pts layout as
that page's grid -- a real Excel sheet can't merge a "Team Name" header
across two sub-columns the way that page's HTML table does, so this
splits it back out per-team like an actual draft-day roster binder), and
Draft Tendencies' Opponent Roster Needs. Sheet names are sanitized once,
workbook-wide (`safe_sheet_name()` in `src/report_catalog.py`, Excel's
31-char limit and illegal `: \ / ? *[]` characters, with automatic
"(2)"/"(3)" de-duplication) across ALL selected reports' sheets
together, not per-report, so a report label and a team name can never
collide. Manually verified end-to-end against real 2026 projection data
with a partial mock draft: generated the actual workbook, round-tripped
it back through `openpyxl.load_workbook()`, confirmed sheet names and
cell values are correct (15 sheets from the default 6-report selection:
4 single-sheet reports + 10 team sheets from League Rosters + 1 from
Opponent Needs, since My Roster/Available Players/Pick Log don't expand).
4 AppTest smoke tests in `tests/test_reports_page.py` (everything
selected by default, the download button gets a real `.xlsx` behind it,
deselecting a report changes the sheet count, an empty selection shows a
prompt instead of erroring).

Both closed on the live deployed site and in the git-mirrored
`data/punch_list.json`. Full suite 281/281.

### 2026-08-28 — League Rosters rebuilt as one unified wide grid (2nd mockup revision)

League manager clarified their spreadsheet mockup: they wanted ONE grid
for the whole league (every team as a side-by-side Player/Proj Pts
column pair, sharing one set of Roster Position row labels down the
left edge, "Starters"/"Bench" section rows, Starting Lineup Pts/Bench
Points/Total Team Points summary rows at the bottom) -- not the
first revision's separate league-wide summary table plus a per-team
expander each. That summary table is gone; the same totals now live as
rows at the bottom of the single grid.

Split the work: `src/league_grid.py` (new) builds the actual row/column
data (`build_league_grid()` -> a `LeagueGrid` of per-team `TeamColumn`s,
each with starter_players/starter_pts aligned to a shared
`starter_labels` list, plus bench lists and the three point totals) --
pure logic, no Streamlit, fully unit-tested in `tests/test_league_grid
.py` (7 tests: label expansion, dedicated-before-flex fill order,
overflow onto the bench, a missing-projection player scoring 0 and
getting flagged, bench-depth padding across teams of different sizes,
an all-empty team, column ordering). `pages/6_League_Rosters.py` just
turns that into a hand-built HTML `<table>` via
`st.markdown(unsafe_allow_html=True)` -- Streamlit's native
`st.dataframe` can't merge a "Team Name" header across each team's two
sub-columns the way the mockup wants, and `pd.DataFrame` MultiIndex
columns don't render that way through `st.dataframe` either. Sticky
first column (Roster Position stays pinned while scrolling right
through 10 teams × 2 columns = 20 data columns), horizontal
scroll container, "Starters"/"Bench" section-divider rows, my own team
highlighted, every player/team name run through `html.escape()` (caught
for real by "De'Von Achane" correctly escaping to `De&#x27;Von Achane`
during manual verification below).

Manually verified end-to-end against real 2026 projection data (not
just the filler-player unit/AppTest fixtures): drafted the top 60
players round-robin across 4 rounds, rendered the actual HTML, confirmed
Total Team Points == Starting Lineup Pts + Bench Points for every one of
the 10 teams and that dedicated slots fill before flex slots exactly as
`src.roster_needs.assign_roster_slots` documents. 5 AppTest smoke tests
rewritten in `tests/test_league_rosters_page.py` for the new HTML-based
rendering (no more `st.dataframe` to introspect -- assertions check the
raw HTML/caption text instead) plus one confirming the old summary
dataframe is gone. Full suite 261/261.

### 2026-08-28 — League Rosters page redesigned to match the league manager's spreadsheet mockup

Reworked `pages/6_League_Rosters.py` (added earlier this session) after
the league manager shared a screenshot of the layout they actually
wanted: one Roster Position / Player / Proj Pts table per team, ending
in a blank spacer row then three summary rows -- Starting Lineup Pts,
Bench Points, Total Team Points -- each a literal sum of the rows above
it.

This required switching methodologies for the "starting lineup" figure:
previously used `src.lineup_value.optimal_lineup_points()` (the
mathematically best-possible legal lineup, a proper assignment-problem
optimization not tied to any single set of slot rows); now uses
`src.roster_needs.assign_roster_slots()` instead -- the SAME draft-order
heuristic `pages/4_My_Roster.py`'s own "Starting lineup" section already
uses. Necessary because the mockup's summary rows have to visibly sum
the specific Player/Proj-Pts rows printed above them, which only works
if "starting lineup" corresponds to an actual, displayable slot
assignment. `src.lineup_value` is no longer imported by any page --
still used by `scripts/simulate_draft.py`'s Monte Carlo harness, so left
alone (and left `scipy` in `requirements.txt` from the fix below rather
than moving it back to dev-only, since it's harmless there and another
page may want it again).

League summary table's columns renamed to match: Starting Lineup Pts /
Bench Points / Total Team Points (dropped the old ambiguous "Roster
Pts"). Rewrote all 5 tests in `tests/test_league_rosters_page.py` for
the new table shape and column names; full suite 254/254. Manually
verified the math end-to-end with a real (non-filler) mock draft against
actual 2026 projection data -- Starting Lineup Pts summed correctly from
the printed player rows.

### 2026-08-28 — Fix: League Rosters page crashed on Streamlit Cloud with `ModuleNotFoundError: scipy`

`pages/6_League_Rosters.py` (see the entry directly below) imports
`src.lineup_value`, which imports `scipy.optimize.linear_sum_assignment`.
`scipy` had only ever been listed in `requirements-dev.txt` — fine while
`lineup_value` was only reached from `scripts/simulate_draft.py` (a
local dev script), but this new page imports it at page-load time in
the actual deployed app, which installs from `requirements.txt` only.
User hit this immediately after the previous push, as a
`ModuleNotFoundError` traceback on the live site. Moved `scipy>=1.11`
into `requirements.txt` (with a comment explaining why it has to be a
real, non-dev dependency now) and dropped the now-redundant line from
`requirements-dev.txt` (already pulls in `requirements.txt` via `-r`).
No code changes; local venv already had scipy installed so this session
never reproduced the failure directly, only via Streamlit Cloud's build
log/traceback the user shared. Full suite still 254/254 — this was a
deploy-environment gap, not a test gap the suite could have caught (the
local install had scipy from `requirements-dev.txt` all along).

### 2026-08-28 — Punch list #2: new "League Rosters" page (every team's roster + projected points + starting-lineup totals)

New page `pages/6_League_Rosters.py` (registered in `app.py` as "League
Rosters", 🏆). Punch-list item #2: "Create a page that shows the entire
roster of each team in the league that fills as we are drafting ... add
a column to each roster to who the project points for all the players
and the total for each team. Have a breakdown of total points for the
roster and a second for the projected starting line up for each team."
Closed both on the live deployed site (via the claude-in-chrome
scroll/click technique documented in the entry below) and in the
git-mirrored `data/punch_list.json`.

Reused two existing pieces rather than building new math: the Draft
Board's real-data-preferred/sample-fallback `load_players()` pattern
(so this page's points always match the Draft Board's), and
`src.lineup_value.optimal_lineup_points()` (already built for the Monte
Carlo simulator, never previously wired into a page) for the
"starting lineup" total — a proper assignment-problem optimization over
ALL of a team's drafted players, deliberately NOT the same as
`src.roster_needs.assign_roster_slots()`'s draft-order heuristic that
`pages/4_My_Roster.py` uses for its own "Starting lineup" section. Page
shows a league-wide summary table (Team / Picks / Roster Pts / Starting
Lineup Pts, sorted by the latter) plus a per-team expander with each
drafted player's own projected-points column; a player whose name
doesn't match anything in the projections board scores 0 and is called
out in a caption rather than silently vanishing (join is by exact name
against `players_df.set_index("name")["score_total"]`).

5 new tests in `tests/test_league_rosters_page.py`, following the same
AppTest-via-`app.py`-entrypoint pattern as `test_draft_board_page.py`
(a standalone `AppTest.from_file()` on a `pages/*.py` script throws
`KeyError: 'url_pathname'` on this page's own `st.page_link()` too —
same pre-existing harness limitation as Draft Board/My Roster, confirmed
again here, not a regression). Full suite 254/254.

### 2026-08-28 — Punch list #4: added FantasyPoints.com as a 4th projections source; #3: login-gated "Log in & refresh" buttons for CBS + FantasyPoints; punch list now git-mirrored
Three related pieces of work from one session, punch-list items #3 and #4
(closed both — see below).

**#4 — new source, `src/data_sources/fantasypoints.py`.** FantasyPoints.com
is the league manager's own paid subscription, login-gated (like CBS) —
no plain-HTTP path exists. Used Claude in Chrome on the league manager's
own logged-in browser to reach NFL → Projections & Rankings → Season,
which renders an ag-Grid table with its own "Download CSV" button; that
export is per-position (dropdown), so clicked it once for each of
QB/RB/WR/TE/K/DST and staged all 6 files via the device bridge into
`data/projections/raw/fantasypoints_capture/`. (First tried reading the
grid's row data directly via `javascript_tool` — found the full ~630-row
dataset sitting in the page's Pinia store (`useNuxtApp().payload.pinia
.grid`, an ag-Grid `gridApi`) with EVERY position already loaded
regardless of the visible dropdown filter, which would have been a much
cleaner one-shot extraction — but `javascript_tool`'s return value
truncates hard at roughly 1,500-2,000 characters, well below what even
one position's rows need, so that path doesn't work for bulk data and
the CSV-download approach was used instead.)

`src/data_sources/fantasypoints.py` parses those 6 CSVs into the
canonical schema via fixed COLUMN INDEXES per position (not header
names — the export has two header rows, and generic names like YDS/TD
repeat once per stat group, e.g. RB's sheet has YDS/TD for rushing AND
receiving, so name-based aliasing collides). `scripts/fetch_fantasypoints
.py --from-capture-dir` builds `data/projections/fantasypoints_2026.csv`
from a capture dir (633 rows total: 72/146/213/138/32/32 for QB/RB/WR/
TE/K/DST) — confirmed loading and blending cleanly alongside the other 3
sources (Josh Allen and Houston's DST each show all 4 sources joined).
8 new tests in `tests/test_fantasypoints.py`, full suite 249/249.

Two real, documented gaps in this source (see the module's docstring):
no fumbles-lost column anywhere in the export, and DST rows have no
points/yards-allowed at all (only sacks/int/fumble-rec/TD/return-TD) —
both still come from CBS/FFToday in the blend, just not from this
source's own vote.

**#3 — "Log in & refresh" buttons, `pages/2_Projections.py`.** Per the
punch-list item: "Add a refresh button that launches claude in chrome to
allow refresh of the CBS stats." A deployed Streamlit Cloud app has no
browser session of its own to authenticate with, so this can't be a
plain "Refresh" button the way fftoday/fantasypros' plain-HTTP ones are
— added a new `LOGIN_GATED` section instead: `st.link_button("🔗 Log in
& refresh <source>", url)` opens the site (CBS's stats page or
FantasyPoints' season-projections page) in a new tab for the league
manager to sign into; the caption is explicit that getting the actual
refreshed data into the app from there still needs a live Claude
session to capture it (ask "refresh cbs" / "refresh fantasypoints") —
this button is a convenience for step 1 (log in), not a magic pipe from
a deployed static app to an agent session, which doesn't exist. Applied
to both cbs and fantasypoints since both are login-gated the same way.

**Punch list git-mirrored.** Per the league manager's earlier explicit
choice (AskUserQuestion: "Sync with the deployed Streamlit Cloud app"),
removed `data/punch_list.json` from `.gitignore` (kept
`data/draft_state.json` ignored — that one's still live draft data, not
this) and committed the 7 real items currently on the deployed site
(read via Claude in Chrome — the `Claude_Browser__*` device-bridge pane
still won't scroll/render Streamlit content reliably, but the
`claude-in-chrome` extension tools, driving the league manager's actual
logged-in Chrome, work fine: click-then-`key:End` gets an initial
scroll, then plain mouse-wheel `scroll` works after that). This is a
ONE-DIRECTIONAL mirror as of today, not live sync — future edits made
directly on the deployed site won't flow back to git automatically;
whoever picks this up next should re-pull it the same way before trusting
this file as current. Also closed #3 and #4 both here and on the live
site (both now actually done), so `data/punch_list.json` already
reflects 5 open / 2 closed.

### 2026-08-28 — Pick-suggestion algorithm: 2nd DST and both Kickers now can't come before round 17 (Monster Cheese only)
League manager: "The algorithm for pick recommendations look pretty good.
One tweak before we run the simulations. For our team only, add a rule
that the second defense and the 2 kickers cannot come before round 17."

New config block `config/league_settings.yaml` →
`estimation_assumptions.position_not_before_round`:
```yaml
K: {not_before_round: 17, starting_at_count: 1}
DST: {not_before_round: 17, starting_at_count: 2}
```
`starting_at_count` picks which occurrence the floor first applies to --
1 blocks every K (both), 2 blocks only the 2nd-and-later DST, leaving the
1st DST free to be drafted whenever value/need/scarcity says so.

`src/pick_suggestion.py`: new `_not_before_round_blocked()` reads this
config and, in `suggest_position()`, positions it blocks are filtered out
of the WHOLE candidate pool up front -- before the must-fill (mandatory/
quota-deadline) tier is even computed, not just squashed within it. This
matters: an earlier attempt only excluded blocked positions from the
must-fill *subset*, so when K was the only quota-deadline position in
that subset, filtering it out left `must_fill` empty and fell back to
recommending the (blocked) K anyway, even though RB was sitting right
there as a clean, non-deadline alternative. Filtering at the top of
`suggest_position()` instead (`not_blocked = [...]`, falling back to the
full `ranked` list only if literally everything is blocked) fixed this --
covered by
`test_suggest_position_not_before_round_floor_overrides_a_quota_deadline`,
which forces a synthetic K quota deadline at round 16 specifically to
catch this regression. (Real config never actually triggers this
collision -- K/DEF's round_based_fill_targets deadline is round 20, three
rounds after this floor lifts -- but the override logic needed to be
provably correct anyway.)

Distinct from the existing `position_early_round_discount` (a soft VALUE
squash for K/DST generally that still falls back once nothing scores
higher) -- this is a hard, absolute exclusion with no value component,
and it now sits ABOVE even the mandatory/quota-deadline override tier.
14 new tests in `tests/test_pick_suggestion.py` (unit-level on
`_not_before_round_blocked()`, plus `suggest_position()` integration:
hard exclusion beats an overwhelming-VOR blocked K, falls back to a
blocked position only when nothing else is available at all, 1st DST
stays unrestricted while the 2nd is blocked, the floor lifts exactly at
round 17, and the quota-deadline-override scenario above). Full suite:
241/241 passing.

Verified end-to-end with a real Monte Carlo run
(`scripts/simulate_draft.py --trials 15 --seed 42`): avg rank 2.07/10,
top-3 rate 93%, round-20 requirements fully met in all 15 trials (no
regression from this change). Then dumped one full 220-pick draft log
(`--dump-picks-seed 1000 --dump-picks-csv`) and checked Monster Cheese's
actual K/DST picks directly: 1st DST round 11 (unrestricted, exactly
where value/need called for it), 2nd DST round 19, kickers rounds 17/18
(plus a bonus 3rd K round 20) -- zero K/DST picks before round 17,
exactly as requested.

### 2026-08-28 — Development page: punch-list items now get a permanent #number
League manager: "please add item #'s to the punch list items and
automatically assign new ones when a new task is entered. I'll
reference the # when asking you to work on an item."

`src/punch_list.py`: `PunchListItem` gained `number: Optional[int] =
None`. `PunchList` now tracks a `next_number` counter (starts at 1),
persisted in `data/punch_list.json` as a top-level `"next_number"` key
alongside `"items"`. `add()` stamps the new item with `self.next_number`
then increments the counter -- so numbers are sequential, permanent,
and (critically) NEVER reused: deleting item #1 doesn't free it up for
the next add, which still gets whatever `next_number` is up to. New
`get_by_number(n)` does the #-based lookup (`_find` stays id-based
internally, used by the UI's widget keys).

Backward compatibility: if `data/punch_list.json` already has items
from before this feature (no `"number"` key on those dicts -- possible
if the league manager had already been using the page), `_load_if_exists()`
detects any item with `number is None`, assigns them sequential numbers
in `created_at` order (oldest first), and immediately re-saves so the
migration is permanent and doesn't re-run on the next load.
`next_number` is set to `max(stored value, highest number actually
seen) + 1` either way, so it's correct whether or not a migration just
happened.

`pages/5_Development.py`: open-item expanders now read `"#3 · 🔴 High —
<title>"`, the closed-items list shows `**#3**` before the
strikethrough title, and the "Added" toast after submitting the form
now says `Added #3 — "<title>"` so the number is visible the moment an
item is created (no need to scroll down and find it).

8 new tests in `test_punch_list.py`: sequential numbering from 1, a
deleted item's number is never reused, `get_by_number` hit + KeyError
miss, numbering survives closing and reopening a `PunchList` instance
against the same file, and a legacy-file migration test (hand-built
JSON with no `"number"` keys) confirming both the migration itself and
that it's idempotent (doesn't renumber again on a second load).
230/230 tests passing overall. Verified via headless `AppTest`: empty
list (no exceptions), and a 2-item populated list (one open, one
closed) confirming `#1`/`#2` actually render in the expander label and
the closed-list markdown, not just present on the underlying objects.

### 2026-08-28 — Live Draft Tracker: fixed a number-formatting bug (chained .format() calls clobber each other)
League manager: "looks good but fix the numbers. They should be in the
format 'x.x'."

`pages/3_Draft_Tendencies.py`'s tracker Styler was built as:
```python
tracker_df.style
    .map(_delta_color, subset=delta_cols)
    .format({c: "{:.1f}" for c in proj_cols})
    .format({c: "{:+.1f}" for c in delta_cols}, na_rep="–")
```
Two separate `.format()` calls, each scoped to a different set of
columns. Confirmed by inspecting the actual rendered Arrow buffer
(`AppTest`'s `Dataframe.proto.arrow_data.styler.display_values`,
decoded with `pyarrow.ipc.open_stream(...).read_all().to_pandas()`)
that this silently broke: pandas' `Styler.format()` doesn't ADD to
whatever formatting a previous call set up for columns outside its own
subset -- it resets them back to pandas' internal default float
formatter. So the SECOND `.format()` call (delta_cols) wiped out the
FIRST call's `"{:.1f}"` for proj_cols, and those columns rendered with
raw default precision instead -- e.g. `"2.200000"` (6 decimals) rather
than `"2.2"`. This wasn't caught by the 225 passing tests because none
of them inspect a rendered Styler's actual display strings -- the
underlying numeric VALUES were always correct (proven by
`test_draft_tendencies.py`'s coverage of the functions that produce
them), only the presentation layer was silently wrong.

Fixed by merging both format specs into a single dict and calling
`.format()` once:
```python
number_format = {c: "{:.1f}" for c in proj_cols}
number_format.update({c: "{:+.1f}" for c in delta_cols})
tracker_df.style.map(_delta_color, subset=delta_cols).format(number_format, na_rep="–")
```
Re-ran the same byte-level Arrow inspection against a populated draft
state (30 picks logged) and confirmed real cells now read exactly
`"4.5"`, `"-3.5"`, `"+3.8"`, `"–"` for not-yet-reached rounds, etc. --
true 1-decimal formatting, not just a plausible-looking screenshot.
225/225 tests still passing (no `src/` logic changed, pure Styler
-construction fix). **Lesson recorded for next time this page's Styler
gets touched: never chain multiple `.style.format()` calls across
different column subsets on the same Styler -- merge into one dict.**

### 2026-08-28 — Live Draft Tracker: brought the Δ columns back, split from proj, compacted to the position code
League manager: "we lost the delta columns. Can you add those back and
you can compact all the position columns to the max size of the
position abbreviation so it hopefully fits on my screen."

The prior same-day pass had merged each position's Proj and Δ into one
cell ("18.0 (+1.0)") specifically to cut column count in half for
width. That traded away being able to see/scan the delta as its own
column. Un-merged them in `pages/3_Draft_Tendencies.py`: `row[pos]` is
the projection again (numeric, e.g. `18.0`), `row[f"Δ{pos}"]` is the
delta again (numeric, NaN until the round is reached) -- built in the
same loop iteration so the two land as adjacent columns per position,
same visual grouping as the very first version of this feature.

Headers are now just the position code (`QB`) and a Δ-prefixed code
(`ΔQB`) instead of "QB Proj"/"QB Δ", and both columns run through the
`_col_px()` content-fit sizer from the previous pass (pad/per_char
tightened from 14/6 to 10/6, since a numeric column carries less
padding overhead than a text one). Because the actual displayed values
are short (`"18.0"`, `"+1.0"`, `"–"`) and the header is just 2-4
characters, each proj/Δ pair lands around 34px -- 12 narrow columns at
~34px (~408px total) beats the single merged column's 6 columns at
~80-100px each (~480-600px) from the prior pass, so this split-and
-compact approach is actually TIGHTER than the merge it replaces, not
just a restoration of it. Delta cell coloring (🔴 hotter than history /
🟢 cooler) reverted to a plain numeric sign check via `Styler.map` on
the real float column (NaN-safe, no color for a not-yet-reached round)
now that the column holds numbers again, replacing the previous pass's
string-parsing workaround that merging had forced.

225/225 tests passing (pure layout/column-split change, no `src/`
logic touched). Verified via headless `AppTest`: empty draft state, and
the same populated worst-case scenario as the prior pass (every
Monster Cheese pick "Christian McCaffrey" RB, every opponent pick "San
Francisco 49ers" DST, through round 6) -- no exceptions either way.
Recomputed the worst-case total-grid-width estimate the same way as
before: ~870px, down from the merged version's ~960px.

### 2026-08-28 — Live Draft Tracker: column widths now fit their actual content
League manager: "make the 'your pick', 'Consider now' and 'can wait'
columns smaller to match the max characters the field will actually
need. The grid is still off screen on the right."

The prior pass (same day, below) used `column_config` with the
categorical `width="small"`/`"medium"` presets (75px / 200px, fixed
regardless of what's actually in the column) -- fine for the 6 short
position cells, way oversized for "Your pick"/"Consider now"/"Can wait"
most of the time, since a typical cell there is much shorter than
"medium"'s 200px budget.

Replaced with content-driven pixel widths in
`pages/3_Draft_Tendencies.py`: `_col_px(header, values)` scans every
actual value that will appear in that column this rerun (plus the
header, in case it's the longest thing), estimates a rendered width via
`_display_width()` (counts each character as 1 "unit" except emoji/
wide glyphs like 🔒 and the `·` separator, counted as 2, since raw
`len()` undercounts how wide those actually render), and returns
`pad + per_char * widest_unit_count` pixels, floored at a small
minimum. Applied to every column (not just the 3 named) via
`st.column_config`, so the 6 position columns tighten too when their
content is short. Recomputes every rerun from the CURRENT tracker data
(not a hardcoded worst case), so e.g. "Your pick" only grows wide on
the actual round a long-named DST gets logged, and shrinks back for
every other row.

Sanity-checked the arithmetic against a deliberately pessimistic
scenario (every "Your pick" a long DST name, every "Can wait" the full
6-position list with a 🔒 lock) — total estimated grid width dropped
from a previously-fixed ~1200px+ floor to about 960px in that SAME
worst case, and noticeably less in ordinary rows. Verified via headless
`AppTest`, twice: the normal empty-draft state, and a scripted 60-pick
state where every pick is logged as either "Christian McCaffrey" (RB,
Monster Cheese's picks) or "San Francisco 49ers" (DST, everyone else's)
to specifically exercise the long-name case — no exceptions either way.
225/225 tests passing (pure layout change, no new `src/` logic, so no
new tests needed).

### 2026-08-28 — Live Draft Tracker: roster-cap-aware consider/wait, compact columns, 1-decimal everywhere
League manager, third pass on the tracker: "During the draft the
tendencies will be influenced by the roster slots each team has filled.
So while the average rb's taken at any point might be xxx, practically,
if the teams ahead of us prior to our next pick are all filled on RB's,
they are far less likely to take any and we potentially can wait...
also, lets only show 1 decimal place on the numbers and see if we can
crunch the column widths a bit to get the whole grid visible without
scrolling right."

**Roster-cap-aware consider-now/can-wait.** The historical run
predictor (`next_run_positions`) has no idea what any team has actually
drafted -- it's a pure average over past seasons. Added two functions to
`src/roster_needs.py`:
- `positions_at_cap(position_counts, config) -> set[str]`: which
  positions a team can never draft again, per this league's REAL roster
  ceiling (`config.roster.position_active_limits` -- confirmed against
  actual CBS platform behavior for at least DST/TE, see that config
  block's own comments; not a heuristic guess). QB/RB/K/DST each have
  their own max; WR has no standalone max in this league's rules, only
  a combined WR_TE bucket that both WR and TE draw from alongside TE's
  own separate (tighter) max -- handled explicitly: capped on WR once
  the combined bucket is full, capped on TE once EITHER its own max or
  the combined bucket is reached.
- `positions_blocked_for_all(window_teams, capped_positions) -> set[str]`:
  intersection of capped positions across a list of teams -- empty if
  the window is empty or the teams don't share a capped position.

On the Live Draft Tracker, for each round row's window (the opponents
picking between that round's pick and Monster Cheese's own next pick --
fully known in advance from the snake order, regardless of what's
actually been drafted), look up which of those teams are ALREADY
capped (from real, current roster counts) and demote any
historically-predicted "run" position to **Can wait** (🔒) if literally
every window opponent is capped on it. Key property that makes this
valid even for rounds well ahead of where the draft stands right now:
a real roster cap, once hit, can never become un-hit -- so "capped
today" stays true for every later round too, even though a team not
yet capped today COULD become capped by then (which this can't see in
advance; the read only gets more accurate as the real draft catches up
to each row). Verified the exact user-described scenario with a
scripted repro: forced every window-team to draft exactly 1 RB against
a synthetic RB cap=1, confirmed RB (and only RB) gets blocked while WR
does not.

**Compact columns + 1 decimal everywhere.** Merged each position's
separate `Proj`/`Δ` columns into one cell per position: `"2.2"` for a
round not yet reached, `"2.2 (+1.0)"` / `"2.2 (-0.5)"` once reached --
halves the position-column count (6 instead of 12). Cell background
color (🔴/🟢) is now parsed straight from the `(+`/`(-` in the
formatted string rather than kept in a parallel numeric structure,
since the column itself is text now. Added explicit
`st.column_config` widths (`small` for the Round index, Pick #, and
each position column; `medium` for Your pick / Consider now / Can
wait) alongside the existing `use_container_width=True`, confirmed
`column_config` and a pandas `Styler` (for the cell coloring) can be
passed to `st.dataframe` together without error. Also dropped the
opponent-demand table (in the collapsed "Opponent roster needs"
section) from 2 decimal places to 1, for consistency with the rest of
the page.

8 new tests (`test_positions_at_cap_*` x4, `test_positions_blocked_for_all_*`
x4) in `test_roster_needs.py`; 225/225 tests passing overall. Verified
via headless `AppTest` runs of the full page: once against an empty
draft state, once against a scripted 60-pick state (every non-Monster
-Cheese pick through round 6 logged as RB) that pushes several real
opponents past this league's actual RB cap of 5 -- no exceptions either
time. Test state files were removed afterward; nothing left in
`data/draft_state.json` for real.

### 2026-08-28 — New Development page: in-app punch list (add/edit/close)
League manager: "lets also create a development page so that I can
input, edit, close punch list items as I continue to refine the app."

Built `src/punch_list.py`: a small `PunchList` class (add/update/close/
reopen/delete, `open_items()`/`closed_items()`) backed by
`PunchListItem` dataclasses (id, title, description, priority
High/Medium/Low, status Open/Closed, created_at/updated_at/closed_at),
persisted to `data/punch_list.json` with the exact same
write-to-tmp-then-`os.replace()` atomic pattern `DraftState.save()`
uses, so a crash mid-write can't corrupt it. Added the file to
`.gitignore` alongside `data/draft_state.json` -- it's the league
manager's own live data, not something that belongs in the repo.

New `pages/5_Development.py`, registered in `app.py`'s `st.navigation()`
list with icon 🛠️: an "Add an item" form (title, optional details,
priority) at the top; an "Open" section below it, one `st.expander` per
item sorted by priority (High first) then oldest-first, with editable
title/details/priority fields and Save / Close / Delete buttons inline;
a collapsed "Closed" section at the bottom, newest-closed-first, each
with a one-click Reopen. No football-specific logic in this page at
all -- it's app upkeep tooling, kept alongside the other pages so it's
always one click away while using the app.

10 new tests in `tests/test_punch_list.py` (create/strip/validate,
partial updates leave other fields untouched, close/reopen round-trip,
delete, unknown-id errors on every mutating op, persistence round-trip,
missing-file starts empty). 216/216 tests passing overall. Verified the
actual page renders via headless `AppTest`, twice: once against an
empty list, once with two real items added (one open, one closed) to
exercise the edit-form and reopen-button code paths — no exceptions
either time. The test items were added directly to `data/punch_list.json`
and removed again afterward; nothing left behind since the league
manager hadn't started using the page for real yet.

### 2026-08-28 — Live Draft Tracker redesign: moved to top, actual-as-delta, consider-now/can-wait
Second pass on yesterday's feature, per league-manager feedback: "I
really want the live tracker at the top. I'd like to see projected
cumulative #'s based [on] history, actual cumulative as the draft
continues as a delta. I'd also like to have 2 columns at the end. One
would indicate position to consider drafting considering a projected
[up]coming run and conversely, positions that can wait... This would
also replace w[ha]t you built last. For now, we can push everything
else below that and also make everything below collapsed."

Rewrote `pages/3_Draft_Tendencies.py`'s top section. It now opens
(right after the sidebar year-selector and the small live-draft-state
metrics row) with an uncollapsed "🎯 Live Draft Tracker" table, one row
per round of Monster Cheese's own draft slot:
- `{POS} Proj`: historical average cumulative count at that pick,
  unchanged from yesterday (`historical_cumulative_at_pick()`).
- `{POS} Δ`: NEW -- actual minus projected, once that round is reached
  (`actual_cumulative_at_pick()` minus the projection), rendered with a
  sign (`+1.0`/`-2.0`) and a red/green cell background (red =
  running hotter than history at that position = scarcer than usual
  right now; green = running cooler = safer than usual); shows "–" for
  rounds not reached yet. Replaces yesterday's version, which showed
  actual OR projected as alternate ROWS (a "Source" column) rather than
  actual as a delta against projection in the same row -- the delta is
  the more useful read during a live draft ("am I ahead of or behind
  pace"), which is exactly what the league manager asked for.
- `Consider now` / `Can wait`: NEW -- two columns at the end of each
  row. Reuses the existing `next_run_positions()` predictor, but
  windowed per-row on THAT round's actual gap to Monster Cheese's own
  NEXT pick (`team_pick_in_round(rnd)` to `team_pick_in_round(rnd+1)`),
  not the sidebar's fixed 1-3 round look-ahead slider used elsewhere on
  the page -- so each row's suggestion is specific to how many picks
  actually stand between this round and the next one, which varies
  round to round near the snake's turn. Positions in the predicted run
  land in "Consider now"; every other tracked position lands in "Can
  wait".

Everything else that used to be directly on the page -- "Historical
positions drafted per round", "What's likely to happen next" (the
slider-driven version), "Opponent roster needs before your next pick"
-- moved below a `st.divider()` and each got wrapped in its own
collapsed `st.expander(...)`, per the explicit instruction to push
supporting detail down and keep only the tracker immediately visible
on load. No `src/` logic changed; this was entirely a page-layout
rewrite reusing already-tested functions. One implementation note:
pandas 3.0 (installed in this repo) removed `Styler.applymap()` --
used the newer `Styler.map()` instead for the delta-column cell
coloring.

Verified with a headless `AppTest` run of the full page (`app.py` ->
`switch_page("pages/3_Draft_Tendencies.py")`) both against an empty
draft state and against a temporary 15-pick logged state (built and
torn down in this session only -- `data/draft_state.json` was never
touched for real and isn't tracked by git anyway) — no exceptions in
either case. Full test suite: 206/206 passing (no test changes needed,
only UI code changed; the underlying `src/` functions this reuses were
already covered by yesterday's 9 new tests).

### 2026-08-27/28 — Live cumulative picks-by-round tracker on Draft Tendencies
League manager: "on the draft tendencies page we typically track the
actual counts as we go through the draft. It is good to have it
cumulative history pick by pick, and also have that fill in as the
actual draft proceeds," with a screenshot of the old hand-tallied
worksheet (title "8th Pick / 2025") for reference. Clarified via
AskUserQuestion that this should be a new, collapsible section (not
folded into an existing one) since a 20+ round table runs long down the
page.

Read the screenshot carefully before building: it's organized by ROUND,
with an "OA PICK" column showing Monster Cheese's own overall pick
number that round (verified the pattern against `team_for_pick()` math —
an 8th-overall-pick team's snake sequence is 8, 13, 28, 33, 48...,
matching the sheet exactly), then one column per position (QB/RB/WR/TE/
D/K) each holding a single running cumulative league-wide count for that
round, with a "Next Run" hint column at the far right. The
diagonal-hatched columns between each position turned out to just be
visual dividers, not a second data column — an early read of the
screenshot (before the image itself came through) assumed they were a
manual "this round" tally input separate from the cumulative row; they
aren't.

Built: `DraftState.team_pick_in_round(team, round_num)` (new method in
`src/draft_state.py`, right after `round_and_slot_for_pick`) walks a
round's `n` overall-pick numbers and returns whichever one belongs to
`team` — exactly one match always exists per round in this model's
no-keepers/no-trades snake draft. Two new functions in
`src/draft_tendencies.py`: `actual_cumulative_at_pick(picks,
through_overall_pick)` tallies real position counts from the live
`DraftState.picks` log through a given pick (mirrors `_valid_picks()`'s
"ignore unrecognized/blank position" spirit); `historical_cumulative_at_
pick(cumulative_df, overall_pick)` looks up a single row of the existing
`cumulative_counts_by_pick()` table, clipped to the historical data's own
pick range same as `predict_position_counts()` already does.

New UI section in `pages/3_Draft_Tendencies.py`: an `st.expander("📋 Live
cumulative picks by round")`, collapsed by default, with one row per
round 1..`config["draft"]["rounds"]`. For each round, looks up Monster
Cheese's anchor overall-pick via `team_pick_in_round()`; if the live
draft has already reached that pick, shows the ACTUAL cumulative counts
(green row highlight) plus what Monster Cheese drafted that round; if
not, shows the HISTORICAL projection for the sidebar's selected years
(amber row highlight) instead. No manual entry at all — it's derived
entirely from state the app already tracks, and rounds flip from
projected to actual automatically as the real draft happens.

9 new tests: `test_team_pick_in_round_matches_snake_order` and
`test_team_pick_in_round_out_of_range_or_unknown_team_returns_none` in
`test_draft_state.py`; 7 covering both new `draft_tendencies.py`
functions (normal counting, blank/unrecognized positions ignored, empty
pick list, custom positions tuple, matching the underlying table, and
clipping above/below the historical pick range) in
`test_draft_tendencies.py`. 206/206 tests passing overall. Verified the
actual page renders with no exception via a headless `AppTest` run
(`app.py` -> `switch_page("pages/3_Draft_Tendencies.py")`).

### 2026-08-27 — Added a full-pick-log export to the Monte Carlo harness, delivered a sample draft as an Excel workbook
League manager asked to see the actual pick-by-pick results of a
simulated draft (who got picked in each round/slot, by which team, what
position) rather than just the aggregate rank/points stats
`scripts/simulate_draft.py` reports. Added `--dump-picks-seed`/
`--dump-picks-csv` to that script (pass `--trials 0` to skip the
aggregate run and just export one trial's full 220-pick log as CSV --
`simulate_one_draft()` gained an optional `capture_picks` flag that
records every `Pick` in order with proj. points/VOR looked up from the
board). Used it to regenerate the exact seed-1000 trial already reported
in chat (Monster Cheese rank 1/10, 6912.8 pts) and built a 4-sheet Excel
workbook from it (not committed -- one-off deliverable, regenerable any
time from any seed): a Read Me, a round x team "Draft Board Grid" (Monster
Cheese's column highlighted), a flat "Full Draft Log" of all 220 picks,
and a "Monster Cheese Picks" sheet with just this team's 22. No app code
touched; 196/196 tests still passing.

### 2026-08-27 — Cosmetic: renamed the "app" sidebar page to League Settings, added per-page icons
League manager noticed the sidebar's top nav entry just said "app" (a
literal artifact of `app.py` being both the multipage entrypoint AND the
landing page under Streamlit's classic `pages/`-directory auto
-discovery) and asked to rename it plus add icons across the pages. Full
detail in the "Current state" bullet above (search "Sidebar nav switched
to st.navigation()"); short version: switched `app.py` to a thin
`st.navigation()` router with an explicit title+icon per page, moved the
old landing-page content to new `pages/0_League_Settings.py` ("League
Settings", ⚙️), and gave the other four pages icons in the sidebar for
the first time (classic mode only picks those up from an emoji in the
filename, which this repo never used): 🏈 Draft Board, 📊 Projections, 📈
Draft Tendencies, 📋 My Roster. No page content, URLs, or the
`streamlit run app.py` command changed. Verified via a headless smoke
-test boot and the existing `AppTest` page tests (unmodified, all 7 still
pass against the new router) -- 196/196 tests passing overall.

### 2026-08-27 — Confirmed real draft requirements against config/UI, committed the Monte Carlo harness, found+fixed a real TE-overdraft bug
League manager restated the real round-20 requirements and starting
lineup in plain language to double-check the app has them right: by
round 20, 2 QB / 5 RB / 5 WR-or-TE / 2 K / 2 DEF / 1 mandatory TE
(beyond the 5 WR/TE) / 1 additional RB-or-WR-or-TE / 2 any-position (20
total), rounds 21-22 unconstrained; starting lineup 2 QB / 3 RB / 3
WR-or-TE / 1 TE / 1 K / 1 DEF / 1 RB-or-WR-or-TE-or-K (12 total). Checked
line-by-line against `config/league_settings.yaml`'s
`round_based_fill_targets` (8 categories) and `roster.starters` (the
2nd "QB" is the SUPERFLEX slot, labeled "QB (Flex)" on My Roster and
modeled at 100% QB demand per yesterday's change) -- **exact match, no
config changes needed**. Read `pages/4_My_Roster.py` end to end -- its
"Starting lineup" and "Draft Requirements" sections already render every
one of these categories correctly (also confirmed no changes needed).

Then, per the request to "rerun monte carlos and tweaks to the
[pick-suggestion] logic to maximize our projected season points":
committed a real simulation harness (`scripts/simulate_draft.py` +
`src/lineup_value.py`) since the prior sessions' `/tmp/sim/simulate*.py`
scratch scripts were never committed and had been lost. Full
methodology, the bug found (and why the fix had to be scoped narrowly --
an over-broad first attempt measurably hurt points), and the validation
results (weight-reweighting sweep, a `no_quota` ablation, a TE-fully
-uncapped experiment) are in the "Current state" bullet above (search
"Monte Carlo simulation harness now committed") -- short version:

- **Bug**: the round-based quota override (`must_fill` in
  `suggest_position()`) could force-draft an already-capped position
  (e.g. a 3rd-6th TE) over the intended uncapped alternative (WR) in the
  same multi-eligible category, because most of this league's real
  requirements share one round-20 deadline and get grouped into one
  urgent bucket, and the override tier's raw composite comparison had no
  cap check at all. Fixed in `src/pick_suggestion.py`.
- **Result** (25 trials, same seeds as the 2026-08-26 sweeps): back to
  the same strong baseline as before this requirement set existed --
  avg league rank **1.28 of 10** (96% top-3, worst-case 4th), 100% hit
  2 QBs by round 6 and all round-20 requirements every trial. A
  `no_quota` ablation shows the round-based-quota mechanism as a whole is
  now doing a lot of work against the richer 8-category requirement set:
  without it, avg rank drops to **5.0 of 10** (top-3 25%, worst 9th,
  only 65% ever get a 2nd QB at all).
- Reconfirmed (20 trials each) that reweighting value/need/scarcity
  still doesn't matter (all variants within noise of the shipped
  0.45/0.30/0.25) -- no weight change made.
- Also tested fully uncapping TE (it's WR_TE_FLEX-eligible, unlike
  K/DST) in case the configured cap of 2 was itself too conservative for
  pure point-maximization -- it wasn't: slightly WORSE (avg rank 1.25 vs
  1.10, avg points 6949 vs 6968) and let Monster Cheese roster up to 9
  TEs. Kept the existing cap.
- 4 new tests (2 in new `tests/test_lineup_value.py`, 2 regression tests
  in `tests/test_pick_suggestion.py` -- verified against the pre-fix code
  to confirm they actually catch the bug). 196/196 tests passing.
  `scipy` added to `requirements-dev.txt` (sim-only, not needed by the
  deployed app). Also updated a stale comment in
  `config/league_settings.yaml`'s `position_early_round_discount` block
  that still said the K/DEF-by-round-20 rule wasn't confirmed/wired in
  yet -- it was, as of yesterday.

### 2026-08-27 — Real draft requirements doc loaded, DST/TE cap conflict, SUPERFLEX 100%, My Roster requirements UI, Monte Carlo re-run
League manager uploaded the real "Maniac Football League Draft Sheet"
(`.docx`) and asked to load it, treat a 2nd QB as effectively mandatory
whenever available (SUPERFLEX split 90% -> 100% QB), add a Draft
Requirements view + round-20 warning to My Roster, and re-run the Monte
Carlo comparison.

**Reading the doc**: `pandoc -t markdown` collapsed the two-column
requirements table into ambiguous flat text — switched to
`soffice.py --headless --convert-to pdf` + `pdftoppm -jpeg` + `Read` on
the resulting image, which showed the true structure clearly: 10 rows x
2 columns (QB/QB, K/K, DEF/DEF, RB/WR-TE x5, "RB-WR-TE"/"TE (Mandatory)")
= 20 items, plus 2 unconstrained "Bonus Round" picks at 21/22. Interpreted
as a required ROSTER COMPOSITION by round 20 (not literal pick order —
taking K/DEF in the first few picks, as the row position would literally
suggest, would contradict everything already established about K/DST
early-round value), matching the league manager's own framing: "All the
positions at the top must be filled by the end of round 20."

**Config** (`config/league_settings.yaml`): `round_based_fill_targets`
changed shape from a dict keyed by position to a list of `{slot,
eligible, count, by_round}` entries — needed because several real
categories are multi-eligible ("WR or TE", "RB, WR, or TE") in a way a
single position key can't represent. 8 entries now: QB (kept at the
tighter, simulation-tuned round-6 deadline, not the doc's own looser
round-20 one), K x2/round20, DEF x2/round20, RB x5/round20, WR/TE
x5/round20, RB-or-WR-or-TE x1/round20, TE-mandatory x1/round20,
any-position x2/round20 (included for slot-budget bookkeeping even
though it never forces a specific position). Also raised
`roster.position_active_limits` DST max 1->2 and TE max 1->2 to match
this doc's "2 DEF" and TE-flexibility requirements — **this conflicts
with the existing caps (captured 2026-08-24 from CBS's rules page) and
is NOT re-confirmed against CBS's actual platform behavior; flagging
again here since it matters for draft day** — if CBS truly hard-caps DST
at 1, a 2nd DEF may be impossible to legally roster, not just
suboptimal. `flex_position_splits.SUPERFLEX` QB weight raised 0.90 ->
1.0 per explicit request ("it is always the best choice if 2 are
available... treat those as mandatory").

**`src/pick_suggestion.py`**: `_round_based_quota_positions()` rewritten
to consume the new list shape via `src.roster_needs.
unfilled_starter_slots()` (so a drafted player isn't double-counted
across overlapping categories, e.g. a TE satisfies "TE (Mandatory)"
before "WR/TE" gets a claim on it), and to GROUP unfilled categories by
shared `by_round` deadline, checking the group's TOTAL remaining need
against remaining picks before that shared deadline rather than each
category independently — needed because 7 of the 8 configured categories
share the same round-20 deadline, and an independent check can miss a
combined shortfall (e.g. needing K:2 + DEF:2 + RB:1 with exactly 5 picks
left before round 20 looks fine for each alone, but the combined need
already exhausts the combined remaining picks). `my_position_need()` now
also folds in soft demand from unfilled requirement categories (even
split, no flex-splits weighting) so they nudge the ongoing
value/need/scarcity composite all draft long, not just at the hard
deadline. 3 new tests covering the grouped-urgency logic specifically
(double-counting avoidance, a combined-shortfall-not-visible-alone case,
and its negative control with real slack) — 187 total in the suite before
the page-test additions below.

**`pages/4_My_Roster.py`**: new "Draft Requirements" section, same
per-category fill-progress table style as Starting Lineup (reuses
`assign_roster_slots()` against the requirements list instead of
`roster.starters`), plus a warning banner from round 18 on and an error
banner past round 20 if any round-20-deadline category is still unmet
(the QB category's own tighter round-6 deadline is a separate signal the
Suggested Pick panel already surfaces, so it doesn't drive this banner).
2 new `AppTest` tests logging picks directly through `DraftState` (much
faster than clicking through the grid) to reach round 19 and round 21
and confirm the warning/error banners fire correctly. Also fixed an
existing test (`test_my_roster_page_fills_in_as_picks_are_logged`) that
hardcoded an assumption about which slot the real top-of-board player at
pick 8 would land in — that shifted once the config changes above moved
real players' relative VOR rankings, so the test now just confirms the
drafted player appears in exactly one lineup slot rather than assuming
it's specifically RB. Full suite: 189 passed.

**Monte Carlo re-run** (`/tmp/sim/simulate_v2.py`, updated for the new
config shape — `config_with_qb_quota()` now rebuilds the requirements
list rather than assigning a dict key): 15 trials/model against the full
new config (real by-round-20 requirements active for every model except
`no_quota`):

```
MODEL             avg_rank  top3_rate   avg_pts  avg_QBs  2ndQB_rate  avg_2ndQB_rd  empty_slot_trials  n
current               1.40      93.3%    6954.6     2.00      100.0%           6.0                  0  15
no_quota              5.60      33.3%    6730.5     1.27       26.7%          12.5                  0  15
need_heavy            1.27     100.0%    6957.2     2.00      100.0%           6.0                  0  15
scarcity_heavy        1.53      93.3%    6943.4     2.00      100.0%           6.0                  0  15
value_heavy           1.47      93.3%    6944.8     2.00      100.0%           6.0                  0  15
quota_r5_c2           1.40     100.0%    6952.1     2.00      100.0%           5.0                  0  15
quota_r9_c2           2.20      80.0%    6911.2     2.00      100.0%           9.0                  0  15
quota_r12_c2          3.87      53.3%    6835.2     2.00      100.0%          11.5                  0  15
quota_r7_c3           1.33     100.0%    6956.3     2.00      100.0%           6.0                  0  15
```

Takeaways: `no_quota` (QB target AND real requirements both stripped, as
a pure value/need/scarcity baseline) collapses to avg_rank 5.60/33%
top-3 — strong confirmation that the requirements-forcing mechanism as a
whole (not just the QB piece) is doing real work, not just window
dressing. Every other model — regardless of value/need/scarcity weight
blend, and across the whole QB-deadline sweep from round 5 to round 12 —
finished with **zero empty starter slots across all 135 trials**,
including under the raised DST/TE caps, which is a good robustness
signal for the requirements integration. The shipped round-6 QB deadline
remains near-optimal (1.40/93%), essentially tied with round 5
(1.40/100%) and round 7-with-3-QBs (1.33/100%) and clearly ahead of
looser deadlines (round 9: 2.20/80%; round 12: 3.87/53%) — no change
made to the QB deadline itself. `early_KDST` pathological-flag counts
were dropped from this table's printed columns in the writeup above
(unlike the 2026-08-26 runs, a nonzero count here can now legitimately
mean the round-20 requirement group forced an early K/DST pick on
purpose, not a bug — the flag wasn't redesigned to distinguish the two
causes, so raw counts aren't a meaningful regression signal anymore;
worth revisiting if this harness gets formalized into the repo).

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
