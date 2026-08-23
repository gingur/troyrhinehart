// Pure session / stats math shared by the background service worker
// (src/background.js imports this as an ES module) and the node test harness
// (dev/model-test.mjs). No chrome.* here — plain data in, plain data out.
//
// Money math runs in integer cents so float noise (0.1 + 0.2) never leaks
// into totals, and round/tick caps carry their evicted totals forward in
// `session.carry` so a capped session still reports exact lifetime numbers.
'use strict';

export const LIMITS = {
  IDLE_GAP_MS: 30 * 60 * 1000, // new session after 30 min without a round
  MAX_ROUNDS_PER_SESSION: 300,
  MAX_TICKS: 100, // shared-outcome feed (crash points, roulette numbers)
  MAX_ARCHIVED_SESSIONS: 30,
  MAX_EVICTED_IDS: 600, // dedupe memory for rounds already evicted by the cap
  MAX_KNOWN_ROUND_IDS: 2000, // cross-session dedupe memory (survives rotation)
  SNAPSHOT_ROUNDS_TAIL: 120, // rounds included per session in a broadcast snapshot
};

export const round2 = (n) => Math.round(n * 100) / 100;
const round1 = (n) => Math.round(n * 10) / 10;
const isNum = Number.isFinite;
const cents = (n) => Math.round(n * 100);

export function createSession(game, now = Date.now()) {
  return {
    id: game + '-' + now.toString(36),
    game,
    startedAt: now,
    lastActivityAt: now,
    rounds: [],
    ticks: [],
    current: null,
    // carry: totals of rounds evicted by the cap — created on first eviction.
  };
}

/** True when the session recorded anything worth archiving. */
export function hasData(session) {
  return Boolean(
    session.rounds.length || session.ticks.length || (session.carry && session.carry.rounds)
  );
}

function emptyCarry() {
  return {
    rounds: 0,
    wins: 0,
    losses: 0,
    pushes: 0,
    wageredC: 0, // integer cents
    returnedC: 0,
    netC: 0,
    biggestWin: 0,
    biggestLoss: 0,
    tailStreak: 0, // streak in progress at the eviction boundary
    bestWinStreak: 0,
    worstLossStreak: 0,
    evictedIds: [], // capped id memory so a history replay can't re-append an evicted round
  };
}

/**
 * True when the session already holds this round id — in the kept window OR
 * among ids evicted by the cap. The background dedupes replays with this;
 * checking only the window would double-count an evicted round replayed by a
 * page reload (once in carry, once live).
 */
export function hasRound(session, id) {
  if (id == null) return false;
  if (session.rounds.some((r) => r.id === id)) return true;
  const c = session.carry;
  return Boolean(c && c.evictedIds && c.evictedIds.includes(id));
}

// --- cross-session round-id memory -------------------------------------------
// Per-session dedupe (hasRound) stops at the session boundary: 20 rounds →
// manual/idle rotation → page reload (content-script seenRounds resets) →
// the site re-serves bet history, and every replayed round would land in the
// fresh session, double-counting real bets (archived 20 + live 20). Replayed
// history can't be caught by timestamps either — extractRound stamps capture
// time, so a replay looks freshly timed. So the background keeps a global
// capped FIFO of `game:id` keys for every round it has ever appended
// (state.knownRounds, persisted with the rest of the state) and consults it
// before appending, no matter which session the id first landed in.

/**
 * True when this game:id round was already appended to ANY session (current,
 * archived, or evicted) still inside the id-memory window.
 */
export function hasKnownRound(log, game, id) {
  if (id == null || !log || !Array.isArray(log.keys)) return false;
  return log.keys.includes(game + ':' + id);
}

/**
 * Record an appended round's game:id in the global memory, evicting the
 * oldest past `max`. Returns the log (creating it when absent/legacy-shaped)
 * so callers can assign it back: `state.knownRounds = rememberRound(...)`.
 */
export function rememberRound(log, game, id, max = LIMITS.MAX_KNOWN_ROUND_IDS) {
  if (id == null) return log;
  if (!log || !Array.isArray(log.keys)) log = { keys: [] };
  log.keys.push(game + ':' + id);
  while (log.keys.length > max) log.keys.shift();
  return log;
}

// --- round sanitizing ---------------------------------------------------------

/**
 * Whitelist-copy a round at the trust boundary (content script → background).
 * computeStats already guards every numeric read, but sanitizing on append
 * makes the "no NaN/Infinity/garbage in persisted rounds" invariant local to
 * one place instead of distributed across every consumer. Unknown fields are
 * dropped; malformed known fields are dropped (money) or defaulted (ts,
 * result) rather than poisoning storage.
 */
export function sanitizeRound(raw, now = Date.now()) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const round = {
    id: typeof r.id === 'string' || (typeof r.id === 'number' && isNum(r.id)) ? r.id : null,
    ts: isNum(r.ts) ? r.ts : now,
    result: r.result === 'win' || r.result === 'loss' || r.result === 'push' ? r.result : 'unknown',
  };
  if (isNum(r.bet) && r.bet >= 0) round.bet = r.bet;
  if (isNum(r.payout) && r.payout >= 0) round.payout = r.payout;
  if (isNum(r.profit)) round.profit = r.profit;
  if (isNum(r.multiplier) && r.multiplier >= 0) round.multiplier = r.multiplier;
  if (typeof r.currency === 'string' && r.currency.length < 32) round.currency = r.currency;
  if (r.detail && typeof r.detail === 'object' && !Array.isArray(r.detail)) round.detail = r.detail;
  return round;
}

// Streak rule (shared by carry accumulation and computeStats): wins and
// losses extend or flip the run, pushes are transparent (a push does not end
// a blackjack streak), anything else ('unknown') resets it.
function stepStreak(run, result) {
  if (result === 'win') return run > 0 ? run + 1 : 1;
  if (result === 'loss') return run < 0 ? run - 1 : -1;
  if (result === 'push') return run;
  return 0;
}

/**
 * Append a round, evicting from the front past `max` while folding the
 * evicted rounds' totals into session.carry so stats stay exact.
 */
export function appendRound(session, round, max = LIMITS.MAX_ROUNDS_PER_SESSION) {
  session.rounds.push(round);
  while (session.rounds.length > max) {
    const ev = session.rounds.shift();
    const c = session.carry || (session.carry = emptyCarry());
    c.rounds++;
    if (ev.result === 'win') c.wins++;
    else if (ev.result === 'loss') c.losses++;
    else if (ev.result === 'push') c.pushes++;
    if (isNum(ev.bet)) c.wageredC += cents(ev.bet);
    if (isNum(ev.payout)) c.returnedC += cents(ev.payout);
    if (isNum(ev.profit)) {
      c.netC += cents(ev.profit);
      if (ev.profit > c.biggestWin) c.biggestWin = ev.profit;
      if (ev.profit < c.biggestLoss) c.biggestLoss = ev.profit;
    }
    c.tailStreak = stepStreak(c.tailStreak, ev.result);
    if (c.tailStreak > c.bestWinStreak) c.bestWinStreak = c.tailStreak;
    if (c.tailStreak < c.worstLossStreak) c.worstLossStreak = c.tailStreak;
    if (ev.id != null) {
      const ids = c.evictedIds || (c.evictedIds = []); // legacy carries lack the array
      ids.push(ev.id);
      while (ids.length > LIMITS.MAX_EVICTED_IDS) ids.shift();
    }
  }
}

/** Append a shared-outcome tick, capped (no totals to carry for ticks). */
export function appendTick(session, tick, max = LIMITS.MAX_TICKS) {
  session.ticks.push(tick);
  while (session.ticks.length > max) session.ticks.shift();
}

/**
 * Full stats for a session: counts, money totals (exact, cap-aware), current
 * and best/worst streaks, a cumulative-net series for charting, duration and
 * pace. `now` is injectable for tests and for archived (ended) sessions.
 */
export function computeStats(session, now = Date.now()) {
  const rounds = session.rounds;
  const carry = session.carry || emptyCarry();

  let wageredC = carry.wageredC;
  let returnedC = carry.returnedC;
  let netC = carry.netC;
  const stats = {
    rounds: carry.rounds + rounds.length,
    wins: carry.wins,
    losses: carry.losses,
    pushes: carry.pushes,
    biggestWin: carry.biggestWin,
    biggestLoss: carry.biggestLoss,
    streak: 0, // positive = consecutive wins, negative = consecutive losses
  };

  // One forward pass: counts, money, best/worst streak runs, cumulative net.
  const series = [];
  let cumC = carry.netC;
  let run = carry.tailStreak;
  let bestWinStreak = carry.bestWinStreak;
  let worstLossStreak = carry.worstLossStreak;
  for (const r of rounds) {
    if (r.result === 'win') stats.wins++;
    else if (r.result === 'loss') stats.losses++;
    else if (r.result === 'push') stats.pushes++;
    if (isNum(r.bet)) wageredC += cents(r.bet);
    if (isNum(r.payout)) returnedC += cents(r.payout);
    if (isNum(r.profit)) {
      const p = cents(r.profit);
      netC += p;
      cumC += p;
      if (r.profit > stats.biggestWin) stats.biggestWin = r.profit;
      if (r.profit < stats.biggestLoss) stats.biggestLoss = r.profit;
    }
    run = stepStreak(run, r.result);
    if (run > bestWinStreak) bestWinStreak = run;
    if (run < worstLossStreak) worstLossStreak = run;
    series.push({ ts: isNum(r.ts) ? r.ts : null, net: cumC / 100 });
  }

  stats.wagered = wageredC / 100;
  stats.returned = returnedC / 100;
  stats.net = netC / 100;
  stats.biggestWin = round2(stats.biggestWin);
  stats.biggestLoss = round2(stats.biggestLoss);
  const decided = stats.wins + stats.losses;
  stats.winRate = decided ? Math.round((stats.wins / decided) * 100) : null;
  stats.bestWinStreak = bestWinStreak;
  stats.worstLossStreak = worstLossStreak;
  stats.series = series;

  // Current streak from the tail: pushes are transparent, unknown breaks.
  // If the whole kept window is one unbroken run, extend it with the carry's
  // boundary streak so a 300+ run survives cap eviction.
  let broke = false;
  for (let i = rounds.length - 1; i >= 0; i--) {
    const res = rounds[i].result;
    if (res === 'push') continue;
    if (res !== 'win' && res !== 'loss') {
      broke = true;
      break;
    }
    const dir = res === 'win' ? 1 : -1;
    if (stats.streak === 0) stats.streak = dir;
    else if (Math.sign(stats.streak) === dir) stats.streak += dir;
    else {
      broke = true;
      break;
    }
  }
  if (!broke && carry.tailStreak) {
    if (stats.streak === 0) stats.streak = carry.tailStreak;
    else if (Math.sign(carry.tailStreak) === Math.sign(stats.streak)) {
      stats.streak += carry.tailStreak;
    }
  }

  // Duration and pace.
  applyPace(stats, session, now);

  stats.extra = gameExtras(session);
  return stats;
}

function applyPace(stats, session, now) {
  const endAt = isNum(session.endedAt) ? session.endedAt : now;
  stats.durationMs = Math.max(0, endAt - (isNum(session.startedAt) ? session.startedAt : endAt));
  stats.betsPerMinute =
    stats.durationMs >= 1000 ? round1((stats.rounds * 60000) / stats.durationMs) : null;
}

/**
 * Refresh only the wall-clock-dependent stats (durationMs, betsPerMinute) on
 * a session's cached stats. Cheap enough to run on every snapshot, so a
 * consumer polling during a quiet spell never sees a frozen duration/pace.
 */
export function refreshPace(session, now = Date.now()) {
  if (session.stats) applyPace(session.stats, session, now);
}

/**
 * Snapshot view of a session for broadcasting: identical object shape, but
 * `rounds` bounded to the newest SNAPSHOT_ROUNDS_TAIL. A full 300-round
 * session with per-round detail serializes to tens of KiB, and broadcasts go
 * to the popup plus every game tab up to 10×/s under autobet — the UI renders
 * a bounded tail anyway, and every total in `stats` is already lifetime-exact.
 * Sessions under the tail are passed through untouched (no copy). Trimmed
 * copies gain `roundsHeld` (kept-window length) and `roundsTrimmed: true`;
 * the internal session object is never mutated.
 */
export function snapshotSession(session, tail = LIMITS.SNAPSHOT_ROUNDS_TAIL) {
  if (!session.rounds || session.rounds.length <= tail) return session;
  return {
    ...session,
    rounds: session.rounds.slice(-tail),
    roundsHeld: session.rounds.length,
    roundsTrimmed: true,
  };
}

// --- game-specific extras ----------------------------------------------------

function median(sorted) {
  const n = sorted.length;
  if (!n) return null;
  const mid = n >> 1;
  return n % 2 ? sorted[mid] : round2((sorted[mid - 1] + sorted[mid]) / 2);
}

export function gameExtras(session) {
  const { game, rounds, ticks } = session;

  if (game === 'crash') {
    const points = ticks.map((t) => t.crashPoint).filter(isNum);
    if (!points.length) return null;
    const sorted = [...points].sort((a, b) => a - b);
    return {
      label: 'crash points (all rounds seen)',
      count: points.length,
      median: median(sorted),
      under2x: Math.round((points.filter((p) => p < 2).length / points.length) * 100) + '%',
      last: points.slice(-15).reverse(),
    };
  }

  if (game === 'roulette') {
    const nums = ticks.map((t) => t.number).filter(isNum);
    if (!nums.length) return null;
    const freq = {};
    let red = 0, black = 0, green = 0;
    for (const t of ticks) {
      if (!isNum(t.number)) continue;
      freq[t.number] = (freq[t.number] || 0) + 1;
      if (t.color === 'red') red++;
      else if (t.color === 'black') black++;
      else if (t.color === 'green') green++;
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
    const mults = rounds.map((r) => r.multiplier).filter(isNum);
    if (!mults.length) return null;
    return {
      label: 'drop multipliers',
      count: mults.length,
      avg: round2(mults.reduce((a, b) => a + b, 0) / mults.length),
      best: Math.max(...mults),
      last: mults.slice(-15).reverse(),
    };
  }

  if (game === 'mines') {
    const cashed = rounds.filter((r) => r.result === 'win');
    const cashedMults = cashed.map((r) => r.multiplier).filter(isNum);
    return {
      label: 'games',
      count: rounds.length,
      cashouts: cashed.length,
      busts: rounds.filter((r) => r.result === 'loss').length,
      bestMultiplier: cashedMults.length ? Math.max(...cashedMults) : null,
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

// --- archived summaries ------------------------------------------------------

/**
 * Compact summary stored on a session when it's archived and broadcast in
 * snapshot().archivedSummaries. `rounds` and money fields are cap-aware
 * lifetime totals, not just the kept window.
 */
export function makeSummary(session, stats = computeStats(session)) {
  return {
    id: session.id,
    game: session.game,
    startedAt: session.startedAt,
    endedAt: session.endedAt ?? null,
    rounds: stats.rounds,
    net: stats.net,
    wagered: stats.wagered,
    winRate: stats.winRate,
    wins: stats.wins,
    losses: stats.losses,
    pushes: stats.pushes,
    biggestWin: stats.biggestWin,
    biggestLoss: stats.biggestLoss,
    durationMs: stats.durationMs,
    betsPerMinute: stats.betsPerMinute,
  };
}
