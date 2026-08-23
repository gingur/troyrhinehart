// Dev-only stub of the chrome.* extension APIs, plus the SQX global that
// content.js normally provides. Load this BEFORE overlay.js / popup.js so
// they run unmodified outside a real extension context.
//
// Page API:
//   window.__SQX_INJECT(state[, rawLog]) — deliver a snapshot to every
//     onMessage listener exactly like the background broadcast does:
//     { type: 'SQX_STATE', state }. Also becomes the answer to any later
//     SQX_GET_STATE. Optional rawLog feeds SQX.getRawLog() (the HUD raw tab).
//   window.__SQX_SENT — array of every message the page sent via
//     chrome.runtime.sendMessage (for asserting on button clicks).
'use strict';

(() => {
  const listeners = [];
  let currentState = null; // last injected snapshot
  let rawLog = [];
  const sent = [];

  // --- chrome.storage.local (promise-based, in-memory) -----------------------
  const store = Object.create(null);
  const storageLocal = {
    async get(keys) {
      const out = {};
      const pick = (k) => {
        if (k in store) out[k] = structuredClone(store[k]);
      };
      if (keys == null) Object.keys(store).forEach(pick);
      else if (typeof keys === 'string') pick(keys);
      else if (Array.isArray(keys)) keys.forEach(pick);
      else {
        for (const k of Object.keys(keys)) {
          out[k] = k in store ? structuredClone(store[k]) : keys[k];
        }
      }
      return out;
    },
    async set(items) {
      for (const k of Object.keys(items)) store[k] = structuredClone(items[k]);
    },
    async remove(keys) {
      for (const k of Array.isArray(keys) ? keys : [keys]) delete store[k];
    },
    async clear() {
      for (const k of Object.keys(store)) delete store[k];
    },
  };

  // --- chrome.runtime --------------------------------------------------------
  // Plays the background service worker's part for the handful of message
  // types overlay.js and popup.js send.
  function answer(msg) {
    switch (msg && msg.type) {
      case 'SQX_GET_STATE':
        return { state: currentState };
      case 'SQX_EXPORT':
        return {
          data: {
            exportedAt: new Date().toISOString(),
            focusedGame: currentState ? currentState.focusedGame : null,
            active: currentState ? currentState.active : {},
            archived: [],
          },
        };
      case 'SQX_NEW_SESSION':
      case 'SQX_CLEAR_ALL':
      case 'SQX_PAGE':
      case 'SQX_GAME_EVENT':
        return { ok: true };
      default:
        return {};
    }
  }

  const runtime = {
    id: 'sqx-dev-stub',
    sendMessage(msg) {
      sent.push(structuredClone(msg));
      return Promise.resolve(answer(msg));
    },
    onMessage: {
      addListener(fn) {
        listeners.push(fn);
      },
      removeListener(fn) {
        const i = listeners.indexOf(fn);
        if (i >= 0) listeners.splice(i, 1);
      },
      hasListener(fn) {
        return listeners.includes(fn);
      },
    },
  };

  window.chrome = { runtime, storage: { local: storageLocal } };

  // --- SQX global (content.js's isolated-world namespace) --------------------
  // overlay.js only reads SQX.getRawLog; the rest keeps any stray adapter
  // code from exploding if someone loads it on the mock page.
  window.SQX = {
    GAMES: ['plinko', 'mines', 'crash', 'blackjack', 'roulette'],
    adapters: [],
    getRawLog: () => rawLog.slice(),
  };

  // --- injection entry point -------------------------------------------------
  window.__SQX_INJECT = function (state, raw) {
    currentState = state;
    if (Array.isArray(raw)) rawLog = raw;
    const msg = { type: 'SQX_STATE', state };
    for (const fn of listeners.slice()) {
      try {
        fn(msg, { id: runtime.id }, () => {});
      } catch (e) {
        console.error('SQX stub listener threw', e);
      }
    }
  };

  window.__SQX_SENT = sent;
})();
