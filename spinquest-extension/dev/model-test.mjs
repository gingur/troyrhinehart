#!/usr/bin/env node
// Plain-node tests for the pure session/stats math in src/lib/stats.js —
// the exact module the background service worker imports. No framework:
//   node dev/model-test.mjs
// Exits non-zero on the first failing group; prints one line per test.
'use strict';

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
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
  hasRound,
  makeSummary,
  refreshPace,
  round2,
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
  const r = N.extractRound({ ts: T0, body: { bet: -5, payout: 0 } });
  assert.equal(r.bet, undefined); // negative bet rejected
  assert.notEqual(r.result, 'win'); // and certainly not a +5 win
  const skip = N.extractRound({ ts: T0, body: { amount: -3, betAmount: 2, payout: 4 } });
  assert.equal(skip.bet, 2); // walk skips the negative match, finds the real one
  assert.equal(skip.profit, 2);
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

// ----------------------------------------------------------------------------

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
