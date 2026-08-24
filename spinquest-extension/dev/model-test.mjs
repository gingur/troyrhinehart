#!/usr/bin/env node
// Plain-node tests for the pure session/stats math in src/lib/stats.js —
// the exact module the background service worker imports. No framework:
//   node dev/model-test.mjs
// Exits non-zero on the first failing group; prints one line per test.
'use strict';

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const devDir = dirname(fileURLToPath(import.meta.url));
const {
  LIMITS,
  appendRound,
  appendTick,
  computeStats,
  createSession,
  gameExtras,
  hasData,
  compactSession,
  hasKnownRound,
  hasRound,
  liveRepeatId,
  makeSummary,
  refreshPace,
  rememberRound,
  round2,
  sanitizePatch,
  sanitizeRound,
  sanitizeTick,
  snapshotSession,
  upgradeRound,
} = await import(join(devDir, '..', 'src', 'lib', 'stats.js'));

// The normalize layer (util.js + normalize.js) is plain content-script code
// hanging off a global SQX — load the real files into a vm sandbox so the
// exact shipped extraction logic is under test.
function loadNormalize() {
  const sandbox = { Math, JSON, Date, Number, Array, Object, String, Boolean, console };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  for (const f of ['util.js', 'normalize.js']) {
    vm.runInContext(readFileSync(join(devDir, '..', 'src', 'lib', f), 'utf8'), sandbox, { filename: f });
  }
  return sandbox.window.SQX;
}
const N = loadNormalize();

let passed = 0;
let failed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log('  ok  ' + name);
  } catch (err) {
    failed++;
    console.error('FAIL  ' + name);
    console.error(String(err.message || err).replace(/^/gm, '      '));
  }
}

const T0 = Date.parse('2026-08-23T20:00:00Z');
const MIN = 60 * 1000;

// Round factory: profit derived from bet/payout unless given explicitly.
let nextId = 0;
function round(result, bet, payout, extra = {}) {
  const r = { id: 'r' + nextId++, ts: T0 + nextId * 1000, result, ...extra };
  if (bet !== undefined) r.bet = bet;
  if (payout !== undefined) r.payout = payout;
  if (r.profit === undefined && typeof bet === 'number' && typeof payout === 'number') {
    r.profit = round2(payout - bet);
  }
  return r;
}

function sessionWith(game, rounds, now = T0 + 10 * MIN) {
  const s = createSession(game, T0);
  for (const r of rounds) appendRound(s, r);
  s.stats = computeStats(s, now);
  return s;
}

// --- empty session ----------------------------------------------------------

test('empty session: zeroed stats, null winRate, no NaN anywhere', () => {
  const s = createSession('crash', T0);
  const stats = computeStats(s, T0 + MIN);
  assert.equal(stats.rounds, 0);
  assert.equal(stats.wins, 0);
  assert.equal(stats.losses, 0);
  assert.equal(stats.pushes, 0);
  assert.equal(stats.winRate, null);
  assert.equal(stats.net, 0);
  assert.equal(stats.wagered, 0);
  assert.equal(stats.returned, 0);
  assert.equal(stats.streak, 0);
  assert.equal(stats.bestWinStreak, 0);
  assert.equal(stats.worstLossStreak, 0);
  assert.deepEqual(stats.series, []);
  assert.equal(stats.durationMs, MIN);
  assert.equal(stats.betsPerMinute, 0);
  assert.equal(stats.extra, null);
  assert.equal(hasData(s), false);
});

test('zero/negative duration: betsPerMinute is null, never Infinity', () => {
  const s = sessionWith('mines', [round('win', 1, 2)], T0); // now === startedAt
  assert.equal(s.stats.durationMs, 0);
  assert.equal(s.stats.betsPerMinute, null);
});

// --- pushes -----------------------------------------------------------------

test('all pushes: winRate null (0/0 decided), streak 0, net 0', () => {
  const s = sessionWith('blackjack', [
    round('push', 5, 5),
    round('push', 5, 5),
    round('push', 10, 10),
    round('push', 2.5, 2.5),
  ]);
  assert.equal(s.stats.rounds, 4);
  assert.equal(s.stats.pushes, 4);
  assert.equal(s.stats.wins, 0);
  assert.equal(s.stats.losses, 0);
  assert.equal(s.stats.winRate, null);
  assert.equal(s.stats.streak, 0);
  assert.equal(s.stats.net, 0);
  assert.equal(s.stats.wagered, 22.5);
  assert.equal(s.stats.returned, 22.5);
});

test('push is transparent to a streak: W W P W -> streak 3', () => {
  const s = sessionWith('blackjack', [
    round('win', 1, 2),
    round('win', 1, 2),
    round('push', 1, 1),
    round('win', 1, 2),
  ]);
  assert.equal(s.stats.streak, 3);
  assert.equal(s.stats.bestWinStreak, 3);
});

test('unknown result breaks a streak: W W U W -> streak 1', () => {
  const s = sessionWith('crash', [
    round('win', 1, 2),
    round('win', 1, 2),
    round('unknown', undefined, undefined),
    round('win', 1, 2),
  ]);
  assert.equal(s.stats.streak, 1);
  assert.equal(s.stats.bestWinStreak, 2);
});

// --- streaks ----------------------------------------------------------------

test('alternating W/L: streak follows the last round, best/worst are ±1', () => {
  const alts = [];
  for (let i = 0; i < 10; i++) alts.push(i % 2 ? round('loss', 1, 0) : round('win', 1, 2));
  const s = sessionWith('roulette', alts);
  assert.equal(s.stats.streak, -1); // last round is a loss
  assert.equal(s.stats.bestWinStreak, 1);
  assert.equal(s.stats.worstLossStreak, -1);
  assert.equal(s.stats.winRate, 50);
});

test('loss run after win run: streak negative, both bests recorded', () => {
  const s = sessionWith('crash', [
    round('win', 1, 2),
    round('win', 1, 2),
    round('win', 1, 2),
    round('loss', 1, 0),
    round('loss', 1, 0),
  ]);
  assert.equal(s.stats.streak, -2);
  assert.equal(s.stats.bestWinStreak, 3);
  assert.equal(s.stats.worstLossStreak, -2);
});

// --- missing/invalid fields -------------------------------------------------

test('missing bet fields: counted in results, ignored in money, no NaN', () => {
  const s = sessionWith('crash', [
    round('win', 1, 3),
    round('win', undefined, undefined), // result only
    { id: 'nan', ts: T0, result: 'loss', bet: NaN, payout: NaN, profit: NaN }, // hostile
    round('loss', 2, 0),
  ]);
  assert.equal(s.stats.rounds, 4);
  assert.equal(s.stats.wins, 2);
  assert.equal(s.stats.losses, 2);
  assert.equal(s.stats.wagered, 3); // only the two well-formed rounds
  assert.equal(s.stats.net, 0); // +2 - 2
  assert.equal(s.stats.winRate, 50);
  for (const v of [s.stats.net, s.stats.wagered, s.stats.returned, s.stats.biggestWin, s.stats.biggestLoss]) {
    assert.ok(Number.isFinite(v), 'money stat must be finite, got ' + v);
  }
  for (const pt of s.stats.series) assert.ok(Number.isFinite(pt.net));
});

// --- float rounding ---------------------------------------------------------

test('float rounding: 0.1-sized bets sum exactly (cents math)', () => {
  const s = sessionWith('plinko', [
    round('win', 0.1, 0.2),
    round('win', 0.1, 0.2),
    round('win', 0.1, 0.2),
  ]);
  assert.equal(s.stats.wagered, 0.3); // not 0.30000000000000004
  assert.equal(s.stats.returned, 0.6);
  assert.equal(s.stats.net, 0.3);
  assert.equal(s.stats.series[2].net, 0.3);
  const many = [];
  for (let i = 0; i < 100; i++) many.push(round('loss', 0.1, 0.03));
  const s2 = sessionWith('plinko', many);
  assert.equal(s2.stats.net, -7); // 100 × -0.07 exactly
});

// --- cumulative series ------------------------------------------------------

test('series: one point per kept round, cumulative net, carries ts', () => {
  const s = sessionWith('mines', [
    round('win', 1, 3), // +2
    round('loss', 2, 0), // 0
    round('win', 0.5, 2), // +1.5
  ]);
  assert.deepEqual(s.stats.series.map((p) => p.net), [2, 0, 1.5]);
  assert.equal(s.stats.series[0].ts, s.rounds[0].ts);
  assert.equal(s.stats.series.at(-1).net, s.stats.net);
});

// --- cap eviction -----------------------------------------------------------

test('cap eviction: totals, counts and streak survive the 300-round cap', () => {
  const s = createSession('plinko', T0);
  const n = LIMITS.MAX_ROUNDS_PER_SESSION + 10;
  for (let i = 0; i < n; i++) appendRound(s, round('win', 1, 2));
  assert.equal(s.rounds.length, LIMITS.MAX_ROUNDS_PER_SESSION);
  assert.equal(s.carry.rounds, 10);
  const stats = computeStats(s, T0 + 30 * MIN);
  assert.equal(stats.rounds, n); // lifetime count, not window count
  assert.equal(stats.wins, n);
  assert.equal(stats.net, n); // +1 per round, evicted rounds included
  assert.equal(stats.wagered, n);
  assert.equal(stats.streak, n); // unbroken run extends through the boundary
  assert.equal(stats.bestWinStreak, n);
  assert.equal(stats.series.length, LIMITS.MAX_ROUNDS_PER_SESSION);
  assert.equal(stats.series[0].net, 11); // 10 evicted wins + first kept win
  assert.equal(stats.series.at(-1).net, stats.net);
  assert.equal(stats.betsPerMinute, Math.round(((n * 60000) / (30 * MIN)) * 10) / 10);
});

test('cap eviction: boundary streak does NOT extend a broken window', () => {
  const s = createSession('crash', T0);
  for (let i = 0; i < LIMITS.MAX_ROUNDS_PER_SESSION + 5; i++) appendRound(s, round('win', 1, 2));
  appendRound(s, round('loss', 1, 0)); // evicts one more win, breaks the run
  const stats = computeStats(s, T0 + MIN);
  assert.equal(stats.streak, -1);
  assert.equal(stats.worstLossStreak, -1);
  assert.equal(stats.bestWinStreak, LIMITS.MAX_ROUNDS_PER_SESSION + 5);
});

test('cap eviction: biggest win/loss remembered from evicted rounds', () => {
  const s = createSession('mines', T0);
  appendRound(s, round('win', 10, 60)); // +50, will be evicted
  for (let i = 0; i < LIMITS.MAX_ROUNDS_PER_SESSION; i++) appendRound(s, round('loss', 1, 0));
  const stats = computeStats(s, T0 + MIN);
  assert.equal(stats.biggestWin, 50);
  assert.equal(stats.biggestLoss, -1);
  assert.equal(hasData(s), true);
});

test('tick cap: appendTick keeps the newest MAX_TICKS', () => {
  const s = createSession('crash', T0);
  for (let i = 0; i < LIMITS.MAX_TICKS + 25; i++) appendTick(s, { ts: T0 + i, crashPoint: i });
  assert.equal(s.ticks.length, LIMITS.MAX_TICKS);
  assert.equal(s.ticks[0].crashPoint, 25); // oldest evicted
  assert.equal(s.ticks.at(-1).crashPoint, LIMITS.MAX_TICKS + 24);
});

// --- duration / pace --------------------------------------------------------

test('duration + betsPerMinute: live session uses now, archived uses endedAt', () => {
  const s = sessionWith('roulette', [round('win', 1, 2), round('loss', 1, 0)], T0 + 4 * MIN);
  assert.equal(s.stats.durationMs, 4 * MIN);
  assert.equal(s.stats.betsPerMinute, 0.5);
  s.endedAt = T0 + 2 * MIN;
  const ended = computeStats(s, T0 + 99 * MIN); // now must be ignored
  assert.equal(ended.durationMs, 2 * MIN);
  assert.equal(ended.betsPerMinute, 1);
});

// --- game extras ------------------------------------------------------------

test('crash extras: even-count median averages the middle pair', () => {
  const s = createSession('crash', T0);
  for (const cp of [1.01, 2, 3, 10]) appendTick(s, { ts: T0, crashPoint: cp });
  const x = gameExtras(s);
  assert.equal(x.median, 2.5);
  assert.equal(x.under2x, '25%');
  assert.equal(x.count, 4);
});

test('crash extras: odd-count median is the middle element', () => {
  const s = createSession('crash', T0);
  for (const cp of [1.5, 8, 2.2]) appendTick(s, { ts: T0, crashPoint: cp });
  assert.equal(gameExtras(s).median, 2.2);
});

test('roulette extras: unknown colors are not counted as green', () => {
  const s = createSession('roulette', T0);
  appendTick(s, { ts: T0, number: 0, color: 'green' });
  appendTick(s, { ts: T0, number: 7, color: 'red' });
  appendTick(s, { ts: T0, number: 8 }); // color missing
  appendTick(s, { ts: T0, number: 8, color: 'black' });
  const x = gameExtras(s);
  assert.deepEqual(x.colors, { red: 1, black: 1, green: 1 });
  assert.equal(x.count, 4);
  assert.equal(x.hot[0], '8×2');
});

test('mines extras: bestMultiplier null with no numeric cashouts', () => {
  const s = sessionWith('mines', [round('loss', 1, 0), { id: 'w', ts: T0, result: 'win', bet: 1 }]);
  assert.equal(s.stats.extra.bestMultiplier, null);
  assert.equal(s.stats.extra.cashouts, 1);
  assert.equal(s.stats.extra.busts, 1);
});

test('plinko extras: avg guarded, empty multipliers -> null extras', () => {
  const s = sessionWith('plinko', [{ id: 'x', ts: T0, result: 'win', bet: 1, payout: 2, profit: 1 }]);
  assert.equal(s.stats.extra, null); // no numeric multiplier anywhere
  const s2 = sessionWith('plinko', [round('win', 1, 2, { multiplier: 2 }), round('loss', 1, 0.3, { multiplier: 0.3 })]);
  assert.equal(s2.stats.extra.avg, 1.15);
  assert.equal(s2.stats.extra.best, 2);
});

// --- archived summaries -----------------------------------------------------

test('makeSummary: cap-aware lifetime numbers + duration fields', () => {
  const s = createSession('blackjack', T0);
  const n = LIMITS.MAX_ROUNDS_PER_SESSION + 20;
  for (let i = 0; i < n; i++) appendRound(s, round(i % 3 === 2 ? 'push' : i % 2 ? 'loss' : 'win', 1, i % 2 ? 0 : 2));
  s.endedAt = T0 + 40 * MIN;
  const stats = computeStats(s);
  const sum = makeSummary(s, stats);
  assert.equal(sum.id, s.id);
  assert.equal(sum.game, 'blackjack');
  assert.equal(sum.rounds, n);
  assert.equal(sum.startedAt, T0);
  assert.equal(sum.endedAt, T0 + 40 * MIN);
  assert.equal(sum.net, stats.net);
  assert.equal(sum.wagered, stats.wagered);
  assert.equal(sum.winRate, stats.winRate);
  assert.equal(sum.wins + sum.losses + sum.pushes, n);
  assert.equal(sum.durationMs, 40 * MIN);
  assert.equal(sum.betsPerMinute, stats.betsPerMinute);
});

// --- evicted-round replay dedupe (hasRound) ---------------------------------

test('hasRound: sees window rounds AND cap-evicted ids (replay cannot double-count)', () => {
  const s = createSession('plinko', T0);
  const n = LIMITS.MAX_ROUNDS_PER_SESSION + 40;
  for (let i = 0; i < n; i++) appendRound(s, { id: 'p' + i, ts: T0 + i, result: 'win', bet: 1, payout: 2, profit: 1 });
  assert.equal(s.rounds.length, LIMITS.MAX_ROUNDS_PER_SESSION);
  assert.equal(hasRound(s, 'p0'), true); // evicted 40 rounds ago
  assert.equal(hasRound(s, 'p' + (n - 1)), true); // still in the window
  assert.equal(hasRound(s, 'never-seen'), false);
  assert.equal(hasRound(s, null), false);
  // Replaying an evicted round must not change lifetime totals.
  const before = computeStats(s, T0 + MIN).net;
  if (!hasRound(s, 'p0')) appendRound(s, { id: 'p0', ts: T0, result: 'win', bet: 1, payout: 2, profit: 1 });
  assert.equal(computeStats(s, T0 + MIN).net, before);
});

test('evicted-id memory is capped at MAX_EVICTED_IDS', () => {
  const s = createSession('crash', T0);
  const n = LIMITS.MAX_ROUNDS_PER_SESSION + LIMITS.MAX_EVICTED_IDS + 5;
  for (let i = 0; i < n; i++) appendRound(s, { id: 'c' + i, ts: T0 + i, result: 'loss', bet: 1, payout: 0, profit: -1 });
  assert.equal(s.carry.evictedIds.length, LIMITS.MAX_EVICTED_IDS);
  assert.equal(hasRound(s, 'c0'), false); // fell off the id memory
  assert.equal(hasRound(s, 'c5'), true); // oldest still remembered
});

// --- cross-session round-id memory (rotation replay) ------------------------

test('rotation replay: archive -> replay same ids into fresh session leaves lifetime unchanged', () => {
  let log; // background: state.knownRounds
  const first = createSession('plinko', T0);
  const replayed = [];
  for (let i = 0; i < 20; i++) {
    const r = { id: 'h' + i, ts: T0 + i * 1000, result: 'win', bet: 1, payout: 2, profit: 1 };
    replayed.push({ ...r, ts: T0 + 5 * MIN + i }); // replays carry fresh capture ts
    appendRound(first, r);
    log = rememberRound(log, 'plinko', r.id);
  }
  first.endedAt = T0 + 2 * MIN;
  const summary = makeSummary(first, computeStats(first, T0 + 2 * MIN));
  assert.equal(summary.rounds, 20);

  // Rotation (SQX_NEW_SESSION / idle sweep) + page reload: content-script
  // seenRounds resets and the site re-serves history into the NEW session.
  const fresh = createSession('plinko', T0 + 5 * MIN);
  for (const r of replayed) {
    if (hasRound(fresh, r.id) || hasKnownRound(log, 'plinko', r.id)) continue;
    appendRound(fresh, r);
    log = rememberRound(log, 'plinko', r.id);
  }
  assert.equal(fresh.rounds.length, 0); // every replay rejected
  assert.equal(computeStats(fresh, T0 + 6 * MIN).net, 0);
  assert.equal(summary.rounds, 20); // archived side untouched: 20 real bets stay 20
  // A genuinely new bet still lands.
  const live = { id: 'live-1', ts: T0 + 6 * MIN, result: 'loss', bet: 1, payout: 0, profit: -1 };
  assert.equal(hasKnownRound(log, 'plinko', live.id), false);
  appendRound(fresh, live);
  log = rememberRound(log, 'plinko', live.id);
  assert.equal(fresh.rounds.length, 1);
});

test('known-round memory is per game and survives a null/legacy log shape', () => {
  let log;
  assert.equal(hasKnownRound(undefined, 'crash', 'x'), false);
  assert.equal(hasKnownRound({ bogus: true }, 'crash', 'x'), false);
  log = rememberRound(log, 'crash', 'x');
  assert.equal(hasKnownRound(log, 'crash', 'x'), true);
  assert.equal(hasKnownRound(log, 'plinko', 'x'), false); // same id, other game
  assert.equal(rememberRound(log, 'crash', null), log); // null id ignored
  assert.equal(hasKnownRound(log, 'crash', null), false);
});

test('known-round memory: per-game FIFO capped at MAX_KNOWN_ROUND_IDS', () => {
  let log;
  const n = LIMITS.MAX_KNOWN_ROUND_IDS + 7;
  for (let i = 0; i < n; i++) log = rememberRound(log, 'mines', 'm' + i);
  assert.equal(log['g:mines'].keys.length, LIMITS.MAX_KNOWN_ROUND_IDS);
  assert.equal(hasKnownRound(log, 'mines', 'm0'), false); // oldest evicted
  assert.equal(hasKnownRound(log, 'mines', 'm7'), true);
  assert.equal(hasKnownRound(log, 'mines', 'm' + (n - 1)), true);
});

test('known-round shards: flooding one game past the cap cannot evict another game\'s keys', () => {
  // The round-3 bug: a single global 2000-key FIFO let 2000 plinko autobet
  // rounds flush blackjack's replay protection. Shards make eviction per-game.
  let log;
  for (let i = 0; i < 20; i++) log = rememberRound(log, 'blackjack', 'bj-' + i);
  const n = LIMITS.MAX_KNOWN_ROUND_IDS + 500;
  for (let i = 0; i < n; i++) log = rememberRound(log, 'plinko', 'pk-' + i);
  for (let i = 0; i < 20; i++) {
    assert.equal(hasKnownRound(log, 'blackjack', 'bj-' + i), true, 'bj-' + i + ' must survive the plinko flood');
  }
  assert.equal(hasKnownRound(log, 'plinko', 'pk-0'), false); // plinko's own FIFO still evicts
  assert.equal(hasKnownRound(log, 'plinko', 'pk-' + (n - 1)), true);
});

test('known-round memory: legacy flat shape reads in place and migrates on first write', () => {
  const legacy = { keys: ['blackjack:h1', 'plinko:p1', 'plinko:p2'] };
  assert.equal(hasKnownRound(legacy, 'blackjack', 'h1'), true);
  assert.equal(hasKnownRound(legacy, 'plinko', 'h1'), false); // still game-scoped
  const log = rememberRound(legacy, 'plinko', 'p3');
  assert.equal(Array.isArray(log.keys), false); // sharded now
  assert.equal(hasKnownRound(log, 'blackjack', 'h1'), true); // nothing lost in migration
  assert.equal(hasKnownRound(log, 'plinko', 'p1'), true);
  assert.equal(hasKnownRound(log, 'plinko', 'p3'), true);
  assert.equal(hasKnownRound(log, 'blackjack', 'p1'), false);
});

test('known-round memory: shard count capped, hostile game names stay inert', () => {
  let log;
  for (let i = 0; i < LIMITS.MAX_KNOWN_GAMES + 5; i++) {
    log = rememberRound(log, 'game' + i, 'x', LIMITS.MAX_KNOWN_ROUND_IDS, T0 + i);
  }
  assert.ok(Object.keys(log).length <= LIMITS.MAX_KNOWN_GAMES);
  assert.equal(hasKnownRound(log, 'game' + (LIMITS.MAX_KNOWN_GAMES + 4), 'x'), true); // newest kept
  assert.equal(hasKnownRound(log, 'game0', 'x'), false); // least-recently-written evicted
  const evil = rememberRound(undefined, '__proto__', 'e1');
  assert.equal(hasKnownRound(evil, '__proto__', 'e1'), true);
  assert.equal({}.e1, undefined); // no prototype pollution through the game name
  assert.equal(Object.getPrototypeOf(evil), Object.prototype);
});

test('known-round memory survives a JSON storage round-trip (Set cache rebuilt)', () => {
  let log;
  for (let i = 0; i < 50; i++) log = rememberRound(log, 'crash', 'c' + i);
  log = rememberRound(log, 'crash', 42); // numeric ids coerce consistently
  const revived = JSON.parse(JSON.stringify(log));
  assert.equal(hasKnownRound(revived, 'crash', 'c0'), true);
  assert.equal(hasKnownRound(revived, 'crash', 42), true);
  assert.equal(hasKnownRound(revived, 'crash', '42'), true);
  assert.equal(hasKnownRound(revived, 'crash', 'nope'), false);
  const log2 = rememberRound(revived, 'crash', 'c50');
  assert.equal(hasKnownRound(log2, 'crash', 'c50'), true);
  assert.equal(log2['g:crash'].keys.length, 52);
});

// --- sanitizeRound (trust boundary) -----------------------------------------

test('sanitizeRound: NaN/Infinity/strings/negatives never reach a stored round', () => {
  const r = sanitizeRound({
    id: 'ok-1',
    ts: NaN,
    bet: NaN,
    payout: Infinity,
    profit: '5',
    multiplier: -2,
    result: 'WIN',
    currency: 'x'.repeat(100),
    detail: ['not', 'an', 'object'],
    injected: 'field',
  }, T0);
  assert.equal(r.id, 'ok-1');
  assert.equal(r.ts, T0); // defaulted to now
  assert.equal(r.bet, undefined);
  assert.equal(r.payout, undefined);
  assert.equal(r.profit, undefined);
  assert.equal(r.multiplier, undefined);
  assert.equal(r.currency, undefined);
  assert.equal(r.detail, undefined);
  assert.equal(r.result, 'unknown'); // not in the win/loss/push whitelist
  assert.equal('injected' in r, false);
});

test('sanitizeRound: well-formed rounds pass through intact', () => {
  const good = { id: 42, ts: T0, bet: 1.5, payout: 3, profit: 1.5, multiplier: 2, result: 'win', currency: 'USD', detail: { crashPoint: 2 } };
  const r = sanitizeRound({ ...good }, T0 + 1);
  assert.deepEqual(r, good);
  const bad = sanitizeRound({ id: { evil: true }, result: 'push' }, T0);
  assert.equal(bad.id, null); // object id rejected -> null (dedupe skips nulls)
  assert.equal(bad.result, 'push');
  const none = sanitizeRound(null, T0);
  assert.equal(none.result, 'unknown');
  assert.equal(none.ts, T0);
});

test('sanitizeRound: finite-overflow money (1e308) rejected before cents math can hit Infinity', () => {
  const r = sanitizeRound(
    { id: 'big-1', ts: T0, bet: 1e308, payout: 1e308, profit: 1e300, multiplier: 1e13, result: 'win' },
    T0
  );
  assert.equal(r.bet, undefined);
  assert.equal(r.payout, undefined);
  assert.equal(r.profit, undefined);
  assert.equal(r.multiplier, undefined);
  // Just inside the cap still passes.
  const ok = sanitizeRound({ id: 'big-2', ts: T0, bet: 999, payout: 1e11, profit: 1e11 - 999, result: 'win' }, T0);
  assert.equal(ok.payout, 1e11);
  // Even a legacy-persisted round that skipped the sanitizer cannot poison stats.
  const s = createSession('plinko', T0);
  appendRound(s, { id: 'legacy', ts: T0, result: 'win', bet: 1e308, payout: 1e308, profit: 1e308 });
  const stats = computeStats(s, T0 + MIN);
  for (const v of [stats.wagered, stats.returned, stats.net, stats.biggestWin, stats.biggestLoss]) {
    assert.ok(Number.isFinite(v), 'stat must stay finite, got ' + v);
  }
});

test('sanitizeRound: oversized id truncated deterministically, oversized/circular detail dropped', () => {
  const r = sanitizeRound({ id: 'x'.repeat(100000), ts: T0, result: 'win', detail: { blob: 'y'.repeat(100000) } }, T0);
  assert.equal(r.id.length, LIMITS.MAX_ID_LEN);
  assert.equal(r.detail, undefined); // a megabyte detail would burn the storage quota
  // Deterministic truncation: the same oversized id replayed still dedupes.
  const r2 = sanitizeRound({ id: 'x'.repeat(100000), ts: T0, result: 'win' }, T0);
  assert.equal(r.id, r2.id);
  // Sane detail passes; a circular one is dropped without throwing.
  const good = sanitizeRound({ id: 'd1', ts: T0, result: 'win', detail: { slot: 3 } }, T0);
  assert.deepEqual(good.detail, { slot: 3 });
  const cyc = {};
  cyc.self = cyc;
  const c = sanitizeRound({ id: 'd2', ts: T0, result: 'win', detail: cyc }, T0);
  assert.equal(c.detail, undefined);
});

// --- snapshot round-tail trimming -------------------------------------------

test('snapshotSession: bounded round tail, lifetime stats intact, source untouched', () => {
  const small = sessionWith('mines', [round('win', 1, 2)]);
  assert.equal(snapshotSession(small), small); // under the tail: pass-through

  const s = createSession('crash', T0);
  const n = LIMITS.SNAPSHOT_ROUNDS_TAIL + 30;
  for (let i = 0; i < n; i++) appendRound(s, { id: 's' + i, ts: T0 + i, result: 'win', bet: 1, payout: 2, profit: 1 });
  s.stats = computeStats(s, T0 + MIN);
  const snap = snapshotSession(s);
  assert.equal(snap.rounds.length, LIMITS.SNAPSHOT_ROUNDS_TAIL);
  assert.equal(snap.rounds.at(-1).id, 's' + (n - 1)); // newest kept
  assert.equal(snap.roundsHeld, n);
  assert.equal(snap.roundsTrimmed, true);
  assert.equal(snap.stats.rounds, n); // totals still lifetime-exact
  assert.equal(s.rounds.length, n); // internal session not mutated
  assert.equal('roundsTrimmed' in s, false);
});

// --- live pace refresh (refreshPace) ----------------------------------------

test('refreshPace: duration/bpm track the clock between events, archived stays fixed', () => {
  const s = sessionWith('roulette', [round('win', 1, 2), round('loss', 1, 0)], T0 + 2 * MIN);
  assert.equal(s.stats.durationMs, 2 * MIN);
  refreshPace(s, T0 + 8 * MIN); // 6 quiet minutes later, a snapshot is taken
  assert.equal(s.stats.durationMs, 8 * MIN);
  assert.equal(s.stats.betsPerMinute, 0.3); // 2 rounds / 8 min, round1
  assert.equal(s.stats.rounds, 2); // rest of the stats untouched
  s.endedAt = T0 + 4 * MIN;
  refreshPace(s, T0 + 99 * MIN);
  assert.equal(s.stats.durationMs, 4 * MIN); // archived: endedAt wins over now
  refreshPace(createSession('mines', T0)); // no cached stats: must not throw
});

// --- normalize: round-id extraction -----------------------------------------

test('id ranking: deep betId beats a shallower constant gameId', () => {
  N._resetRoundIds();
  const mk = (betId, payout) => N.extractRound({
    ts: T0,
    body: { gameId: 'plinko-main', bet: 1, payout, betDetails: { betId } },
  });
  const a = mk('b1', 2.1);
  const b = mk('b2', 0.4);
  assert.equal(a.id, 'b1');
  assert.equal(b.id, 'b2'); // NOT 'plinko-main' twice
});

test('constant weak id across distinct rounds falls back to unique synthetic ids', () => {
  N._resetRoundIds();
  const mk = (payout, nonce) => N.extractRound({
    ts: T0 + nonce,
    body: { gameId: 'plinko-main', bet: 1, payout, path: [nonce, nonce + 1] },
  });
  const rounds = [mk(2.1, 1), mk(0.4, 2), mk(0.4, 3), mk(8.9, 4)];
  const ids = rounds.map((r) => r.id);
  assert.equal(ids[0], 'plinko-main'); // first occurrence has nothing to compare against
  for (const id of ids.slice(1)) assert.notEqual(id, 'plinko-main');
  assert.equal(new Set(ids).size, 4); // every round keeps a distinct id — none dropped
});

test('byte-identical replay keeps the same id (dedupe still catches re-fetched history)', () => {
  N._resetRoundIds();
  const body = { gameId: 'plinko-main', bet: 1, payout: 2.5, path: [0, 1] };
  const first = N.extractRound({ ts: T0, body });
  const replay = N.extractRound({ ts: T0 + 5000, body: JSON.parse(JSON.stringify(body)) });
  assert.equal(first.id, replay.id); // capture time excluded from the signature
  N._resetRoundIds();
  // Synthetic ids are deterministic too: after a page reload (fresh memory)
  // the same replayed bodies resolve to the same synthetic ids.
  const mk = (payout) => N.extractRound({ ts: T0, body: { gameId: 'g', bet: 1, payout } });
  const run1 = [mk(2), mk(3), mk(3)].map((r) => r.id);
  N._resetRoundIds();
  const run2 = [mk(2), mk(3), mk(3)].map((r) => r.id);
  assert.deepEqual(run1, run2);
});

test('live transport: byte-identical weak-id frames are genuine repeats, each counted', () => {
  // Plinko autobet, same stake, same slot: the settle frames are identical.
  // On a live socket that is two REAL bets — dedupe must not eat the second.
  N._resetRoundIds();
  const body = { gameId: 'plinko-main', betAmount: 1, payoutMultiplier: 0.5, payout: 0.5 };
  const mk = () =>
    N.extractRound({ ts: T0, kind: 'ws', url: 'wss://spinquest.com/socket', body: JSON.parse(JSON.stringify(body)) });
  const ids = [mk().id, mk().id, mk().id];
  assert.equal(new Set(ids).size, 3); // three drops -> three distinct ids
});

test('history transport: byte-identical weak-id entries keep one id (replay still deduped)', () => {
  N._resetRoundIds();
  const body = { gameId: 'plinko-main', betAmount: 1, payoutMultiplier: 0.5, payout: 0.5 };
  const hist = () =>
    N.extractRound({
      ts: T0,
      kind: 'fetch',
      url: 'https://spinquest.com/api/plinko/history?limit=50',
      body: JSON.parse(JSON.stringify(body)),
    });
  assert.equal(hist().id, hist().id);
  // No transport info at all (sub-item extraction, list entries) stays on the
  // replay-safe side too.
  N._resetRoundIds();
  const bare = () => N.extractRound({ ts: T0, body: JSON.parse(JSON.stringify(body)) });
  assert.equal(bare().id, bare().id);
});

test('strong per-bet ids never trip the constant-id detector', () => {
  N._resetRoundIds();
  const ids = [];
  for (let i = 0; i < 5; i++) {
    ids.push(N.extractRound({ ts: T0 + i, body: { betId: 'bet-' + i, bet: 1, payout: i } }).id);
  }
  assert.deepEqual(ids, ['bet-0', 'bet-1', 'bet-2', 'bet-3', 'bet-4']);
});

// --- normalize: money-field semantics ---------------------------------------

test('profit-shaped field is net, not gross: {bet:10, profit:5} is a +5 win', () => {
  N._resetRoundIds();
  const r = N.extractRound({ ts: T0, body: { bet: 10, profit: 5 } });
  assert.equal(r.payout, 15);
  assert.equal(r.profit, 5);
  assert.equal(r.result, 'win');
  const l = N.extractRound({ ts: T0, body: { bet: 10, profit: -10 } });
  assert.equal(l.payout, 0);
  assert.equal(l.result, 'loss');
  assert.equal(N.looksSettled({ ts: T0, body: { bet: 10, profit: 5 } }), true);
});

test('negative bet/payout garbage is not recorded as money', () => {
  N._resetRoundIds();
  // Negative bet rejected; the payout-only remainder has no strong id and no
  // settled status, so the whole payload is refused rather than recorded as
  // a betless "round".
  const r = N.extractRound({ ts: T0, body: { bet: -5, payout: 0 } });
  assert.equal(r, null);
  const skip = N.extractRound({ ts: T0, body: { amount: -3, betAmount: 2, payout: 4 } });
  assert.equal(skip.bet, 2); // walk skips the negative match, finds the real one
  assert.equal(skip.profit, 2);
});

test('wallet/balance/user envelopes never feed money legs', () => {
  N._resetRoundIds();
  // {balance:{amount}} is account state — not a bet, not settled.
  const wallet = { balance: { amount: 500.25, currency: 'usd' }, seq: 1 };
  assert.equal(N.extractRound({ ts: T0, body: wallet }), null);
  assert.equal(N.looksSettled({ ts: T0, body: wallet }), false);
  // ... even with a profit delta alongside: that's a ledger push, not a round.
  const delta = { balance: { amount: 502.75 }, profit: 2.5, seq: 2 };
  assert.equal(N.extractRound({ ts: T0, body: delta }), null);
  assert.equal(N.looksSettled({ ts: T0, body: delta }), false);
  // A real bet next to a balance snapshot still extracts from the bet leg.
  const both = { betId: 'w-1', bet: 2, payout: 5, balance: { amount: 100 } };
  const r = N.extractRound({ ts: T0, body: both });
  assert.equal(r.bet, 2);
  assert.equal(r.payout, 5);
});

test('lone namey object (bigwin broadcast) is stripped unless it has a strong id', () => {
  N._resetRoundIds();
  const bcast = { event: 'bigwin', username: 'whale42', win: 1250.5, betId: null };
  assert.equal(N.extractRound({ ts: T0, body: bcast }), null);
  // Our own settle echoes our username but carries a per-bet id — kept.
  const own = { username: 'me', betId: 'own-1', bet: 5, payout: 10 };
  const r = N.extractRound({ ts: T0, body: own });
  assert.equal(r.id, 'own-1');
  assert.equal(r.profit, 5);
});

test('payout-only rounds need corroboration (strong id or settled status)', () => {
  N._resetRoundIds();
  assert.equal(N.extractRound({ ts: T0, body: { win: 3.75 } }), null);
  const ok = N.extractRound({ ts: T0, body: { betId: 'co-9', win: 7.5, status: 'cashed_out' } });
  assert.equal(ok.payout, 7.5);
});

test('integer minor-unit money with scale/decimals is divided down', () => {
  N._resetRoundIds();
  const r = N.extractRound({
    ts: T0,
    body: {
      betId: 'sc-1',
      state: 'settled',
      bet: { amount: 121000000, currency: 'btc', scale: 8 },
      payout: { amount: 242000000, currency: 'btc', scale: 8 },
    },
  });
  assert.equal(r.bet, 1.21);
  assert.equal(r.payout, 2.42);
  // Float amounts are already major units — scale-shaped siblings ignored.
  const f = N.extractRound({
    ts: T0,
    body: { betId: 'sc-2', bet: { amount: 12.5, decimals: 2 }, payout: 0 },
  });
  assert.equal(f.bet, 12.5);
});

test('findTickId prefers roundId over betId; sioPayload unwraps bare arrays', () => {
  assert.equal(N.findTickId(['crash:bet_result', { betId: 'b-7', roundId: 'c-1' }]), 'c-1');
  assert.equal(N.findTickId({ betId: 'b-7' }), 'b-7');
  const arr = [{ roundId: 'h-1' }];
  assert.equal(N.sioPayload(['crash:history', arr]), arr);
  assert.equal(N.sioPayload(['lonely']), undefined);
  assert.equal(N.sioPayload({ a: 1 }), undefined);
});

test('multiplier-derived payout still works; division by zero bet stays guarded', () => {
  N._resetRoundIds();
  const r = N.extractRound({ ts: T0, body: { bet: 2, multiplier: 1.5 } });
  assert.equal(r.payout, 3);
  assert.equal(r.result, 'win');
  const z = N.extractRound({ ts: T0, body: { bet: 0, payout: 0 } });
  assert.equal(z.multiplier, undefined); // no 0/0 NaN
  assert.equal(z.result, 'push');
});

test('placement-status ack never reads as settled; settled words still do', () => {
  const ack = { ts: T0, body: { betId: 'pa-1', bet: 5, state: 'placed' } };
  assert.equal(N.looksSettled(ack), false);
  assert.equal(N.hasSettledEvidence(ack), false);
  const pend = { ts: T0, body: { betId: 'pa-2', amount: 5, status: 'pending' } };
  assert.equal(N.hasSettledEvidence(pend), false);
  const settle = { ts: T0, body: { betId: 'pa-1', bet: 5, payout: 12.5, state: 'settled' } };
  assert.equal(N.looksSettled(settle), true);
  assert.equal(N.hasSettledEvidence(settle), true);
  // Payout-only evidence (cashout push without a bet echo) still counts.
  assert.equal(N.hasSettledEvidence({ ts: T0, body: { betId: 'co-1', win: 7.5 } }), true);
});

test('blackjack split: money legs summed across the hands array', () => {
  N._resetRoundIds();
  const r = N.extractRound({
    ts: T0,
    body: {
      betId: 'bj-split',
      state: 'settled',
      hands: [
        { bet: 5, payout: 10, cards: ['8H', '3D', '9S'] },
        { bet: 5, payout: 0, cards: ['8C', '7D', 'KH'] },
      ],
    },
  });
  assert.equal(r.bet, 10);
  assert.equal(r.payout, 10);
  assert.equal(r.profit, 0);
  assert.equal(r.result, 'push');
  // A single-hand array is NOT a multi-leg settle — normal extraction.
  N._resetRoundIds();
  const one = N.extractRound({
    ts: T0,
    body: { betId: 'bj-one', state: 'settled', hands: [{ bet: 5, payout: 10 }] },
  });
  assert.equal(one.bet, 5);
  assert.equal(one.payout, 10);
});

test('feed-channel word strips namey objects even when they carry a strong id', () => {
  N._resetRoundIds();
  const feed = N.extractRound({
    ts: T0,
    body: { event: 'feed:win', username: 'whale42', betId: 'fw-1', bet: 100, payout: 5000 },
  });
  assert.equal(feed, null);
  // Our own settle echo (no feed channel named) keeps working.
  const own = N.extractRound({
    ts: T0,
    body: { username: 'me_player', betId: 'own-9', bet: 5, payout: 10, state: 'settled' },
  });
  assert.equal(own.payout, 10);
});

test('zero-profit round-end broadcast (no bet, no payout, no id) is not a round', () => {
  assert.equal(
    N.extractRound({ ts: T0, body: { type: 'round_end', status: 'finished', profit: 0, multiplier: 1.24 } }),
    null
  );
  // With a per-bet id it IS our push settle.
  N._resetRoundIds();
  const push = N.extractRound({ ts: T0, body: { betId: 'z-1', status: 'finished', profit: 0 } });
  assert.equal(push.profit, 0);
  assert.equal(push.result, 'push');
});

test('upgradeRound: payout-bearing settle replaces a payout-less ack round in place', () => {
  const s = createSession('plinko', T0);
  appendRound(s, { id: 'up-1', ts: T0, bet: 5, result: 'unknown' });
  // Not an upgrade: no payout on the incoming round.
  assert.equal(upgradeRound(s, { id: 'up-1', ts: T0, bet: 5, result: 'unknown' }), false);
  // Not an upgrade: unknown id.
  assert.equal(upgradeRound(s, { id: 'up-9', ts: T0, bet: 5, payout: 12.5, result: 'win' }), false);
  // The real settle upgrades.
  assert.equal(upgradeRound(s, { id: 'up-1', ts: T0 + 2000, bet: 5, payout: 12.5, profit: 7.5, result: 'win' }), true);
  assert.equal(s.rounds.length, 1);
  assert.equal(s.rounds[0].payout, 12.5);
  assert.equal(computeStats(s, T0 + 3000).net, 7.5);
  // Already payout-bearing rounds never get overwritten.
  assert.equal(upgradeRound(s, { id: 'up-1', ts: T0 + 9000, bet: 5, payout: 0, result: 'loss' }), false);
  assert.equal(s.rounds[0].payout, 12.5);
});

test('constant-id discovery on a live transport registers the occurrence (no round lost per discovery)', () => {
  // The round-4 sibling bug: the badIds-discovery branch returned 'sqx-'+sig
  // WITHOUT counting the live occurrence, so the next genuine repeat of that
  // exact content collided and dedupe ate one real round per discovery.
  N._resetRoundIds();
  const live = (body) => N.extractRound({ ts: T0, kind: 'ws', url: 'wss://spinquest.com/s', body: JSON.parse(JSON.stringify(body)) });
  const a = live({ gameId: 'g1', bet: 1, payout: 2 }); // first: weak id kept
  const b = live({ gameId: 'g1', bet: 1, payout: 0.5 }); // discovery: switches to synthetic
  const c = live({ gameId: 'g1', bet: 1, payout: 0.5 }); // genuine repeat of b's outcome
  const d = live({ gameId: 'g1', bet: 1, payout: 0.5 }); // and again
  assert.equal(new Set([a.id, b.id, c.id, d.id]).size, 4); // every real bet keeps a distinct id
  // Weak-id live rounds carry the transient `live` flag so the background can
  // pair page-local uniqueness with its persisted counter...
  assert.equal(a.live, true);
  assert.equal(b.live, true);
  // ...but strong ids and replay-shaped/bare captures never do.
  assert.equal(live({ betId: 'st-1', bet: 1, payout: 2 }).live, undefined);
  N._resetRoundIds();
  assert.equal(N.extractRound({ ts: T0, body: { gameId: 'g1', bet: 1, payout: 2 } }).live, undefined);
  // ...and sanitizeRound strips it before anything persists.
  assert.equal('live' in sanitizeRound({ id: 'x', ts: T0, result: 'win', live: true }, T0), false);
});

test('liveRepeatId: persisted per-game counter allocates collision-free ids across storage round-trips', () => {
  let log = rememberRound(undefined, 'plinko', 'sqx-abc');
  const a = liveRepeatId(log, 'plinko', 'sqx-abc');
  assert.notEqual(a.id, 'sqx-abc');
  log = rememberRound(a.log, 'plinko', a.id);
  const b = liveRepeatId(log, 'plinko', 'sqx-abc');
  log = rememberRound(b.log, 'plinko', b.id);
  assert.notEqual(b.id, a.id);
  // The counter lives IN the shard: a fresh worker rehydrating from storage
  // must not reissue an id an earlier worker already allocated.
  const revived = JSON.parse(JSON.stringify(log));
  const c = liveRepeatId(revived, 'plinko', 'sqx-abc');
  assert.notEqual(c.id, a.id);
  assert.notEqual(c.id, b.id);
  assert.equal(hasKnownRound(c.log, 'plinko', c.id), false);
  // An oversized base id still fits under the id length cap after suffixing.
  const big = liveRepeatId(c.log, 'plinko', 'x'.repeat(500));
  assert.ok(big.id.length <= LIMITS.MAX_ID_LEN);
});

test('compactSession: archive tail trimmed + detail stripped, lifetime totals stay exact', () => {
  const s = createSession('plinko', T0);
  for (let i = 0; i < 120; i++) {
    appendRound(s, { id: 'cp' + i, ts: T0 + i, result: 'win', bet: 1, payout: 2, profit: 1, detail: { path: [i, i + 1] } });
  }
  const before = computeStats(s, T0 + MIN);
  compactSession(s);
  assert.equal(s.rounds.length, LIMITS.MAX_ARCHIVED_ROUNDS);
  assert.equal(s.compacted, true);
  for (const r of s.rounds) assert.equal('detail' in r, false);
  const after = computeStats(s, T0 + MIN);
  for (const k of ['rounds', 'wins', 'losses', 'pushes', 'net', 'wagered', 'returned', 'streak', 'bestWinStreak', 'biggestWin']) {
    assert.equal(after[k], before[k], k + ' must survive compaction');
  }
  assert.equal(after.series.length, LIMITS.MAX_ARCHIVED_ROUNDS); // cached series shrinks with the window
  assert.equal(hasRound(s, 'cp0'), true); // compacted-away ids stay in the dedupe memory (carry.evictedIds)
});

test('sanitizePatch/sanitizeTick: size-bounded plain objects only (trust boundary for non-round events)', () => {
  const ok = { phase: 'betting', bet: 1, detail: { mines: 3 } };
  assert.equal(sanitizePatch(ok), ok);
  assert.equal(sanitizePatch(null), null);
  assert.equal(sanitizePatch([1, 2, 3]), null);
  assert.equal(sanitizePatch('phase'), null);
  assert.equal(sanitizePatch({ blob: 'x'.repeat(LIMITS.MAX_PATCH_JSON + 1) }), null);
  const cyc = {};
  cyc.self = cyc;
  assert.equal(sanitizePatch(cyc), null);
  const tick = { ts: T0, crashPoint: 2.1 };
  assert.equal(sanitizeTick(tick), tick);
  assert.equal(sanitizeTick({ blob: 'x'.repeat(LIMITS.MAX_TICK_JSON + 1) }), null);
});

// --- integration: the real background.js over a chrome stub ------------------
// Fresh module instance per "worker" (?v=N) sharing one JSON-serializing
// storage backend, exactly like chrome.storage.local behaves across MV3
// service-worker restarts.

async function atest(name, fn) {
  try {
    await fn();
    passed++;
    console.log('  ok  ' + name);
  } catch (err) {
    failed++;
    console.error('FAIL  ' + name);
    console.error(String(err.message || err).replace(/^/gm, '      '));
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const backend = new Map(); // key -> JSON string, shared across worker restarts
const failWrites = { on: false }; // simulate quota exhaustion / IO failure

function makeChrome() {
  const runtime = {
    _listener: null,
    onMessage: { addListener: (fn) => { runtime._listener = fn; } },
    sendMessage: async () => {},
  };
  return {
    storage: {
      local: {
        get: async (key) => {
          const out = {};
          if (backend.has(key)) out[key] = JSON.parse(backend.get(key));
          return out;
        },
        set: async (obj) => {
          if (failWrites.on) throw new Error('QUOTA_BYTES quota exceeded');
          for (const [k, v] of Object.entries(obj)) backend.set(k, JSON.stringify(v));
        },
      },
    },
    runtime,
    tabs: { query: (_q, cb) => cb([]), sendMessage: async () => {} },
    alarms: null, // periodic sweep not under test here
  };
}

const BG_URL = pathToFileURL(join(devDir, '..', 'src', 'background.js')).href;
let workerN = 0;
async function bootWorker() {
  workerN++;
  const chrome = makeChrome();
  globalThis.chrome = chrome;
  await import(BG_URL + '?worker=' + workerN);
  const send = (msg) => new Promise((resolve) => chrome.runtime._listener(msg, {}, resolve));
  return { chrome, send };
}

const roundEvent = (id, bet = 1, payout = 2, game = 'plinko') => ({
  type: 'SQX_GAME_EVENT',
  game,
  event: {
    type: 'round',
    round: { id, ts: Date.now(), bet, payout, profit: round2(payout - bet), result: payout > bet ? 'win' : payout < bet ? 'loss' : 'push' },
  },
});

await atest('message path: 20 rounds -> SQX_NEW_SESSION -> history replay is fully deduped', async () => {
  const { send } = await bootWorker();
  for (let i = 0; i < 20; i++) await send(roundEvent('hist-' + i));
  let snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.plinko.stats.rounds, 20);
  assert.equal(snap.active.plinko.stats.net, 20);

  await send({ type: 'SQX_NEW_SESSION', game: 'plinko' });
  // Page reload: content-script seenRounds resets, site re-serves history.
  for (let i = 0; i < 20; i++) await send(roundEvent('hist-' + i));
  snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.plinko.rounds.length, 0); // nothing re-counted
  assert.equal(snap.archivedSummaries.length, 1);
  assert.equal(snap.archivedSummaries[0].rounds, 20); // lifetime: 20 real bets stay 20
  assert.equal(snap.archivedSummaries[0].net, 20); // money counted once, not 2x
  // A new live bet still lands in the fresh session.
  await send(roundEvent('live-0', 1, 0));
  snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.plinko.stats.rounds, 1);
  assert.equal(snap.active.plinko.stats.net, -1);
});

await atest('message path: replay after WORKER RESTART is still deduped (knownRounds persisted)', async () => {
  await sleep(1200); // let the debounced save flush knownRounds to storage
  const { send } = await bootWorker(); // fresh module, same storage backend
  for (let i = 0; i < 20; i++) await send(roundEvent('hist-' + i));
  const snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.plinko.stats.rounds, 1); // only live-0 from before
  assert.equal(snap.archivedSummaries.length, 1);
  assert.equal(snap.archivedSummaries[0].rounds, 20);
});

await atest('message path: hostile round fields are sanitized before persisting', async () => {
  const { send } = await bootWorker();
  await send({
    type: 'SQX_GAME_EVENT',
    game: 'plinko',
    event: { type: 'round', round: { id: 'evil-1', ts: NaN, bet: NaN, payout: Infinity, profit: 3, result: 'win', extra: 'x' } },
  });
  const snap = (await send({ type: 'SQX_GET_STATE' })).state;
  const r = snap.active.plinko.rounds.find((x) => x.id === 'evil-1');
  assert.ok(r, 'sanitized round still recorded');
  assert.ok(Number.isFinite(r.ts));
  assert.equal('bet' in r, false);
  assert.equal('payout' in r, false);
  assert.equal('extra' in r, false);
  assert.equal(r.profit, 3);
  assert.ok(Number.isFinite(snap.active.plinko.stats.net));
});

await atest('message path: event.upgrade replaces the ack round instead of deduping the settle', async () => {
  const { send } = await bootWorker();
  await send({
    type: 'SQX_GAME_EVENT',
    game: 'plinko',
    event: { type: 'round', round: { id: 'ack-1', ts: Date.now(), bet: 5, result: 'unknown' } },
  });
  await send({
    type: 'SQX_GAME_EVENT',
    game: 'plinko',
    event: {
      type: 'round',
      upgrade: true,
      round: { id: 'ack-1', ts: Date.now(), bet: 5, payout: 12.5, profit: 7.5, result: 'win' },
    },
  });
  const snap = (await send({ type: 'SQX_GET_STATE' })).state;
  const rounds = snap.active.plinko.rounds.filter((r) => r.id === 'ack-1');
  assert.equal(rounds.length, 1); // replaced in place, not appended twice
  assert.equal(rounds[0].payout, 12.5);
  assert.equal(rounds[0].result, 'win');
  // A spoofed upgrade flag on an already-payout-bearing round is a plain dupe.
  await send({
    type: 'SQX_GAME_EVENT',
    game: 'plinko',
    event: { type: 'round', upgrade: true, round: { id: 'ack-1', ts: Date.now(), bet: 5, payout: 99, result: 'win' } },
  });
  const snap2 = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap2.active.plinko.rounds.find((r) => r.id === 'ack-1').payout, 12.5);
});

await atest('message path: broadcast/GET_STATE rounds bounded to SNAPSHOT_ROUNDS_TAIL', async () => {
  const { send } = await bootWorker();
  await send({ type: 'SQX_CLEAR_ALL' });
  const n = LIMITS.SNAPSHOT_ROUNDS_TAIL + 40;
  for (let i = 0; i < n; i++) await send(roundEvent('bulk-' + i));
  const snap = (await send({ type: 'SQX_GET_STATE' })).state;
  const s = snap.active.plinko;
  assert.equal(s.rounds.length, LIMITS.SNAPSHOT_ROUNDS_TAIL);
  assert.equal(s.roundsHeld, n);
  assert.equal(s.roundsTrimmed, true);
  assert.equal(s.stats.rounds, n); // lifetime totals unaffected by the trim
  assert.equal(s.stats.net, n);
  assert.equal(s.rounds.at(-1).id, 'bulk-' + (n - 1));
});

await atest('message path: cross-game autobet flood cannot evict another game\'s replay protection', async () => {
  // The round-3 double-count, end-to-end: 20 blackjack hands -> rotation ->
  // 2000+ plinko autobet rounds (blows any SHARED 2000-key FIFO) -> page
  // reload replays blackjack history. With per-game shards the archived hands
  // must stay dead.
  const { send } = await bootWorker();
  await send({ type: 'SQX_CLEAR_ALL' }); // fresh sessions; knownRounds survives by design
  for (let i = 0; i < 20; i++) await send(roundEvent('hand-' + i, 5, 10, 'blackjack'));
  await send({ type: 'SQX_NEW_SESSION', game: 'blackjack' });
  const flood = LIMITS.MAX_KNOWN_ROUND_IDS + 50;
  for (let i = 0; i < flood; i++) await send(roundEvent('storm-' + i));
  // Page reload: content-script seenRounds resets, site re-serves history.
  for (let i = 0; i < 20; i++) await send(roundEvent('hand-' + i, 5, 10, 'blackjack'));
  const snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.blackjack.rounds.length, 0); // no archived hand resurrects
  assert.equal(snap.active.blackjack.stats.rounds, 0);
  assert.equal(snap.active.blackjack.stats.net, 0);
  const bj = snap.archivedSummaries.filter((s) => s.game === 'blackjack');
  assert.equal(bj.length, 1);
  assert.equal(bj[0].rounds, 20); // lifetime: 20 real hands stay 20, not 40
  assert.equal(bj[0].net, 100); // money counted once, not 2x
  assert.equal(snap.active.plinko.stats.rounds, flood); // the storm itself is intact
  assert.equal(snap.active.plinko.stats.net, flood);
  // A genuinely new blackjack hand still lands after the flood.
  await send(roundEvent('hand-new', 5, 0, 'blackjack'));
  const snap2 = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap2.active.blackjack.stats.rounds, 1);
});

await atest('message path: legacy flat knownRounds in storage still dedupes, then migrates', async () => {
  await sleep(1200); // drain the previous worker's trailing save first
  const stored = JSON.parse(backend.get('sqxState'));
  stored.knownRounds = { keys: ['plinko:legacy-1', 'plinko:legacy-2'] }; // pre-shard shape
  backend.set('sqxState', JSON.stringify(stored));
  const { send } = await bootWorker();
  await send(roundEvent('legacy-1'));
  await send(roundEvent('legacy-2'));
  await send(roundEvent('legacy-3'));
  const snap = (await send({ type: 'SQX_GET_STATE' })).state;
  const ids = snap.active.plinko.rounds.map((r) => r.id);
  assert.equal(ids.includes('legacy-1'), false); // legacy memory still honored
  assert.equal(ids.includes('legacy-2'), false);
  assert.equal(ids.includes('legacy-3'), true); // new bets still land
  await sleep(1200); // flush, then confirm the persisted shape is sharded
  const after = JSON.parse(backend.get('sqxState'));
  assert.equal(Array.isArray(after.knownRounds.keys), false);
  assert.equal(after.knownRounds['g:plinko'].keys.includes('legacy-3'), true);
  assert.equal(after.knownRounds['g:plinko'].keys.includes('legacy-1'), true); // migrated, not lost
});

await atest('message path: failed storage writes surface persistFailing, then recover', async () => {
  await sleep(1200); // drain pending saves before toggling failures
  const { send } = await bootWorker();
  failWrites.on = true;
  await send(roundEvent('pf-1'));
  await sleep(20); // let the rejected write settle
  let snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.persistFailing, true); // consumers can warn: memory-only data
  failWrites.on = false;
  await sleep(1100); // past the debounce window: the next event writes at once
  await send(roundEvent('pf-2'));
  await sleep(20);
  snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.persistFailing, false);
  // The retried write carried BOTH rounds: a fresh worker rehydrates them.
  const w2 = await bootWorker();
  const snap2 = (await w2.send({ type: 'SQX_GET_STATE' })).state;
  const ids = snap2.active.plinko.rounds.map((r) => r.id);
  assert.ok(ids.includes('pf-1'), 'pf-1 persisted after recovery');
  assert.ok(ids.includes('pf-2'), 'pf-2 persisted after recovery');
});

await atest('message path: identical-outcome live autobet keeps counting across PAGE RELOADS', async () => {
  // The round-4 headline: normalize.js's live-repeat counter is page-local
  // while knownRounds is persistent, so after a reload the regenerated
  // synthetic-id sequence collided with remembered ids and every acked
  // genuine bet was silently dropped (200/200 lost). Real normalize.js per
  // "page load" (fresh vm sandbox) driving the real background listener.
  const { send } = await bootWorker();
  await send({ type: 'SQX_CLEAR_ALL' });
  const mults = [0.5, 1, 2, 5];
  const mkBody = (m) => ({ gameId: 'plinko-live', betAmount: 1, payoutMultiplier: m, payout: m });
  const runDrops = async (page, n) => {
    for (let i = 0; i < n; i++) {
      const r = page.extractRound({ ts: Date.now(), kind: 'ws', url: 'wss://spinquest.com/game', body: mkBody(mults[i % 4]) });
      await send({ type: 'SQX_GAME_EVENT', game: 'plinko', event: { type: 'round', round: r } });
    }
  };
  let page = loadNormalize(); // page load 1
  await runDrops(page, 30);
  let snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.plinko.stats.rounds, 30); // constant-id discovery loses nothing within one load
  page = loadNormalize(); // reload: page-local id memory resets, knownRounds doesn't
  await runDrops(page, 30);
  snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.plinko.stats.rounds, 60); // every genuine repeat re-suffixed and counted
  page = loadNormalize(); // third reload, shorter run
  await runDrops(page, 10);
  snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.plinko.stats.rounds, 70);
  assert.equal(snap.active.plinko.stats.wagered, 70); // each bet's money counted exactly once
  // Replay-shaped events keep DROP semantics: the same content re-fetched via
  // a history URL resolves deterministically and stays dead.
  const hist = page.extractRound({ ts: Date.now(), kind: 'fetch', url: 'https://spinquest.com/api/plinko/history', body: mkBody(0.5) });
  assert.equal(hist.live, undefined);
  await send({ type: 'SQX_GAME_EVENT', game: 'plinko', event: { type: 'round', round: hist } });
  snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.plinko.stats.rounds, 70); // history replay did not double-count
});

await atest('message path: live-repeat counter survives a WORKER RESTART (persisted in the shard)', async () => {
  await sleep(1200); // flush knownRounds (incl. the shard counter) to storage
  const { send } = await bootWorker(); // fresh module, same storage backend
  const page = loadNormalize(); // and a fresh page load
  const mults = [0.5, 1, 2, 5];
  for (let i = 0; i < 8; i++) {
    const r = page.extractRound({
      ts: Date.now(),
      kind: 'ws',
      url: 'wss://spinquest.com/game',
      body: { gameId: 'plinko-live', betAmount: 1, payoutMultiplier: mults[i % 4], payout: mults[i % 4] },
    });
    await send({ type: 'SQX_GAME_EVENT', game: 'plinko', event: { type: 'round', round: r } });
  }
  const snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.plinko.stats.rounds, 78); // 70 + all 8 genuine repeats
});

await atest('message path: ack -> NEW_SESSION -> settle upgrade repairs the ARCHIVED round', async () => {
  // Round-4 S7: a payout-less ack round rotated into the archive, then the
  // real settle (upgrade:true) missed the fresh session, fell through to
  // knownRounds and was dropped — archived wagered 25, net 0 forever.
  const { send } = await bootWorker();
  await send({ type: 'SQX_CLEAR_ALL' });
  await send({
    type: 'SQX_GAME_EVENT',
    game: 'mines',
    event: { type: 'round', round: { id: 'uar-1', ts: Date.now(), bet: 25, result: 'unknown' } },
  });
  await send({ type: 'SQX_NEW_SESSION', game: 'mines' });
  await send({
    type: 'SQX_GAME_EVENT',
    game: 'mines',
    event: { type: 'round', upgrade: true, round: { id: 'uar-1', ts: Date.now(), bet: 25, payout: 50, profit: 25, result: 'win' } },
  });
  const snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.mines.stats.rounds, 0); // settle patched the archive, not the live session
  const arch = snap.archivedSummaries.filter((s) => s.game === 'mines');
  assert.equal(arch.length, 1);
  assert.equal(arch[0].rounds, 1);
  assert.equal(arch[0].net, 25); // wagered 25, returned 50 — the real outcome landed
  assert.equal(arch[0].wins, 1);
});

await atest('message path: oversized state patches and ticks are dropped at the boundary', async () => {
  // Round-4 S4: event.patch / event.tick bypassed the sanitizer — one hostile
  // 400KiB patch persisted straight into the storage quota rounds protect.
  const { send } = await bootWorker();
  await send({ type: 'SQX_CLEAR_ALL' });
  await send({ type: 'SQX_GAME_EVENT', game: 'crash', event: { type: 'state', patch: { phase: 'flying', multiplier: 1.5 } } });
  let snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.crash.current.phase, 'flying'); // sane patch lands
  await send({ type: 'SQX_GAME_EVENT', game: 'crash', event: { type: 'state', patch: { phase: 'evil', blob: 'x'.repeat(400 * 1024) } } });
  snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.crash.current.phase, 'flying'); // oversized patch dropped whole
  assert.equal('blob' in snap.active.crash.current, false);
  await send({ type: 'SQX_GAME_EVENT', game: 'crash', event: { type: 'tick', tick: { ts: Date.now(), crashPoint: 2.1, blob: 'x'.repeat(64 * 1024) } } });
  await send({ type: 'SQX_GAME_EVENT', game: 'crash', event: { type: 'tick', tick: { ts: Date.now(), crashPoint: 3.5 } } });
  snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap.active.crash.ticks.length, 1); // oversized tick dropped, sane one kept
  assert.equal(snap.active.crash.ticks[0].crashPoint, 3.5);
  // Merged session.current is bounded too: distinct-keyed patches can't accrete without limit.
  for (let i = 0; i < 40; i++) {
    await send({ type: 'SQX_GAME_EVENT', game: 'crash', event: { type: 'state', patch: { ['k' + i]: 'y'.repeat(1000) } } });
  }
  snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.ok(JSON.stringify(snap.active.crash.current).length <= LIMITS.MAX_CURRENT_JSON + 2048, 'merged current stays bounded');
});

await atest('message path: unknown game names are refused loudly — no proto pollution, no shard churn', async () => {
  // Round-4 S5/S6: game '__proto__' acked {ok:true} while the round vanished
  // into prototype assignment, and 16 junk names churned real games' shards
  // out of the knownRounds cap. The boundary now allowlists KNOWN_GAMES and
  // answers {ok:false} — never a silent drop behind an {ok:true}.
  const { send } = await bootWorker();
  await send({ type: 'SQX_CLEAR_ALL' });
  await send(roundEvent('gv-1', 1, 2, 'roulette'));
  const evil = await send({
    type: 'SQX_GAME_EVENT',
    game: '__proto__',
    event: { type: 'round', round: { id: 'gv-p', ts: Date.now(), bet: 5, payout: 10, profit: 5, result: 'win' } },
  });
  assert.equal(evil.ok, false);
  assert.equal(Object.getPrototypeOf({}).rounds, undefined); // no pollution
  for (let g = 0; g < 20; g++) {
    assert.equal((await send(roundEvent('j' + g, 1, 0, 'junkgame' + g))).ok, false);
  }
  const snap = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.deepEqual(Object.keys(snap.active), ['roulette']); // junk never opened a session
  await send(roundEvent('gv-1', 1, 2, 'roulette')); // replay after the junk flood
  const snap2 = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap2.active.roulette.stats.rounds, 1); // replay protection intact — no shard churn
  assert.equal((await send({ type: 'SQX_NEW_SESSION', game: '__proto__' })).ok, false);
  assert.equal((await send({ type: 'SQX_GAME_EVENT', game: 'roulette', event: null })).ok, false); // event must be an object
});

await atest('message path: archived sessions compact to a bounded round tail, lifetime totals intact', async () => {
  // Round-4 S9: 30 archived max-detail sessions projected to 3.7x the storage
  // quota, eventually pinning the extension in memory-only mode.
  const { send } = await bootWorker();
  await send({ type: 'SQX_CLEAR_ALL' });
  const n = 120;
  for (let i = 0; i < n; i++) {
    await send({
      type: 'SQX_GAME_EVENT',
      game: 'blackjack',
      event: { type: 'round', round: { id: 'cmp-' + i, ts: Date.now(), bet: 1, payout: 2, profit: 1, result: 'win', detail: { hand: ['AS', 'KD'], actions: ['hit', 'stand'] } } },
    });
  }
  await send({ type: 'SQX_NEW_SESSION', game: 'blackjack' });
  const snap = (await send({ type: 'SQX_GET_STATE' })).state;
  const sum = snap.archivedSummaries.find((s) => s.game === 'blackjack');
  assert.equal(sum.rounds, n); // lifetime totals exact through compaction
  assert.equal(sum.net, n);
  const { data } = await send({ type: 'SQX_EXPORT' });
  const arch = data.archived.find((s) => s.game === 'blackjack');
  assert.equal(arch.compacted, true);
  assert.equal(arch.rounds.length, LIMITS.MAX_ARCHIVED_ROUNDS);
  assert.ok(arch.rounds.every((r) => !('detail' in r)), 'archived rounds carry no detail blobs');
  assert.equal(arch.stats.rounds, n); // stats recomputed over the compacted shape, still lifetime-exact
  // A compacted-away round replayed after reload still dedupes.
  await send({ type: 'SQX_GAME_EVENT', game: 'blackjack', event: { type: 'round', round: { id: 'cmp-0', ts: Date.now(), bet: 1, payout: 2, profit: 1, result: 'win' } } });
  const snap2 = (await send({ type: 'SQX_GET_STATE' })).state;
  assert.equal(snap2.active.blackjack.stats.rounds, 0);
});

// ----------------------------------------------------------------------------

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
