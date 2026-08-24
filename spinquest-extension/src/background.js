// Service worker: owns sessions. One active session per game, rotated after
// an idle gap (checked lazily on events AND by a periodic alarm, so idle
// sessions archive even while nobody plays) or on manual reset. Persists to
// chrome.storage.local and broadcasts updates to the HUD overlay and popup.
//
// MV3 restart safety: every message path awaits loadState() (single-flight),
// so a freshly woken worker always rehydrates from storage before touching
// state. Broadcast snapshots carry a monotonically increasing `seq` — it
// starts at Date.now() so it keeps rising across worker restarts and
// receivers can drop out-of-order/stale snapshots.
//
// All stats/session math lives in lib/stats.js (pure, shared with
// dev/model-test.mjs).
'use strict';

import {
  KNOWN_GAMES,
  LIMITS,
  appendRound,
  appendTick,
  boundedPlainObject,
  compactSession,
  computeStats,
  createSession,
  hasData,
  hasKnownRound,
  hasRound,
  liveRepeatId,
  makeSummary,
  refreshPace,
  rememberRound,
  sanitizePatch,
  sanitizeRound,
  sanitizeTick,
  snapshotSession,
  upgradeRound,
} from './lib/stats.js';

// Coalesce storage writes under event storms: leading + trailing edge, at
// most one write per second. The first event after a quiet period persists
// IMMEDIATELY (a casual single bet is durable at once); an autobet storm
// then folds into one trailing write per second. Known tradeoff: rounds are
// acked {ok:true} from memory, so a hard worker kill (browser crash, forced
// update mid-autobet) can still drop up to ~1s of storm tail. MV3 keeps the
// worker alive ~30s past the last event so the trailing write normally
// lands; onSuspend/onUpdateAvailable below flush best-effort on orderly
// teardown.
const SAVE_DEBOUNCE_MS = 1000;
const BROADCAST_MIN_INTERVAL_MS = 100; // coalesce broadcasts (autobet ~10+/s)
const IDLE_SWEEP_ALARM = 'sqx-idle-sweep';
const IDLE_SWEEP_PERIOD_MIN = 5;

/**
 * state = {
 *   active: { [game]: Session },
 *   archived: Session[],           // most recent first, each with .summary
 *   focusedGame: string|null,      // game page the user is currently on
 *   knownRounds: {                 // replay dedupe across session rotations:
 *     ['g:'+game]: {keys, t}       // PER-GAME capped id FIFOs (lazy-created;
 *   }                              // legacy flat {keys:["game:id"]} states
 *                                  // migrate on first write — see stats.js)
 * }
 * Session = { id, game, startedAt, lastActivityAt, rounds[], ticks[],
 *             current{}, carry?, stats?, summary? (archived only) }
 */
let state = null;
let statePromise = null; // single-flight: concurrent messages share one load

function loadState() {
  if (state) return Promise.resolve(state);
  if (!statePromise) {
    statePromise = chrome.storage.local.get('sqxState').then(
      (stored) => {
        statePromise = null;
        if (!state) state = stored.sqxState || { active: {}, archived: [], focusedGame: null };
        return state;
      },
      () => {
        statePromise = null;
        if (!state) state = { active: {}, archived: [], focusedGame: null };
        return state;
      }
    );
  }
  return statePromise;
}

// --- persistence (leading+trailing edge; at most one write per second) ------

let saveTimer = null;
let dirty = false;
let lastSaveAt = 0;
// True after a failed storage write (quota exhausted, IO error): everything
// since the last good write exists only in memory. Surfaced in every snapshot
// as `persistFailing` so a consumer can warn instead of silently losing data;
// `dirty` stays set so the next event or the alarm sweep retries the write.
let persistFailing = false;

function scheduleSave() {
  dirty = true;
  if (saveTimer) return;
  const wait = lastSaveAt + SAVE_DEBOUNCE_MS - Date.now();
  if (wait <= 0) {
    flushSave();
  } else {
    saveTimer = setTimeout(flushSave, wait);
  }
}

function flushSave() {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  if (!dirty || !state) return;
  dirty = false;
  lastSaveAt = Date.now();
  chrome.storage.local.set({ sqxState: state }).then(
    () => {
      persistFailing = false;
    },
    () => {
      persistFailing = true;
      dirty = true; // retried by the next event's save or the alarm sweep
    }
  );
}

// --- session lifecycle ------------------------------------------------------

function getActiveSession(game, { rotateIfIdle = true } = {}) {
  let session = state.active[game];
  if (session && rotateIfIdle && Date.now() - session.lastActivityAt > LIMITS.IDLE_GAP_MS && hasData(session)) {
    archive(session);
    session = null;
  }
  if (!session) {
    session = createSession(game);
    // Fresh sessions carry stats from birth so a snapshot consumer never
    // sees an active session without them (e.g. NEW_SESSION followed by a
    // fully-deduped history replay: no event ever recomputes stats).
    session.stats = computeStats(session);
    state.active[game] = session;
  }
  return session;
}

function archive(session) {
  delete state.active[session.game];
  if (!hasData(session)) return;
  session.endedAt = Date.now();
  session.summary = makeSummary(session, computeStats(session));
  delete session.current;
  // Compact for storage: fold all but a small round tail into carry and strip
  // detail, then recompute stats over the compacted shape (totals are
  // identical — carry is exact — but the cached series shrinks with the
  // window). 30 archived full-detail sessions would otherwise serialize past
  // the chrome.storage.local quota and pin every later save into failure.
  compactSession(session);
  session.stats = computeStats(session);
  state.archived.unshift(session);
  state.archived.length = Math.min(state.archived.length, LIMITS.MAX_ARCHIVED_SESSIONS);
}

/** Archive every active session that idled out. Returns true if any did. */
function sweepIdle() {
  const now = Date.now();
  let archivedAny = false;
  for (const game of Object.keys(state.active)) {
    const session = state.active[game];
    if (now - session.lastActivityAt > LIMITS.IDLE_GAP_MS && hasData(session)) {
      archive(session);
      archivedAny = true;
    }
  }
  return archivedAny;
}

// --- event handling ---------------------------------------------------------

/**
 * Ack→rotate→settle repair: the payout-less ack round may have been archived
 * (manual NEW_SESSION, idle rotation) before its settle arrived. The settle's
 * upgrade flag would otherwise fall through to the knownRounds dedupe and the
 * real outcome would be dropped, leaving a dead unknown-result round in the
 * archive (wagered counted, payout lost). Patch the archived round in place
 * and refresh that session's stats + summary instead.
 */
function upgradeArchivedRound(game, round) {
  for (const s of state.archived) {
    if (s.game !== game) continue;
    if (upgradeRound(s, round)) {
      s.stats = computeStats(s); // endedAt is set, so duration/pace stay fixed
      s.summary = makeSummary(s, s.stats);
      return true;
    }
  }
  return false;
}

function applyGameEvent(game, event) {
  const session = getActiveSession(game);
  session.lastActivityAt = Date.now();

  if (event.type === 'state') {
    // Size-bounded like round.detail (sanitizePatch): a hostile 400KiB patch
    // must not walk straight into the storage quota. The MERGED current is
    // bounded too — many small distinct-keyed patches otherwise accrete
    // without limit — falling back to the fresh patch alone on overflow.
    const patch = sanitizePatch(event.patch);
    if (!patch) return;
    const now = Date.now();
    const merged = {
      ...(session.current || {}),
      ...patch,
      detail: { ...((session.current || {}).detail || {}), ...(patch.detail || {}) },
      updatedAt: now,
    };
    session.current = boundedPlainObject(merged, LIMITS.MAX_CURRENT_JSON)
      ? merged
      : { ...patch, updatedAt: now };
  } else if (event.type === 'round') {
    // Sanitize at the trust boundary, then dedupe two ways: a re-injected
    // content script (page reload) can replay history payloads whose rounds
    // (a) this session already holds — including rounds the cap has evicted
    // (hasRound also checks carry.evictedIds) — or (b) a PREVIOUS session
    // already counted before it rotated/archived. The global knownRounds
    // memory catches (b): without it, 20 rounds → new session → reload →
    // history replay would double-count all 20 into the fresh session.
    //
    // `round.live` (set by normalize.js, stripped by sanitizeRound) marks a
    // weak-id round captured on a LIVE transport: its id uniqueness comes
    // from a page-local counter that a reload resets while knownRounds
    // persists, so a dedupe hit on such a round is a GENUINE identical-
    // outcome repeat, not a replay — re-suffix it from the counter persisted
    // in the game's shard instead of silently eating the bet. Replay-shaped
    // events (history lists, refetches) keep drop semantics.
    const live = event.round && event.round.live === true;
    const round = sanitizeRound(event.round);
    // `event.upgrade` (set by content.js) marks a payout-bearing settle for a
    // round already forwarded WITHOUT a payout (ack-then-push APIs): replace
    // the stored round in place — in this session or, when a rotation slipped
    // between ack and settle, in the archived one — instead of deduping the
    // real outcome away.
    if (!(event.upgrade === true && (upgradeRound(session, round) || upgradeArchivedRound(game, round)))) {
      if (hasRound(session, round.id) || hasKnownRound(state.knownRounds, game, round.id)) {
        if (!live) return;
        const alloc = liveRepeatId(state.knownRounds, game, round.id);
        state.knownRounds = alloc.log;
        round.id = alloc.id;
      }
      appendRound(session, round);
      state.knownRounds = rememberRound(state.knownRounds, game, round.id);
    }
    session.current = null; // deal resolved
  } else if (event.type === 'tick') {
    const tick = sanitizeTick(event.tick);
    if (!tick) return;
    appendTick(session, tick);
  } else {
    return; // unknown event type — nothing changed, nothing to persist
  }

  session.stats = computeStats(session);
  scheduleSave();
  requestBroadcast(game);
}

// --- snapshots + broadcast --------------------------------------------------

// Monotonic across worker restarts: seeded from the clock, and each snapshot
// takes max(seq + 1, now) — so seq can only outrun the clock by the number of
// same-millisecond snapshots, and a restart's fresh clock seed can never fall
// behind a long-lived predecessor.
let seq = Date.now();

function legacySummary(s) {
  // Archived sessions persisted by older versions have no stored summary.
  return {
    id: s.id,
    game: s.game,
    startedAt: s.startedAt,
    endedAt: s.endedAt ?? null,
    rounds: s.stats ? s.stats.rounds : s.rounds.length,
    net: s.stats ? s.stats.net : 0,
  };
}

function snapshot(changedGame = null) {
  const now = Date.now();
  seq = Math.max(seq + 1, now);
  // Live sessions carry stats cached at the last event; duration and pace
  // drift with the clock, so refresh them per snapshot (cheap, no full pass).
  // Sessions go out through snapshotSession: rounds bounded to the newest
  // SNAPSHOT_ROUNDS_TAIL (stats stay lifetime-exact), so an autobet-speed
  // broadcast doesn't structured-clone 300 detail-bearing rounds per tab.
  const active = {};
  for (const game of Object.keys(state.active)) {
    refreshPace(state.active[game], now);
    active[game] = snapshotSession(state.active[game]);
  }
  return {
    seq,
    generatedAt: now,
    changedGame, // which game's session changed, null = anything/everything
    focusedGame: state.focusedGame,
    persistFailing, // true while storage writes fail (quota/IO) — memory-only data
    active,
    archivedSummaries: state.archived.map((s) => s.summary || legacySummary(s)),
  };
}

let lastBroadcastAt = 0;
let broadcastTimer = null;
const pendingGames = new Set(); // '*' = a non-game-scoped change

function requestBroadcast(game) {
  pendingGames.add(game || '*');
  if (broadcastTimer) return;
  const wait = lastBroadcastAt + BROADCAST_MIN_INTERVAL_MS - Date.now();
  if (wait <= 0) {
    doBroadcast();
  } else {
    broadcastTimer = setTimeout(doBroadcast, wait);
  }
}

function doBroadcast() {
  if (broadcastTimer) {
    clearTimeout(broadcastTimer);
    broadcastTimer = null;
  }
  lastBroadcastAt = Date.now();
  const changedGame =
    pendingGames.size === 1 && !pendingGames.has('*') ? pendingGames.values().next().value : null;
  pendingGames.clear();
  const msg = { type: 'SQX_STATE', state: snapshot(changedGame) };
  chrome.runtime.sendMessage(msg).catch(() => {}); // popup, if open
  chrome.tabs.query({ url: '*://*.spinquest.com/*' }, (tabs) => {
    for (const tab of tabs || []) {
      chrome.tabs.sendMessage(tab.id, msg).catch(() => {});
    }
  });
}

// --- messages ---------------------------------------------------------------

// Game names are allowlisted at the same boundary sanitizeRound guards:
// adapters can only emit KNOWN_GAMES, so anything else is a spoofed sender.
// Unvalidated, a game of '__proto__' would ack {ok:true} while the round
// vanishes into prototype assignment, and 16 junk names would churn real
// games' shards out of the knownRounds cap (replay protection lost).
const VALID_GAMES = new Set(KNOWN_GAMES);
const validGame = (g) => (typeof g === 'string' && VALID_GAMES.has(g) ? g : null);

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    await loadState();

    if (msg.type === 'SQX_GAME_EVENT') {
      if (!validGame(msg.game) || !msg.event || typeof msg.event !== 'object') {
        sendResponse({ ok: false }); // never a silent {ok:true} for dropped data
        return;
      }
      applyGameEvent(msg.game, msg.event);
      sendResponse({ ok: true });
    } else if (msg.type === 'SQX_PAGE') {
      const game = validGame(msg.game); // null = lobby / unknown page
      if (state.focusedGame !== game) {
        state.focusedGame = game;
        scheduleSave();
        requestBroadcast(null);
      }
      sendResponse({ ok: true });
    } else if (msg.type === 'SQX_GET_STATE') {
      sendResponse({ state: snapshot() });
    } else if (msg.type === 'SQX_NEW_SESSION') {
      if (!validGame(msg.game)) {
        sendResponse({ ok: false });
        return;
      }
      const session = state.active[msg.game];
      if (session) archive(session);
      getActiveSession(msg.game, { rotateIfIdle: false });
      scheduleSave();
      requestBroadcast(msg.game);
      sendResponse({ ok: true });
    } else if (msg.type === 'SQX_EXPORT') {
      sendResponse({ data: { exportedAt: new Date().toISOString(), ...state } });
    } else if (msg.type === 'SQX_CLEAR_ALL') {
      // knownRounds survives the wipe on purpose: a page reload right after
      // clearing replays the site's bet history, and without the id memory
      // the cleared rounds would resurrect as a fresh session.
      state = { active: {}, archived: [], focusedGame: state.focusedGame, knownRounds: state.knownRounds };
      dirty = false;
      try {
        await chrome.storage.local.set({ sqxState: state });
        persistFailing = false;
      } catch {
        persistFailing = true;
        dirty = true;
      }
      requestBroadcast(null);
      sendResponse({ ok: true });
    } else {
      sendResponse({});
    }
  })().catch(() => sendResponse({}));
  return true; // async sendResponse
});

// --- idle-rotation alarm ----------------------------------------------------
// Event-driven rotation only fires when a new event arrives; the alarm also
// closes out sessions abandoned mid-visit (tab left open, player walked away).

if (chrome.alarms) {
  chrome.alarms.create(IDLE_SWEEP_ALARM, { periodInMinutes: IDLE_SWEEP_PERIOD_MIN });
  chrome.alarms.onAlarm.addListener(async (alarm) => {
    if (alarm.name !== IDLE_SWEEP_ALARM) return;
    await loadState();
    if (sweepIdle()) {
      scheduleSave();
      requestBroadcast(null);
    }
    flushSave(); // opportunistic: persist anything still debounced
  });
}

// --- teardown flush ---------------------------------------------------------
// Best-effort close of the SAVE_DEBOUNCE_MS loss window on orderly shutdown:
// onSuspend fires before MV3 terminates an idle worker, onUpdateAvailable
// before an extension update restarts it. A hard kill can still lose the
// in-flight debounce (documented at SAVE_DEBOUNCE_MS).

if (chrome.runtime.onSuspend) chrome.runtime.onSuspend.addListener(flushSave);
if (chrome.runtime.onUpdateAvailable) chrome.runtime.onUpdateAvailable.addListener(flushSave);
