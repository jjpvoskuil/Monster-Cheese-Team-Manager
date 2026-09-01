// Runs in the page's own MAIN world (manifest.json's "world": "MAIN") so it
// can see CBS's own `mainapp` draft-room object directly, exactly like
// pasting a script into DevTools console would -- a normal (isolated-world)
// content script cannot see page-defined globals like `mainapp` at all.
//
// This auto-injects into EVERY cbssports.com page (manifest.json's match
// pattern has to be broad -- draft rooms live on unpredictable per-draft
// subdomains like mockdraft14-2842314.football.cbssports.com or
// maniacfl.football.cbssports.com, and CBS doesn't expose a single stable
// URL pattern to scope to more tightly), so it must fail QUIETLY and
// cheaply on every page that isn't an active draft room -- see the bounded
// retry in installHook() below (a plain page has no `mainapp`, so this
// gives up after ~30s instead of polling forever).
(function () {
  if (window.__mcHookInstalled) return;

  // ---------------------------------------------------------------
  // Request/response bridge to background.js (via bridge.js) -- see that
  // file's header for why this indirection exists (Private Network Access
  // blocks a page-context fetch to localhost; only the extension's
  // background service worker is exempt).
  // ---------------------------------------------------------------
  let reqCounter = 0;
  const pending = new Map();

  window.addEventListener("mc-sync-response", (event) => {
    const { id, response } = event.detail;
    const resolve = pending.get(id);
    if (resolve) {
      pending.delete(id);
      resolve(response);
    }
  });

  function postToReceiver(path, body) {
    const id = ++reqCounter;
    return new Promise((resolve) => {
      pending.set(id, resolve);
      window.dispatchEvent(new CustomEvent("mc-sync-request", { detail: { id, path, body } }));
      setTimeout(() => {
        if (pending.has(id)) {
          pending.delete(id);
          resolve({ ok: false, error: "bridge timeout (extension not responding)" });
        }
      }, 5000);
    });
  }

  // ---------------------------------------------------------------
  // Status badge
  // ---------------------------------------------------------------
  let badge = null;
  function ensureBadge() {
    if (badge) return badge;
    badge = document.createElement("div");
    badge.style.cssText = [
      "position:fixed", "top:8px", "right:8px", "z-index:999999",
      "font:12px/1.4 -apple-system,sans-serif", "padding:8px 12px",
      "border-radius:6px", "color:#fff", "background:#555",
      "box-shadow:0 2px 8px rgba(0,0,0,.3)", "max-width:320px",
    ].join(";");
    badge.textContent = "MC sync: starting…";
    document.body.appendChild(badge);
    return badge;
  }
  function updateBadge(state, text) {
    const colors = { ok: "#1a7f37", error: "#c0392b", warn: "#b8860b", info: "#555" };
    const el = ensureBadge();
    el.style.background = colors[state] || colors.info;
    el.textContent = "MC sync: " + text;
  }

  // ---------------------------------------------------------------
  // Send queue -- fire-and-forget with retry, BUT bounded for a pick the
  // receiver actively REJECTS (e.g. a validation error), not just for a
  // pick that can't be delivered at all. This distinction is the fix for
  // a real incident (2026-08-30 real draft): one pick got a teamid the
  // receiver couldn't match, the receiver correctly rejected it with a
  // 400, and the OLD code here treated that identically to "can't reach
  // the receiver at all" -- retrying the same pick forever and, because
  // this is a FIFO queue that only advances past its head on success,
  // silently blocking EVERY pick after it for the rest of the draft. The
  // badge kept saying "retrying #99" while ~120 later picks piled up
  // behind it, unsynced, with no visible indication anything past #99
  // had stopped working at all.
  //
  // background.js's response shape (see that file) is what makes the two
  // cases distinguishable: a real network/connection failure never gets a
  // response at all (`{ok:false, error: "..."}`, no `status`), while ANY
  // reply from the receiver -- even a 400 -- carries a `status` field,
  // because the receiver process was reachable and answered.
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
      const response = await postToReceiver("/pick", item.payload);

      if (response.ok) {
        queue.shift();
        const data = response.data || {};
        const failNote = failures.length ? ` — ${failures.length} pick(s) FAILED, see console` : "";
        if (data.mismatches && data.mismatches.length) {
          updateBadge("error", `MISMATCH reported by receiver — check its terminal${failNote}`);
        } else {
          updateBadge("ok", `synced ${itemLabel(item.payload)} — on the clock: ${data.on_the_clock || "—"}${failNote}`);
        }
        continue;
      }

      const reachedReceiver = "status" in response; // got an HTTP response at all, even non-ok
      const reason = (response.data && response.data.error) || response.error || `HTTP ${response.status}`;

      if (!reachedReceiver) {
        // Genuine connectivity failure -- every other queued pick needs
        // this same receiver, so there's nothing to gain by skipping
        // ahead. Keep retrying THIS item indefinitely; the badge wording
        // is accurate here.
        updateBadge("error", `receiver unreachable — retrying ${itemLabel(item.payload)} (${reason})`);
        await new Promise((r) => setTimeout(r, 2000));
        continue;
      }

      // The receiver IS up and responded -- it just rejected this specific
      // pick (e.g. couldn't match the team). Retrying won't fix a
      // validation error, and letting it sit at the head of the queue
      // forever would silently stall every pick behind it, so give up
      // after a few tries and move on -- loudly.
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
    const response = await postToReceiver("/picks", { picks: payloads });
    if (response.ok) {
      updateBadge("ok", `backfilled through #${payloads[payloads.length - 1].overall_pick}`);
    } else {
      updateBadge("warn", "backfill failed — is the receiver running?");
    }
  }

  // ---------------------------------------------------------------
  // Resolve a CBS playerid into {name, pos, team}. mainapp.players
  // .getPlayer() returns name as "Last, First" -- confirmed live
  // 2026-08-30 -- convert to "First Last" to match this app's data.
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
  // match. Splits on the first "(" rather than trying to parse the
  // owner text itself, since that part's format varies wildly (a single
  // name, "A/B", "A & B", "A,B", extra spaces...).
  // ---------------------------------------------------------------
  function shortTeamName(rawName) {
    return String(rawName || "").split("(")[0].trim();
  }

  // ---------------------------------------------------------------
  // Resolve a CBS teamid into that team's real display NAME, using CBS's
  // own in-page team data (mainapp.teams.teams) -- exactly the same "ask
  // the page itself" approach resolvePlayer() above already uses for
  // players.
  //
  // BUG FOUND LIVE 2026-08-30 (the REAL draft, not a mock): this used to
  // not exist at all -- the receiver was trusted to convert a numeric
  // teamid into a team name by treating it as a 1..N index into
  // config/league_settings.yaml's team_order, which happened to be true
  // for every MOCK draft room tested (CBS numbers mock-room teams 1..N
  // fresh each time) but is FALSE for this real, long-running league,
  // whose teams carry persistent CBS franchise ids that aren't 1..10 at
  // all (teamid 27 showed up in a 10-team league). Resolving the name
  // HERE, from CBS's own authoritative data, instead of asking the
  // receiver to guess from a slot number, removes that assumption
  // entirely -- whatever teamid CBS uses, mainapp.teams.teams already
  // knows its real name.
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
  // Best-effort backfill from the draft room's own results table (picks
  // made before this script attached, e.g. joining mid-draft). See
  // tools/cbs_console_hook.js's equivalent function for the same caveats.
  // ---------------------------------------------------------------
  function backfillFromResultsTable(expectedUpTo) {
    try {
      const sel = document.querySelector("#selectRoundResults");
      if (sel) {
        sel.value = "all";
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      }
      const rows = document.querySelectorAll("#DraftRoom .views.results .SLTables1 table.data tr");
      if (!rows || !rows.length) {
        updateBadge("warn", "no history table found — starting fresh from live picks only");
        return;
      }
      const knownNames = new Set(
        Object.values(mainapp.teams.teams || {})
          .map((t) => t && t.name && shortTeamName(t.name))
          .filter(Boolean)
      );

      const batch = [];
      rows.forEach((row) => {
        const cells = row.querySelectorAll("td");
        if (cells.length < 3) return;
        const text = Array.from(cells).map((c) => c.textContent.trim());
        // Match the cell against CBS's own team names directly -- no
        // numeric teamid involved at all, see resolveTeamName()'s comment
        // above for why that indirection was the bug.
        const teamCellIdx = text.findIndex((t) => knownNames.has(t));
        if (teamCellIdx === -1) return;
        const teamName = text[teamCellIdx]; // the FANTASY team's name (e.g. "Monster Cheese")
        const playerCell = text[teamCellIdx + 1] || "";
        const m = playerCell.match(/^\*?(.+?),\s*(.+?)\s*\(([A-Z][A-Z-]*)\s*([A-Z]*)\)$/);
        const noComma = playerCell.match(/^\*?(.+?)\s*\(([A-Z][A-Z-]*)\s*([A-Z]*)\)$/);
        let name, pos, nflTeam; // the drafted PLAYER's NFL team (e.g. "DET") -- distinct from teamName above
        if (m) {
          name = `${m[2].trim()} ${m[1].trim()}`;
          pos = m[3];
          nflTeam = m[4];
        } else if (noComma) {
          name = noComma[1].trim();
          pos = noComma[2];
          nflTeam = noComma[3];
        } else {
          // "No Player Selected" or similar -- still record the slot so
          // this pick number doesn't silently shift every later pick's
          // numbering when reconciled by hand.
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
  // Install the hook -- gives up quietly after ~30s on a page that never
  // develops a `mainapp.socket` (i.e. any cbssports.com page that isn't an
  // active draft room), instead of polling forever.
  // ---------------------------------------------------------------
  let attempts = 0;
  function installHook() {
    if (typeof mainapp === "undefined" || !mainapp.socket || !mainapp.socket.eventPicksCompleted) {
      attempts++;
      if (attempts > 60) return; // ~30s at 500ms intervals -- not a draft room, stop trying
      setTimeout(installHook, 500);
      return;
    }
    window.__mcHookInstalled = true;

    const orig = mainapp.socket.eventPicksCompleted.bind(mainapp.socket);
    mainapp.socket.eventPicksCompleted = function (outer) {
      try {
        // CONFIRMED LIVE 2026-08-30: the real event argument is wrapped as
        // {type, subtype, payload: {picks, newstate, fullstatedelta}}, one
        // level deeper than first assumed, and both `teamid` on each pick
        // and `opick` on newstate arrive as strings, not numbers.
        const inner = outer && outer.payload;
        const picks = (inner && inner.picks) || [];
        const nextOpickRaw = inner && inner.newstate && inner.newstate.opick;
        const nextOpick = nextOpickRaw != null ? parseInt(nextOpickRaw, 10) : null;
        if (picks.length && nextOpick) {
          // BUG FOUND LIVE 2026-08-30 (real mock draft, mid-morning run):
          // `nextOpick` is the pick number that becomes "on the clock"
          // AFTER this batch completes, so the LAST pick in `picks`
          // (i === picks.length - 1) is overall pick `nextOpick - 1`, and
          // the batch spans backward from there -- NOT `nextOpick` itself.
          // The previous "+ 1" here numbered every pick one too high,
          // which meant pick #1 was never reported at all (it got
          // mislabeled as #2), so the receiver's merge logic sat forever
          // waiting for a #1 that would never arrive -- confirmed via the
          // receiver's own pending_ahead list, whose team order matched
          // the real snake order exactly once every number was shifted
          // down by one.
          picks.forEach((pk, i) => {
            const overall = nextOpick - picks.length + i;
            const info = resolvePlayer(pk.playerid);
            const teamName = resolveTeamName(pk.teamid);
            if (!teamName) {
              // Don't even send this one -- there's no team_order match to
              // hope for server-side any more (see resolveTeamName()'s
              // docstring), so failing fast here with a clear console
              // message is more useful than a round-trip 400.
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

    const opickNow = mainapp.summaryState && parseInt(mainapp.summaryState.opick, 10);
    if (opickNow && opickNow > 1) {
      backfillFromResultsTable(opickNow);
    }
  }

  installHook();
})();
