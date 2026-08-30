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
  // Send queue (fire-and-forget with retry) -- unchanged in spirit from
  // the console-paste version, just posts through the bridge instead of
  // calling fetch() directly.
  // ---------------------------------------------------------------
  const queue = [];
  let sending = false;

  function enqueue(payload) {
    queue.push(payload);
    flush();
  }

  async function flush() {
    if (sending) return;
    sending = true;
    while (queue.length) {
      const payload = queue[0];
      const response = await postToReceiver("/pick", payload);
      if (response.ok) {
        queue.shift();
        const data = response.data || {};
        if (data.mismatches && data.mismatches.length) {
          updateBadge("error", "MISMATCH reported by receiver — check its terminal");
        } else {
          updateBadge("ok", `synced #${payload.overall_pick} — on the clock: ${data.on_the_clock || "—"}`);
        }
      } else {
        const reason = (response.data && response.data.error) || response.error || `HTTP ${response.status}`;
        updateBadge("error", `receiver unreachable — retrying #${payload.overall_pick} (${reason})`);
        await new Promise((r) => setTimeout(r, 2000));
      }
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
      const nameToTeamId = {};
      Object.values(mainapp.teams.teams || {}).forEach((t) => {
        if (t && t.teamid != null && t.name) nameToTeamId[t.name.trim()] = t.teamid;
      });

      const batch = [];
      rows.forEach((row) => {
        const cells = row.querySelectorAll("td");
        if (cells.length < 3) return;
        const text = Array.from(cells).map((c) => c.textContent.trim());
        const teamCellIdx = text.findIndex((t) => nameToTeamId[t] != null);
        if (teamCellIdx === -1) return;
        const teamid = nameToTeamId[text[teamCellIdx]];
        const playerCell = text[teamCellIdx + 1] || "";
        const m = playerCell.match(/^\*?(.+?),\s*(.+?)\s*\(([A-Z]+)\s*([A-Z]*)\)$/);
        const noComma = playerCell.match(/^\*?(.+?)\s*\(([A-Z]+)\s*([A-Z]*)\)$/);
        let name, pos, team;
        if (m) {
          name = `${m[2].trim()} ${m[1].trim()}`;
          pos = m[3];
          team = m[4];
        } else if (noComma) {
          name = noComma[1].trim();
          pos = noComma[2];
          team = noComma[3];
        } else {
          return;
        }
        const pickNum = parseInt(text[0], 10);
        if (!pickNum) return;
        batch.push({ overall_pick: pickNum, teamid: parseInt(teamid, 10), player_name: name, position: pos, nfl_team: team });
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
          const startOverall = nextOpick - picks.length;
          picks.forEach((pk, i) => {
            const overall = startOverall + i + 1;
            const info = resolvePlayer(pk.playerid);
            enqueue({
              overall_pick: overall,
              teamid: parseInt(pk.teamid, 10),
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
