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
  LIMITS,
  appendRound,
  appendTick,
  computeStats,
  createSession,
  hasData,
  hasRound,
  makeSummary,
  refreshPace,
} from './lib/stats.js';

const SAVE_DEBOUNCE_MS = 1000; // coalesce storage writes under event storms
const BROADCAST_MIN_INTERVAL_MS = 100; // coalesce broadcasts (autobet ~10+/s)
const IDLE_SWEEP_ALARM = 'sqx-idle-sweep';
const IDLE_SWEEP_PERIOD_MIN = 5;

/**
 * state = {
 *   active: { [game]: Session },
 *   archived: Session[],           // most recent first, each with .summary
 *   focusedGame: string|null,      // game page the user is currently on
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

// --- persistence (debounced; at most one storage write per second) ----------

let saveTimer = null;
let dirty = false;

function scheduleSave() {
  dirty = true;
  if (saveTimer) return;
  saveTimer = setTimeout(flushSave, SAVE_DEBOUNCE_MS);
}

function flushSave() {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  if (!dirty || !state) return;
  dirty = false;
  chrome.storage.local.set({ sqxState: state }).catch(() => {});
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
    state.active[game] = session;
  }
  return session;
}

function archive(session) {
  delete state.active[session.game];
  if (!hasData(session)) return;
  session.endedAt = Date.now();
  session.stats = computeStats(session);
  session.summary = makeSummary(session, session.stats);
  delete session.current;
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

function applyGameEvent(game, event) {
  const session = getActiveSession(game);
  session.lastActivityAt = Date.now();

  if (event.type === 'state') {
    session.current = {
      ...(session.current || {}),
      ...event.patch,
      detail: { ...((session.current || {}).detail || {}), ...(event.patch.detail || {}) },
      updatedAt: Date.now(),
    };
  } else if (event.type === 'round') {
    // Dedupe: a re-injected content script (page reload) can replay history
    // payloads whose rounds this session already holds — including rounds
    // the cap has evicted (hasRound also checks carry.evictedIds, so a
    // replayed evicted round is never counted twice).
    if (hasRound(session, event.round.id)) return;
    appendRound(session, event.round);
    session.current = null; // deal resolved
  } else if (event.type === 'tick') {
    appendTick(session, event.tick);
  }

  session.stats = computeStats(session);
  scheduleSave();
  requestBroadcast(game);
}

// --- snapshots + broadcast --------------------------------------------------

// Monotonic across worker restarts: seeded from the clock, bumped per snapshot.
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
  seq += 1;
  const now = Date.now();
  // Live sessions carry stats cached at the last event; duration and pace
  // drift with the clock, so refresh them per snapshot (cheap, no full pass).
  for (const game of Object.keys(state.active)) refreshPace(state.active[game], now);
  return {
    seq,
    generatedAt: now,
    changedGame, // which game's session changed, null = anything/everything
    focusedGame: state.focusedGame,
    active: state.active,
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

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    await loadState();

    if (msg.type === 'SQX_GAME_EVENT') {
      applyGameEvent(msg.game, msg.event);
      sendResponse({ ok: true });
    } else if (msg.type === 'SQX_PAGE') {
      if (state.focusedGame !== msg.game) {
        state.focusedGame = msg.game;
        scheduleSave();
        requestBroadcast(null);
      }
      sendResponse({ ok: true });
    } else if (msg.type === 'SQX_GET_STATE') {
      sendResponse({ state: snapshot() });
    } else if (msg.type === 'SQX_NEW_SESSION') {
      const session = state.active[msg.game];
      if (session) archive(session);
      getActiveSession(msg.game, { rotateIfIdle: false });
      scheduleSave();
      requestBroadcast(msg.game);
      sendResponse({ ok: true });
    } else if (msg.type === 'SQX_EXPORT') {
      sendResponse({ data: { exportedAt: new Date().toISOString(), ...state } });
    } else if (msg.type === 'SQX_CLEAR_ALL') {
      state = { active: {}, archived: [], focusedGame: state.focusedGame };
      dirty = false;
      await chrome.storage.local.set({ sqxState: state });
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
