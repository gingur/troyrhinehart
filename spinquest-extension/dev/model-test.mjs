#!/usr/bin/env node
// Plain-node tests for the pure session/stats math in src/lib/stats.js —
// the exact module the background service worker imports. No framework:
//   node dev/model-test.mjs
// Exits non-zero on the first failing group; prints one line per test.
'use strict';

import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const devDir = dirname(fileURLToPath(import.meta.url));
const {
  LIMITS,
  appendRound,
  appendTick,
  computeStats,
  createSession,
  gameExtras,
  hasData,
  makeSummary,
  round2,
} = await import(join(devDir, '..', 'src', 'lib', 'stats.js'));

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

// ----------------------------------------------------------------------------

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
