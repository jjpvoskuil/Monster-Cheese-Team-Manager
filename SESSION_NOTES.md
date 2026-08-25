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
- `pytest` — 28/28 passing.
- Deployed to Streamlit Cloud; user confirmed the Draft Board loads
  correctly as of 2026-08-25.
- Known gaps (not blocking): FantasyPros/ESPN blending not done (CBS-only
  for now); `src/data_sources/cbs.py` live draft sync is still a stub,
  manual pick entry is the reliable path; defensive PA/yards-allowed
  tables (only 3 tiers each on CBS's page) not yet re-confirmed with the
  commissioner; no full UI click-through of the Draft Board has been done
  beyond a direct pipeline check; parsing an in-progress/completed draft
  (PLAYER column populated) is not built — only the pre-draft order.

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

## Log

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
