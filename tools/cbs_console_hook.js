/**
 * CBS live-draft console hook — pairs with tools/live_pick_receiver.py.
 *
 * WHAT THIS DOES: hooks CBS's own real-time draft socket callback
 * (mainapp.socket.eventPicksCompleted) directly inside the CBS draft room
 * page. The instant CBS fires a pick event, this resolves the player's
 * name/position/team from CBS's own in-page data (mainapp.players) and
 * POSTs it straight to a local receiver (tools/live_pick_receiver.py)
 * running on your machine, which writes it into data/draft_state.json.
 * No polling, no Claude, no browser automation in the loop at all --
 * Claude is not involved in this data path once this script is running.
 * It also draws a small status badge in the corner of the page so you can
 * see at a glance that picks are syncing, with no need to check anything
 * else.
 *
 * SETUP (do this once per draft, in this order):
 *   1. In a real Terminal (not this browser), start the receiver:
 *        python3 tools/live_pick_receiver.py
 *      Leave that terminal open for the whole draft.
 *   2. Join the CBS draft room in Chrome, BEFORE the draft starts if at
 *      all possible (see the backfill note below for why).
 *   3. Open DevTools (Cmd+Option+J on Mac), click the Console tab, paste
 *      this entire file's contents, press Enter.
 *   4. Look for the green badge in the top-right corner of the page
 *      saying "Hook installed". That's it -- leave the tab open and let
 *      the draft run. The badge updates live as picks sync.
 *
 * IF THE TAB GETS RELOADED OR CLOSED MID-DRAFT: this script's state lives
 * only in that tab's JS memory, so a reload means pasting it again. On
 * install it makes a best-effort attempt to catch up on anything it
 * missed (see backfillFromResultsTable below) by reading CBS's own
 * results table on the page -- but that table's exact layout has not been
 * re-verified live for this draft, so treat it as a safety net, not the
 * plan: joining before the draft starts and never reloading the tab is
 * the reliable path. If the badge shows a backfill warning, or picks stop
 * advancing, tell your league manager -- there's a documented manual
 * fallback (Claude re-attaching via browser automation) that was used
 * and validated earlier in testing.
 */
(function () {
  if (window.__mcHookInstalled) {
    console.log("[MC sync] already installed in this tab.");
    return;
  }

  const RECEIVER_URL = "http://127.0.0.1:8765";
  // No hardcoded team list here any more -- team names are resolved live
  // from CBS's own mainapp.teams.teams (see resolveTeamName() below),
  // which is what fixed the 2026-08-30 real-draft incident where a
  // hardcoded/assumed team_order slot mapping got a real teamid wrong.

  // ---------------------------------------------------------------
  // Status badge
  // ---------------------------------------------------------------
  const badge = document.createElement("div");
  badge.style.cssText = [
    "position:fixed", "top:8px", "right:8px", "z-index:999999",
    "font:12px/1.4 -apple-system,sans-serif", "padding:8px 12px",
    "border-radius:6px", "color:#fff", "background:#555",
    "box-shadow:0 2px 8px rgba(0,0,0,.3)", "max-width:320px",
  ].join(";");
  badge.textContent = "MC sync: starting…";
  document.body.appendChild(badge);

  function updateBadge(state, text) {
    const colors = { ok: "#1a7f37", error: "#c0392b", warn: "#b8860b", info: "#555" };
    badge.style.background = colors[state] || colors.info;
    badge.textContent = "MC sync: " + text;
  }

  // ---------------------------------------------------------------
  // Send queue -- fire-and-forget with retry, BUT bounded for a pick the
  // receiver actively REJECTS (a validation error, e.g. no team match),
  // as opposed to a pick that plain can't be delivered (receiver down).
  // This distinction is the fix for a real incident (2026-08-30 real
  // draft): one pick got a teamid the receiver couldn't match, the
  // receiver correctly rejected it with a 400, and the OLD code here
  // treated that identically to "can't reach the receiver at all" --
  // retrying the same pick forever and, because this is a FIFO queue
  // that only advances past its head on success, silently blocking
  // EVERY pick after it for the rest of the draft. The badge kept saying
  // "retrying #99" while ~120 later picks piled up behind it, unsynced,
  // with no visible sign anything past #99 had stopped working at all.
  //
  // A real network/connection failure never gets an HTTP response at
  // all (fetch() itself throws); a rejection means the receiver WAS
  // reachable and answered (even with a 400) -- that's what
  // distinguishes the two branches below.
  // ---------------------------------------------------------------
  const MAX_REJECT_ATTEMPTS = 4;
  const failures = []; // {payload, reason} -- picks given up on; see console.table(window.__mcSyncFailures)
  window.__mcSyncFailures = failures;

  const queue = [];
  let sending = false;

  function itemLabel(payload) {
    return `#${payload.overall_pick} (${payload.team || "team?"} / ${payload.player_name || "?"})`;
  }

  function enqueue(payload) {
    queue.push({ payload, attempts: 0 });
    flush();
  }

  async function flush() {
    if (sending) return;
    sending = true;
    while (queue.length) {
      const item = queue[0];
      let res;
      try {
        res = await fetch(RECEIVER_URL + "/pick", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(item.payload),
        });
      } catch (e) {
        // Genuine connectivity failure -- every other queued pick needs
        // this same receiver, so there's nothing to gain by skipping
        // ahead. Keep retrying THIS item indefinitely.
        updateBadge("error", `receiver unreachable — retrying ${itemLabel(item.payload)} (is live_pick_receiver.py running?)`);
        await new Promise((r) => setTimeout(r, 2000));
        continue;
      }

      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        queue.shift();
        const failNote = failures.length ? ` — ${failures.length} pick(s) FAILED, see console` : "";
        if (data.mismatches && data.mismatches.length) {
          updateBadge("error", `MISMATCH reported by receiver — check its terminal${failNote}`);
        } else {
          updateBadge("ok", `synced ${itemLabel(item.payload)} — on the clock: ${data.on_the_clock || "—"}${failNote}`);
        }
        continue;
      }

      // The receiver IS up and responded -- it just rejected this
      // specific pick. Retrying won't fix a validation error, and
      // letting it sit at the head of the queue forever would silently
      // stall every pick behind it, so give up after a few tries and
      // move on -- loudly.
      const reason = data.error || `HTTP ${res.status}`;
      item.attempts += 1;
      if (item.attempts >= MAX_REJECT_ATTEMPTS) {
        queue.shift();
        failures.push({ payload: item.payload, reason });
        console.error(`[MC sync] giving up on ${itemLabel(item.payload)} after ${MAX_REJECT_ATTEMPTS} attempts: ${reason}`);
        updateBadge(
          "error",
          `SYNC FAILED for ${itemLabel(item.payload)}: ${reason} — log this pick manually! (${failures.length} failed so far — console.table(window.__mcSyncFailures) for the list)`
        );
        continue;
      }
      updateBadge("warn", `receiver rejected ${itemLabel(item.payload)}, retry ${item.attempts}/${MAX_REJECT_ATTEMPTS}: ${reason}`);
      await new Promise((r) => setTimeout(r, 1500));
    }
    sending = false;
  }

  async function sendBatch(payloads) {
    if (!payloads.length) return;
    try {
      const res = await fetch(RECEIVER_URL + "/picks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ picks: payloads }),
      });
      const data = await res.json().catch(() => ({}));
      updateBadge("ok", `backfilled through #${payloads[payloads.length - 1].overall_pick}`);
    } catch (e) {
      updateBadge("warn", "backfill failed — receiver may not be running yet");
    }
  }

  // ---------------------------------------------------------------
  // Resolve a CBS playerid into {name, pos, team} using CBS's own
  // in-page player data. mainapp.players.getPlayer() returns name as
  // "Last, First" (confirmed live during mock-draft testing) -- convert
  // to "First Last" to match this app's projection data everywhere else.
  // ---------------------------------------------------------------
  function resolvePlayer(playerid) {
    try {
      const p = mainapp.players.getPlayer(playerid);
      if (!p) return { name: "Unknown", pos: "", team: "" };
      let name = p.name || "";
      if (name.includes(",")) {
        const [last, first] = name.split(",").map((s) => s.trim());
        name = `${first} ${last}`;
      }
      return { name, pos: p.pripos || "", team: p.proteam || "" };
    } catch (e) {
      return { name: "Unknown", pos: "", team: "" };
    }
  }

  // ---------------------------------------------------------------
  // mainapp.teams.teams[].name includes the owner's name in parens --
  // e.g. "Monster Cheese (John,Sam Cardinal)" -- confirmed live
  // 2026-09-01 while backfilling the real draft's results by hand. Our
  // config's team_order (and CBS's own Draft Results panel) only ever
  // uses the bare team name, so every place this file reads a team name
  // off mainapp must strip the "(...)" suffix or nothing will ever
  // match. Splits on the first "(" rather than parsing the owner text
  // itself, since that part's format varies wildly (one name, "A/B",
  // "A & B", "A,B", extra spaces...).
  // ---------------------------------------------------------------
  function shortTeamName(rawName) {
    return String(rawName || "").split("(")[0].trim();
  }

  // ---------------------------------------------------------------
  // Resolve a CBS teamid into that team's real display NAME, from CBS's
  // own in-page team data (mainapp.teams.teams) -- the same "ask the
  // page itself" approach resolvePlayer() above uses for players.
  //
  // BUG FOUND LIVE 2026-08-30 (the REAL draft, not a mock): the receiver
  // used to be trusted to convert a numeric teamid into a team name by
  // treating it as a 1..N index into config/league_settings.yaml's
  // team_order -- true for every MOCK draft room tested (CBS numbers
  // those 1..N fresh each time) but FALSE for this real, long-running
  // league, whose teams carry persistent CBS franchise ids that aren't
  // 1..10 at all (teamid 27 showed up in a 10-team league). Resolving
  // the name HERE, from CBS's own authoritative data, removes that
  // assumption entirely.
  // ---------------------------------------------------------------
  function resolveTeamName(teamid) {
    try {
      const teams = mainapp.teams.teams || {};
      const direct = teams[teamid];
      if (direct && direct.name) return shortTeamName(direct.name);
      const found = Object.values(teams).find((t) => t && String(t.teamid) === String(teamid));
      return found && found.name ? shortTeamName(found.name) : null;
    } catch (e) {
      return null;
    }
  }

  // ---------------------------------------------------------------
  // Best-effort backfill from the draft room's own results table, for
  // picks that happened before this script was installed (e.g. you
  // joined mid-draft, or the tab got reloaded). NOT re-verified live for
  // this draft session -- if it doesn't find rows, it just skips
  // silently and you start syncing live from whatever pick comes next
  // (meaning anything before that stays un-synced in the app until
  // manually reconciled).
  // ---------------------------------------------------------------
  function backfillFromResultsTable(expectedUpTo) {
    try {
      const sel = document.querySelector("#selectRoundResults");
      if (sel) {
        sel.value = "all";
        // NOT `new Event(...)` -- CBS's own page code redefines the global
        // `Event` identifier for its own socket/messaging system, so that
        // constructor throws ("Event is not a constructor") in this main-
        // world context. document.createEvent is a method, not the global
        // identifier, so it isn't affected. Confirmed live 2026-09-01.
        const ev = document.createEvent("HTMLEvents");
        ev.initEvent("change", true, true);
        sel.dispatchEvent(ev);
      }
      // NOTE: "DraftRoom.views.results" is CBS's own literal element id --
      // the dots are part of the id string, not CSS-selector descendant
      // combinators. `#DraftRoom .views.results ...` (space-separated) was
      // silently matching nothing; confirmed live 2026-09-01 via a DOM scan
      // of the completed draft room (the id showed up as one element's
      // parentId, not three nested ones). getElementById sidesteps the
      // escaping entirely.
      const resultsPanel = document.getElementById("DraftRoom.views.results");
      const rows = resultsPanel ? resultsPanel.querySelectorAll(".SLTables1 table.data tr") : [];
      if (!rows || !rows.length) {
        updateBadge("warn", "no history table found — starting fresh from live picks only");
        return;
      }
      // Match rows against CBS's own team NAMES directly -- no numeric
      // teamid involved at all, see resolveTeamName()'s comment above for
      // why that indirection was the bug.
      const knownNames = new Set(
        Object.values(mainapp.teams.teams || {})
          .map((t) => t && t.name && shortTeamName(t.name))
          .filter(Boolean)
      );

      const batch = [];
      rows.forEach((row) => {
        const cells = row.querySelectorAll("td");
        if (cells.length < 3) return;
        // Layout assumed from earlier live verification: Round | Pick | Team | Player.
        // If CBS's markup differs this draft, this silently produces no
        // usable rows rather than sending garbage (each row is skipped
        // unless a known team name AND a plausible overall pick are found).
        const text = Array.from(cells).map((c) => c.textContent.trim());
        const teamCellIdx = text.findIndex((t) => knownNames.has(t));
        if (teamCellIdx === -1) return;
        const teamName = text[teamCellIdx]; // the FANTASY team's name (e.g. "Monster Cheese")
        const playerCell = text[teamCellIdx + 1] || "";
        const m = playerCell.match(/^\*?(.+?),\s*(.+?)\s*\(([A-Z][A-Z-]*)\s*([A-Z]*)\)$/);
        const noComma = playerCell.match(/^\*?(.+?)\s*\(([A-Z][A-Z-]*)\s*([A-Z]*)\)$/);
        let name, pos, nflTeam; // the drafted PLAYER's NFL team -- distinct from teamName above
        if (m) {
          name = `${m[2].trim()} ${m[1].trim()}`;
          pos = m[3];
          nflTeam = m[4];
        } else if (noComma) {
          name = noComma[1].trim();
          pos = noComma[2];
          nflTeam = noComma[3];
        } else {
          name = playerCell.replace(/^\*/, "").trim();
          pos = "";
          nflTeam = "";
        }
        const pickNum = parseInt(text[0], 10);
        if (!pickNum) return;
        batch.push({ overall_pick: pickNum, team: teamName, player_name: name, position: pos, nfl_team: nflTeam });
      });

      const usable = batch.filter((b) => b.overall_pick < expectedUpTo);
      if (usable.length) {
        usable.sort((a, b) => a.overall_pick - b.overall_pick);
        updateBadge("info", `backfilling ${usable.length} pick(s)…`);
        sendBatch(usable);
      } else {
        updateBadge("warn", "history table present but no usable rows parsed");
      }
    } catch (e) {
      console.error("[MC sync] backfill error", e);
      updateBadge("warn", "backfill failed (see console) — starting fresh from live picks only");
    }
  }

  // ---------------------------------------------------------------
  // Install the hook
  // ---------------------------------------------------------------
  function installHook() {
    if (typeof mainapp === "undefined" || !mainapp.socket || !mainapp.socket.eventPicksCompleted) {
      updateBadge("info", "waiting for draft room to load…");
      setTimeout(installHook, 500);
      return;
    }
    window.__mcHookInstalled = true;

    const orig = mainapp.socket.eventPicksCompleted.bind(mainapp.socket);
    mainapp.socket.eventPicksCompleted = function (outer) {
      try {
        // CONFIRMED LIVE 2026-08-30 (a real mock draft, via instrumented
        // logging -- the earlier "payload.picks" / "payload.newstate.opick"
        // shape documented from prior-session exploration was WRONG, and
        // this bug would have silently done nothing all draft long: the
        // actual event argument is one level deeper, wrapped as
        // {type: "picks", subtype: "completed", payload: {picks, newstate,
        // fullstatedelta}}, and both `teamid` on each pick and `opick` on
        // newstate arrive as STRINGS ("2", "169"), not numbers -- must
        // parseInt both or the receiver's int-only validation rejects them.
        const inner = outer && outer.payload;
        const picks = (inner && inner.picks) || [];
        const nextOpickRaw = inner && inner.newstate && inner.newstate.opick;
        const nextOpick = nextOpickRaw != null ? parseInt(nextOpickRaw, 10) : null;
        if (picks.length && nextOpick) {
          // BUG FOUND LIVE 2026-08-30 (real mock draft, mid-morning run):
          // the comment this replaced ("overall_pick of picks[0] - 1") was
          // wrong -- `nextOpick` is the pick that becomes "on the clock"
          // AFTER this batch, so picks[picks.length - 1]'s overall_pick is
          // `nextOpick - 1`, and the batch counts backward from there.
          // The old "+ 1" numbered every pick one too high, so overall
          // pick #1 was never reported at all (mislabeled as #2) and the
          // receiver's merge logic sat forever waiting for a #1 that would
          // never arrive -- confirmed via the receiver's own pending_ahead
          // list, whose team order matched the real snake order exactly
          // once every number was shifted down by one.
          picks.forEach((pk, i) => {
            const overall = nextOpick - picks.length + i;
            const info = resolvePlayer(pk.playerid);
            const teamName = resolveTeamName(pk.teamid);
            if (!teamName) {
              console.error(`[MC sync] could not resolve team name for CBS teamid ${pk.teamid} (pick #${overall})`);
              updateBadge("error", `can't identify the team for pick #${overall} (teamid ${pk.teamid}) — log it manually!`);
              return;
            }
            enqueue({
              overall_pick: overall,
              team: teamName,
              teamid: parseInt(pk.teamid, 10), // kept for debugging only -- the receiver matches on `team`, not this
              player_name: info.name,
              position: info.pos,
              nfl_team: info.team,
            });
          });
        }
      } catch (e) {
        console.error("[MC sync] hook error", e);
        updateBadge("error", "hook error — see console");
      }
      return orig(outer);
    };

    updateBadge("ok", "hook installed — waiting for picks");

    const opickNow = mainapp.summaryState && mainapp.summaryState.opick;
    if (opickNow && opickNow > 1) {
      backfillFromResultsTable(opickNow);
    }
  }

  installHook();
})();
