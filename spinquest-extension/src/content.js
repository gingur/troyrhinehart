// Isolated-world pipeline: receives captured network events from page-hook.js,
// picks the adapter for the active game, and forwards normalized game events
// to the background service worker (the single source of truth for sessions).
'use strict';

(() => {
  const CHANNEL = 'sqx-capture';
  const seenRounds = new Set(); // round ids already forwarded (dedupe across payloads)
  const rawLog = []; // recent raw events for the inspector
  const RAW_LOG_MAX = 50;

  SQX.detectGame = function detectGame() {
    const hay = (location.pathname + ' ' + location.search).toLowerCase();
    for (const game of SQX.GAMES) {
      if (hay.includes(game)) return game;
    }
    // Common alias: "21" pages are blackjack.
    if (/\b(21|twentyone)\b/.test(hay)) return 'blackjack';
    return null;
  };

  const send = (msg) => {
    try {
      chrome.runtime.sendMessage(msg).catch(() => {});
    } catch {
      // Extension context invalidated (update/reload) — nothing to do.
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

    const adapter = SQX.adapters.find((a) => a.match(evt, activeGame));
    if (!adapter) return;
    const game = adapter.game || activeGame;
    if (!game) return;

    let events;
    try {
      events = adapter.parse(evt) || [];
    } catch {
      return; // one malformed payload must not kill the pipeline
    }

    for (const e of events) {
      if (e.type === 'round') {
        const key = game + ':' + e.round.id;
        if (seenRounds.has(key)) continue;
        seenRounds.add(key);
        if (seenRounds.size > 500) seenRounds.delete(seenRounds.values().next().value);
      }
      send({ type: 'SQX_GAME_EVENT', game, event: e });
    }
  };

  window.addEventListener('message', (msg) => {
    if (msg.source !== window) return;
    const data = msg.data;
    if (!data || data.channel !== CHANNEL) return;
    handleCapture(data);
  });

  // Tell the background which game page we're on (drives session focus),
  // re-checked on SPA navigations.
  let lastReported = '';
  const reportGame = () => {
    const game = SQX.detectGame();
    const key = game + '|' + location.pathname;
    if (key === lastReported) return;
    lastReported = key;
    send({ type: 'SQX_PAGE', game, url: location.href });
  };
  reportGame();
  setInterval(reportGame, 1500);

  // overlay.js runs in this same isolated world and reads the log directly.
  SQX.getRawLog = () => rawLog.slice().reverse();
})();
