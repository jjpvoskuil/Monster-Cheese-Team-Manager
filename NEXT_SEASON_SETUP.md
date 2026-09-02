# Next-Season Setup Guide

A step-by-step runbook for getting the Monster Cheese Team Manager app
ready for a new draft season — teams/draft order, fresh projections,
pushing everything to GitHub, and testing it before you actually rely on
it live. Written so either you or a future Claude session can follow it
cold, with no other context.

**When to start:** roughly 2–3 weeks before draft day gives enough time
to catch problems (a source's site layout changed, a script broke, the
Chrome extension needs reloading) without being rushed.

**Security note up front:** never paste a GitHub password, personal
access token, or any other credential into a chat with Claude, even if
it seems convenient. Handle GitHub sign-in yourself in Terminal — see
§3 below.

---

## 1. Where everything lives on your Mac

Repo root: **`~/MFL/monster-cheese-team-manager`**
GitHub remote: **`https://github.com/jjpvoskuil/Monster-Cheese-Team-Manager`**

| Path (relative to repo root) | What it is |
|---|---|
| `app.py` | Entry point — run this with `streamlit run app.py` |
| `config/league_settings.yaml` | **Source of truth** for scoring rules, roster requirements, draft order, draft date/time. Edit this, not code, when a league setting changes. |
| `data/draft_state.json` | The live pick log for the current draft. **Delete before every mock draft test and again right before the real draft** — see §6. Gitignored (local-only, never committed). |
| `data/live_sync_status.json` | Live-sync heartbeat file the Chrome extension writes to. Also gitignored, also reset before every draft. |
| `data/source_weights.json` | Per-source trust weights set on the Projections page. Gitignored (local-only). |
| `data/projections/*.csv` | The actual season projection files the app blends together. **The app loads every CSV/XLSX in this folder** — see the year-rollover warning in §4. |
| `data/draft/` | Parsed draft-order JSON per season (`fetch_draft_order.py`'s output). Keep every year's file — don't delete old ones. |
| `data/draft_history/` | Multi-year completed-draft history used for pick-tendency modeling. Keep growing this year over year — add to it, never overwrite. |
| `data/simulations/` | Output of Monte Carlo mock-draft simulations (ADP estimates, simulated league strength). |
| `reports/` | Generated deliverables (e.g. the draft-grades Word doc). Gitignored — these are outputs for you to share, not source. |
| `scripts/` | One-off CLI tools: pulling draft order, pulling projections, running simulations. See §4–5. |
| `tools/live_pick_receiver.py` | The local server that receives live picks from the Chrome extension during a real/mock draft. |
| `tools/chrome_extension/` | The unpacked Chrome extension that watches the CBS draft room and posts picks to the receiver. |
| `pages/` | The Streamlit app's individual pages (Draft Board, Projections, My Roster, League Rosters, Reports, Development, League Settings). |
| `DRAFT_DAY_CHECKLIST.md` | The detailed, tested walkthrough for live draft-day sync specifically — this guide's §6 is a condensed pointer to it. |
| `SESSION_NOTES.md` | Full running history of every bug found/fixed and decision made on this project — read this if something here seems out of date. |
| `docs/draft_insights.md` | Draft-strategy analysis (VOR, positional scarcity) from past work. |
| `NEXT_SEASON_SETUP.md` | This file. |

---

## 2. One-time environment check (skip if your Mac already runs this app)

Only needed on a fresh machine, or if you're not sure the local clone
still works:

```bash
# Confirm the basics are installed
git --version
python3 --version

# Clone the repo (skip if ~/MFL/monster-cheese-team-manager already exists)
mkdir -p ~/MFL
cd ~/MFL
git clone https://github.com/jjpvoskuil/Monster-Cheese-Team-Manager.git monster-cheese-team-manager
cd monster-cheese-team-manager

# Create and activate a virtual environment, install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run this test to confirm it's healthy:

```bash
cd ~/MFL/monster-cheese-team-manager
source venv/bin/activate
pytest
```

You should see every test pass (294 as of this writing — a different
number just means the app has grown since, not that something's wrong).

---

## 3. Signing in to GitHub from Terminal

You'll need `git push`/`git pull` to work without prompting for a
password every time (GitHub no longer accepts plain passwords for git
operations — if you see "Password authentication is not supported for
Git operations" or "Invalid username or token," that's why). Two
standard, safe ways to fix this yourself — do this in your own Terminal,
never by handing a token to Claude:

**Option A — GitHub CLI (recommended, easiest to redo next year):**
```bash
brew install gh          # if you don't already have it
gh auth login             # follow the prompts (choose HTTPS, browser login)
```

**Option B — Personal access token stored in the macOS Keychain:**
1. On github.com: Settings → Developer settings → Personal access
   tokens → generate a new token with `repo` scope.
2. In Terminal:
   ```bash
   git config --global credential.helper osxkeychain
   git push   # the next push will prompt for username + the token as the "password"; Keychain remembers it after that
   ```

Either way, verify it worked with a no-op:
```bash
cd ~/MFL/monster-cheese-team-manager
git fetch
```
No password prompt and no error = you're set for the season. Do this
check every year — tokens can expire or get revoked between seasons.

---

## 4. Yearly refresh — step by step

Do these in order. Each step says which files it touches.

### Step 1 — Pull the latest code
```bash
cd ~/MFL/monster-cheese-team-manager
git pull origin main
source venv/bin/activate
pip install -r requirements.txt   # picks up anything new added since last season
```

### Step 2 — Re-verify the league's scoring rules
Log in to `https://maniacfl.football.cbssports.com/rules` and compare
against `config/league_settings.yaml`'s `scoring:` and `roster:`
sections. Commissioners sometimes tweak point values or roster slots
between seasons. If anything changed, either edit the YAML directly or
ask a Claude session to re-capture the page and update it — either way,
update `metadata.captured_at` in that file so it's clear when it was
last checked.

### Step 3 — Archive last year's projection files (important!)
The app blends together **every** CSV/XLSX sitting in
`data/projections/` — it doesn't know or care what year is in the
filename. If last year's files are still there when you add this
year's, players get double-counted or stale data silently blends into
the new projections. Move the old ones out first:

```bash
cd ~/MFL/monster-cheese-team-manager
mkdir -p data/projections/archive_2026
mv data/projections/*_2026.csv data/projections/archive_2026/
```
(swap `2026` for whatever season just ended)

### Step 4 — Get the new draft order
Once CBS publishes the new season's draft order/results page:
```bash
python scripts/fetch_draft_order.py --print-url --year 2027
```
Open that URL in a logged-in browser, copy the draft-results page's
plain text (select-all + copy, or ask a Claude session with browser
access to grab it) into a text file, then:
```bash
python scripts/fetch_draft_order.py \
    --input /path/to/raw_page.txt \
    --year 2027 \
    --source-url "<the URL from --print-url>" \
    --update-config
```
This writes `data/draft/2027_draft_order.json` and automatically
rewrites `draft.team_order` in `config/league_settings.yaml`. Also
manually update that file's `draft.date_time` and `draft.rounds` if
they changed, and double check `draft.reverse_last_n_rounds` — last
year this was wrongly set to `2` (a "reverse the last 2 rounds" rule
that turned out not to be real) and had to be corrected to `0` after
checking it against the actual completed draft. Don't assume it's still
right; ask the commissioner if the format changed.

### Step 5 — Secure fresh season projections (4 sources)
Two sources refresh with plain HTTP and can be re-pulled with one
command each (or via the "🔄 Refresh" button on the app's Projections
page, once you've bumped the year in the command below):
```bash
python scripts/fetch_fftoday.py --live --output data/projections/fftoday_2027.csv
python scripts/fetch_fantasypros.py --live --output data/projections/fantasypros_2027.csv
```

The other two require a logged-in session (no plain refresh possible):

- **CBS**: log in to `cbssports.com`, then ask a live Claude session
  (with browser access) to pull the season projections pages for each
  position and save them to `data/projections/cbs_2027.csv` — there's
  no CLI script for this source since CBS requires an authenticated
  browser session, not just a URL.
- **FantasyPoints**: log in to `fantasypoints.com` (paid subscription),
  go to NFL → Projections & Rankings → Season, and click "Download CSV"
  once per position (qb/rb/wr/te/k/dst) into one folder, then:
  ```bash
  python scripts/fetch_fantasypoints.py \
      --from-capture-dir /path/to/that/folder \
      --output data/projections/fantasypoints_2027.csv
  ```

The app's Projections page (`http://localhost:8501/Projections`) has
"🔗 Log in & refresh" buttons that jump you to the CBS/FantasyPoints
login pages as a convenience, but getting the data INTO the app from
there still needs the manual/Claude-assisted capture above.

### Step 6 — Revisit source weights
Open the Projections page and reconsider how much you trust each of the
4 sources this year (a source can go stale, change quality, or drop
positions) — set the sliders and save. This writes
`data/source_weights.json`, which every page (Draft Board, League
Rosters, Reports) reads from, so this one setting drives every
projected point in the app.

### Step 7 — Re-verify roster requirements
Compare `config/league_settings.yaml`'s
`estimation_assumptions.round_based_fill_targets` and
`roster.position_active_limits` against the commissioner's current
draft-requirements sheet, in case position minimums (K/DEF counts,
flex eligibility, etc.) changed.

### Step 8 — Commit and push
```bash
cd ~/MFL/monster-cheese-team-manager
git add config/league_settings.yaml data/projections/*_2027.csv data/draft/2027_draft_order.json
git commit -m "Refresh 2027 season: draft order, scoring rules, projections"
git push
```

### Step 9 — Test-drive everything (§6 below) before trusting it live.

---

## 5. Launching the app day-to-day

```bash
cd ~/MFL/monster-cheese-team-manager
source venv/bin/activate
streamlit run app.py
```
Then open `http://localhost:8501` in your browser. Leave the terminal
running while you use the app; `Ctrl+C` to stop it.

If you also keep a copy deployed on Streamlit Cloud for browsing from
anywhere without your Mac running: that copy auto-updates whenever you
`git push` to `main`, but **live draft-day sync only works with the
local instance** — the Chrome extension posts picks to
`http://127.0.0.1:8765` on your own Mac, which a cloud-hosted app can't
receive. Run the app locally on draft day.

---

## 6. Setting up live draft-day sync (receiver + Chrome extension)

Full, tested walkthrough: **`DRAFT_DAY_CHECKLIST.md`** in the repo root
— read that file for the complete steps, troubleshooting, and the
incident history behind each fix. Condensed version:

**One-time** (per Mac, persists across restarts): load the extension at
`chrome://extensions` → enable Developer mode → "Load unpacked" → select
`tools/chrome_extension`.

**Every time you draft (mock or real):**
```bash
# Terminal 1 — reset the pick log, then start the app
cd ~/MFL/monster-cheese-team-manager
rm -f data/draft_state.json data/live_sync_status.json
source venv/bin/activate
streamlit run app.py
```
```bash
# Terminal 2 — start the live pick receiver
cd ~/MFL/monster-cheese-team-manager
source venv/bin/activate
python3 tools/live_pick_receiver.py
```
Then open `http://localhost:8501/Draft_Board` and join the CBS draft
room. Watch for the extension's badge in the draft room's top-right
corner and the Draft Board's "🔴 Live sync from CBS" sidebar panel.

**As of this writing, live sync has NOT been re-verified against a live
CBS room since the fixes that followed the 2026-08-30 real draft** (team
ID resolution and stuck-retry bugs — see `DRAFT_DAY_CHECKLIST.md`'s
incident writeup). Run at least one mock draft test (§7 below) before
trusting it on real draft day.

---

## 7. Pre-draft test-drive checklist

Do this about a week out, and again the day before the real draft.

- [ ] **Run the test suite**: `pytest` from the repo root — everything
      should pass. A failure here means something broke silently since
      last season.
- [ ] **Run one full mock draft with live sync** end-to-end (§6 /
      `DRAFT_DAY_CHECKLIST.md`) — join a CBS mock draft lobby, confirm
      picks sync automatically, confirm the "on the clock" indicator and
      My Roster page update correctly.
- [ ] **Click through every page** of the app (Draft Board, Projections,
      Draft Tendencies, My Roster, League Rosters, Reports, League
      Settings, Development) and confirm no red error banners and no
      "No projection found for" warnings.
- [ ] **Double-check `config/league_settings.yaml`** against CBS's live
      site: `draft.team_order`, `draft.date_time`, `draft.rounds`,
      `draft.reverse_last_n_rounds`, and the scoring/roster sections.
- [ ] **Run a fresh Monte Carlo simulation** against this year's data to
      sanity-check the pick-suggestion logic still behaves reasonably:
      `python scripts/simulate_draft.py --trials 25`
- [ ] **Confirm GitHub push access still works** (§3's `git fetch`
      check) — tokens can expire between seasons.
- [ ] **Confirm the Chrome extension is still loaded** at
      `chrome://extensions` with no errors shown on its card.
- [ ] **Right before the real draft**: delete `data/draft_state.json`
      and `data/live_sync_status.json` one final time so an old mock
      draft doesn't leak into the real one.

---

## 8. Quick-reference command sheet

```bash
# Launch the app
cd ~/MFL/monster-cheese-team-manager && source venv/bin/activate && streamlit run app.py

# Start the live-draft receiver (separate terminal, draft day only)
cd ~/MFL/monster-cheese-team-manager && source venv/bin/activate && python3 tools/live_pick_receiver.py

# Reset the draft log before a mock/real draft
rm -f data/draft_state.json data/live_sync_status.json

# Pull latest code + deps
cd ~/MFL/monster-cheese-team-manager && git pull origin main && pip install -r requirements.txt

# Run the test suite
pytest

# Run a Monte Carlo simulation
python scripts/simulate_draft.py --trials 25

# Commit and push
git add -A && git commit -m "..." && git push
```

---

## 9. Where to go for more detail

- **`DRAFT_DAY_CHECKLIST.md`** — the exact, battle-tested live-sync
  walkthrough with troubleshooting for every failure mode seen so far.
- **`SESSION_NOTES.md`** — the full technical history: every bug found
  and fixed, every decision made and why. Read this first if anything in
  this guide seems out of date.
- **`docs/draft_insights.md`** — draft-strategy analysis (value over
  replacement, positional scarcity) from past seasons' data.
