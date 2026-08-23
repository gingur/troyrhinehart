// Isolated-world pipeline: receives captured network events from page-hook.js,
// picks the adapter for the active game, and forwards normalized game events
// to the background service worker (the single source of truth for sessions).
//
// Trust boundary: everything arriving on the capture channel is page-
// controlled (any page script can postMessage), so every field is validated,
// every adapter call is contained, and nothing here may throw.
'use strict';

(() => {
  const CHANNEL = 'sqx-capture';

  // Dedupe layers, cheapest first:
  //  - recentBodies: the same JSON body captured twice within a breath
  //    (double listener, fetch+XHR mirror, client retry) is one event.
  //  - seenRounds: round ids already forwarded (replayed history).
  //  - seenTickIds / lastTickByGame: shared-outcome ticks — by per-round id
  //    when the payload has one, else "same content within the window is a
  //    rebroadcast" (crash state frames repeat the final point many times).
  const recentBodies = new Map(); // body hash -> last capture ts
  const RECENT_BODY_MS = 400;
  const RECENT_BODIES_MAX = 64;
  const seenRounds = new Set(); // `game:id`
  const SEEN_ROUNDS_MAX = 500;
  const seenTickIds = new Set(); // `game:id`
  const SEEN_TICK_IDS_MAX = 800;
  const lastTickByGame = new Map(); // game -> { sig, ts }
  const TICK_REBROADCAST_MS = 10 * 1000;

  const rawLog = []; // recent raw events for the inspector
  const RAW_LOG_MAX = 50;

  SQX.detectGame = function detectGame() {
    let hay = '';
    try {
      hay = (location.pathname + ' ' + location.search).toLowerCase();
    } catch {
      return null;
    }
    for (const game of SQX.GAMES) {
      if (hay.includes(game)) return game;
    }
    // Common alias: "21" pages are blackjack.
    if (/\b(21|twentyone)\b/.test(hay)) return 'blackjack';
    // Same-origin iframes: the frame's own URL may be an opaque provider
    // path while the embedding page names the game — check the referrer.
    try {
      if (window !== window.top && document.referrer) {
        const ref = document.referrer.toLowerCase();
        for (const game of SQX.GAMES) {
          if (ref.includes(game)) return game;
        }
      }
    } catch {
      /* cross-origin parent — nothing more to learn */
    }
    return null;
  };

  const send = (msg) => {
    try {
      chrome.runtime.sendMessage(msg).catch(() => {});
    } catch {
      // Extension context invalidated (update/reload) — nothing to do.
    }
  };

  const remember = (set, key, max) => {
    set.add(key);
    if (set.size > max) set.delete(set.values().next().value);
  };

  const fnv = (str) => {
    let h = 0x811c9dc5;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return h >>> 0;
  };

  /** True when this exact body was already captured a moment ago. */
  const isTransportDuplicate = (evt) => {
    let sig;
    try {
      sig = fnv(evt.kind + '|' + evt.direction + '|' + (JSON.stringify(evt.body) || ''));
    } catch {
      return false; // unhashable — let it through
    }
    const prev = recentBodies.get(sig);
    recentBodies.set(sig, evt.ts);
    if (recentBodies.size > RECENT_BODIES_MAX) {
      recentBodies.delete(recentBodies.keys().next().value);
    }
    return prev !== undefined && evt.ts - prev < RECENT_BODY_MS;
  };

  const tickSig = (tick) => {
    try {
      return JSON.stringify({ ...tick, ts: undefined });
    } catch {
      return null;
    }
  };

  const handleCapture = (evt) => {
    const activeGame = SQX.detectGame();

    rawLog.push({
      ts: evt.ts,
      kind: evt.kind,
      direction: evt.direction,
      url: evt.url.slice(0, 200),
      keys: evt.body && typeof evt.body === 'object' ? Object.keys(evt.body).slice(0, 15) : [],
    });
    if (rawLog.length > RAW_LOG_MAX) rawLog.shift();

    if (isTransportDuplicate(evt)) return;

    const adapter = SQX.adapters.find((a) => {
      try {
        return a.match(evt, activeGame);
      } catch {
        return false; // a throwing matcher never blocks the others
      }
    });
    if (!adapter) return;
    const game = adapter.game || activeGame;
    if (!game) return;

    let events;
    try {
      events = adapter.parse(evt) || [];
    } catch {
      return; // one malformed payload must not kill the pipeline
    }
    if (!Array.isArray(events)) return;

    for (const e of events) {
      if (!e || typeof e !== 'object') continue;

      if (e.type === 'round') {
        if (!e.round || typeof e.round !== 'object') continue;
        const key = game + ':' + String(e.round.id);
        if (seenRounds.has(key)) continue;
        remember(seenRounds, key, SEEN_ROUNDS_MAX);
      } else if (e.type === 'tick') {
        const tick = e.tick;
        if (!tick || typeof tick !== 'object') continue;
        if (tick.id !== undefined && tick.id !== null) {
          const key = game + ':' + String(tick.id);
          if (seenTickIds.has(key)) continue;
          remember(seenTickIds, key, SEEN_TICK_IDS_MAX);
        } else {
          const sig = tickSig(tick);
          const at = typeof tick.ts === 'number' && Number.isFinite(tick.ts) ? tick.ts : evt.ts;
          const prev = lastTickByGame.get(game);
          if (sig !== null && prev && prev.sig === sig && at - prev.ts < TICK_REBROADCAST_MS) {
            continue; // rebroadcast of the same shared outcome
          }
          lastTickByGame.set(game, { sig, ts: at });
        }
      } else if (e.type !== 'state') {
        continue; // unknown event type — drop rather than forward garbage
      }

      send({ type: 'SQX_GAME_EVENT', game, event: e });
    }
  };

  window.addEventListener('message', (msg) => {
    try {
      if (msg.source !== window) return;
      const data = msg.data;
      if (!data || typeof data !== 'object' || data.channel !== CHANNEL) return;
      // Field-by-field validation: any page script can post on this channel.
      handleCapture({
        ts: typeof data.ts === 'number' && Number.isFinite(data.ts) ? data.ts : Date.now(),
        kind: typeof data.kind === 'string' ? data.kind.slice(0, 16) : '',
        direction: data.direction === 'out' ? 'out' : 'in',
        url: typeof data.url === 'string' ? data.url : '',
        body: data.body,
      });
    } catch {
      /* a hostile message must never break the listener */
    }
  });

  // Tell the background which game page we're on (drives session focus),
  // re-checked on SPA navigations. Sub-frames only report when they positively
  // identify a game — an auxiliary iframe must not blank out the top frame's
  // focus.
  let lastReported = '';
  const reportGame = () => {
    try {
      const game = SQX.detectGame();
      if (game === null && window !== window.top) return;
      const key = game + '|' + location.pathname;
      if (key === lastReported) return;
      lastReported = key;
      send({ type: 'SQX_PAGE', game, url: location.href });
    } catch {
      /* ignore */
    }
  };
  reportGame();
  setInterval(reportGame, 1500);

  // overlay.js runs in this same isolated world and reads the log directly.
  SQX.getRawLog = () => rawLog.slice().reverse();
})();
