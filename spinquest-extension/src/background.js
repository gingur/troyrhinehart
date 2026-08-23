// Service worker: owns sessions. One active session per game, rotated after
// an idle gap or on manual reset. Persists to chrome.storage.local and
// broadcasts updates to the HUD overlay and the popup.
'use strict';

const IDLE_GAP_MS = 30 * 60 * 1000; // new session after 30 min without a round
const MAX_ROUNDS_PER_SESSION = 300;
const MAX_TICKS = 100; // shared-outcome feed (crash points, roulette numbers)
const MAX_ARCHIVED_SESSIONS = 30;

/**
 * state = {
 *   active: { [game]: Session },
 *   archived: Session[],           // most recent first
 *   focusedGame: string|null,      // game page the user is currently on
 * }
 * Session = { id, game, startedAt, lastActivityAt, rounds[], ticks[], current{} }
 */
let state = null;
let saveTimer = null;

async function loadState() {
  if (state) return state;
  const stored = await chrome.storage.local.get('sqxState');
  state = stored.sqxState || { active: {}, archived: [], focusedGame: null };
  return state;
}

function scheduleSave() {
  if (saveTimer) return;
  saveTimer = setTimeout(() => {
    saveTimer = null;
    chrome.storage.local.set({ sqxState: state }).catch(() => {});
  }, 1000);
}

function newSession(game) {
  return {
    id: game + '-' + Date.now().toString(36),
    game,
    startedAt: Date.now(),
    lastActivityAt: Date.now(),
    rounds: [],
    ticks: [],
    current: null,
  };
}

function getActiveSession(game, { rotateIfIdle = true } = {}) {
  let session = state.active[game];
  if (session && rotateIfIdle && Date.now() - session.lastActivityAt > IDLE_GAP_MS && session.rounds.length) {
    archive(session);
    session = null;
  }
  if (!session) {
    session = newSession(game);
    state.active[game] = session;
  }
  return session;
}

function archive(session) {
  delete state.active[session.game];
  if (!session.rounds.length && !session.ticks.length) return;
  session.endedAt = Date.now();
  session.stats = computeStats(session);
  delete session.current;
  state.archived.unshift(session);
  state.archived.length = Math.min(state.archived.length, MAX_ARCHIVED_SESSIONS);
}

// --- stats -----------------------------------------------------------------

function computeStats(session) {
  const rounds = session.rounds;
  const stats = {
    rounds: rounds.length,
    wins: 0,
    losses: 0,
    pushes: 0,
    wagered: 0,
    returned: 0,
    net: 0,
    biggestWin: 0,
    biggestLoss: 0,
    streak: 0, // positive = consecutive wins, negative = consecutive losses
  };

  for (const r of rounds) {
    if (r.result === 'win') stats.wins++;
    else if (r.result === 'loss') stats.losses++;
    else if (r.result === 'push') stats.pushes++;
    if (typeof r.bet === 'number') stats.wagered += r.bet;
    if (typeof r.payout === 'number') stats.returned += r.payout;
    if (typeof r.profit === 'number') {
      stats.net += r.profit;
      if (r.profit > stats.biggestWin) stats.biggestWin = r.profit;
      if (r.profit < stats.biggestLoss) stats.biggestLoss = r.profit;
    }
  }
  const decided = stats.wins + stats.losses;
  stats.winRate = decided ? Math.round((stats.wins / decided) * 100) : null;
  for (const k of ['wagered', 'returned', 'net', 'biggestWin', 'biggestLoss']) {
    stats[k] = Math.round(stats[k] * 100) / 100;
  }

  // Current streak from the tail.
  for (let i = rounds.length - 1; i >= 0; i--) {
    const r = rounds[i].result;
    if (r !== 'win' && r !== 'loss') break;
    const dir = r === 'win' ? 1 : -1;
    if (stats.streak === 0) stats.streak = dir;
    else if (Math.sign(stats.streak) === dir) stats.streak += dir;
    else break;
  }

  stats.extra = gameExtras(session);
  return stats;
}

function gameExtras(session) {
  const { game, rounds, ticks } = session;

  if (game === 'crash') {
    const points = ticks.map((t) => t.crashPoint).filter((n) => typeof n === 'number');
    if (!points.length) return null;
    const sorted = [...points].sort((a, b) => a - b);
    return {
      label: 'crash points (all rounds seen)',
      count: points.length,
      median: sorted[Math.floor(sorted.length / 2)],
      under2x: Math.round((points.filter((p) => p < 2).length / points.length) * 100) + '%',
      last: points.slice(-15).reverse(),
    };
  }

  if (game === 'roulette') {
    const nums = ticks.map((t) => t.number).filter((n) => typeof n === 'number');
    if (!nums.length) return null;
    const freq = {};
    let red = 0, black = 0, green = 0;
    for (const t of ticks) {
      if (typeof t.number !== 'number') continue;
      freq[t.number] = (freq[t.number] || 0) + 1;
      if (t.color === 'red') red++;
      else if (t.color === 'black') black++;
      else green++;
    }
    const byFreq = Object.entries(freq).sort((a, b) => b[1] - a[1]);
    return {
      label: 'spins seen',
      count: nums.length,
      hot: byFreq.slice(0, 4).map(([n, c]) => n + '×' + c),
      colors: { red, black, green },
      last: nums.slice(-15).reverse(),
    };
  }

  if (game === 'plinko') {
    const mults = rounds.map((r) => r.multiplier).filter((n) => typeof n === 'number');
    if (!mults.length) return null;
    return {
      label: 'drop multipliers',
      count: mults.length,
      avg: Math.round((mults.reduce((a, b) => a + b, 0) / mults.length) * 100) / 100,
      best: Math.max(...mults),
      last: mults.slice(-15).reverse(),
    };
  }

  if (game === 'mines') {
    const cashed = rounds.filter((r) => r.result === 'win');
    return {
      label: 'games',
      count: rounds.length,
      cashouts: cashed.length,
      busts: rounds.filter((r) => r.result === 'loss').length,
      bestMultiplier: Math.max(0, ...cashed.map((r) => r.multiplier || 0)) || null,
    };
  }

  if (game === 'blackjack') {
    return {
      label: 'hands',
      count: rounds.length,
      record: `${rounds.filter((r) => r.result === 'win').length}W-${rounds.filter((r) => r.result === 'loss').length}L-${rounds.filter((r) => r.result === 'push').length}P`,
    };
  }

  return null;
}

// --- event handling --------------------------------------------------------

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
    session.rounds.push(event.round);
    if (session.rounds.length > MAX_ROUNDS_PER_SESSION) session.rounds.shift();
    session.current = null; // deal resolved
  } else if (event.type === 'tick') {
    session.ticks.push(event.tick);
    if (session.ticks.length > MAX_TICKS) session.ticks.shift();
  }

  session.stats = computeStats(session);
  scheduleSave();
  broadcast();
}

function snapshot() {
  return {
    focusedGame: state.focusedGame,
    active: state.active,
    archivedSummaries: state.archived.map((s) => ({
      id: s.id,
      game: s.game,
      startedAt: s.startedAt,
      endedAt: s.endedAt,
      rounds: s.rounds.length,
      net: s.stats ? s.stats.net : 0,
    })),
  };
}

function broadcast() {
  const msg = { type: 'SQX_STATE', state: snapshot() };
  chrome.runtime.sendMessage(msg).catch(() => {}); // popup, if open
  chrome.tabs.query({ url: '*://*.spinquest.com/*' }, (tabs) => {
    for (const tab of tabs || []) {
      chrome.tabs.sendMessage(tab.id, msg).catch(() => {});
    }
  });
}

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
        broadcast();
      }
      sendResponse({ ok: true });
    } else if (msg.type === 'SQX_GET_STATE') {
      sendResponse({ state: snapshot() });
    } else if (msg.type === 'SQX_NEW_SESSION') {
      const session = state.active[msg.game];
      if (session) archive(session);
      getActiveSession(msg.game, { rotateIfIdle: false });
      scheduleSave();
      broadcast();
      sendResponse({ ok: true });
    } else if (msg.type === 'SQX_EXPORT') {
      sendResponse({ data: { exportedAt: new Date().toISOString(), ...state } });
    } else if (msg.type === 'SQX_CLEAR_ALL') {
      state = { active: {}, archived: [], focusedGame: state.focusedGame };
      await chrome.storage.local.set({ sqxState: state });
      broadcast();
      sendResponse({ ok: true });
    } else {
      sendResponse({});
    }
  })();
  return true; // async sendResponse
});
