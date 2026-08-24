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
  MAX_KNOWN_ROUND_IDS: 2000, // cross-session dedupe memory, PER GAME (survives rotation)
  MAX_KNOWN_GAMES: 16, // shards in the cross-session memory (least-recent evicted)
  SNAPSHOT_ROUNDS_TAIL: 120, // rounds included per session in a broadcast snapshot
  // At/past this magnitude a "money" figure is a timestamp, an id, or garbage
  // — and cents(1e308) would overflow to Infinity, violating the no-Infinity
  // invariant one multiply past the sanitizer. Mirrors SQX.NUM_MAX upstream.
  MAX_ABS_MONEY: 1e12,
  MAX_ID_LEN: 128, // round ids longer than this are truncated (still deterministic)
  MAX_DETAIL_JSON: 4096, // detail blobs serializing past this are dropped whole
  // The other trust-boundary payloads, bounded like round.detail is: a state
  // patch or tick serializing past its cap is a hostile/buggy flood, not game
  // state — one 400KiB patch would burn the storage quota rounds are capped
  // to protect. MAX_CURRENT_JSON bounds the MERGED session.current, so many
  // small distinct-keyed patches can't accrete without bound either.
  MAX_PATCH_JSON: 8192,
  MAX_CURRENT_JSON: 16384,
  MAX_TICK_JSON: 1024,
  // Archived sessions are compacted to this round tail (detail stripped, the
  // rest folded into carry — totals stay exact). Uncompacted worst case is
  // ~4.75MB per 4 max-detail sessions: 30 archived + active would project to
  // ~3.7x the 10MB chrome.storage.local quota and pin the extension in
  // permanent memory-only mode once writes start failing.
  MAX_ARCHIVED_ROUNDS: 40,
};

// Games the background accepts at its message boundary (mirror of SQX.GAMES
// in lib/util.js — adapters can only ever emit these). An unvalidated
// msg.game would let a hostile sender ack rounds into '__proto__' (silently
// lost through prototype assignment) or churn junk names through the
// knownRounds shard cap until a real game's replay protection evicts.
export const KNOWN_GAMES = ['plinko', 'mines', 'crash', 'blackjack', 'roulette'];

export const round2 = (n) => Math.round(n * 100) / 100;
const round1 = (n) => Math.round(n * 10) / 10;
const isNum = Number.isFinite;
// Money guard: finite AND inside the magnitude cap. Every money read in the
// stats math uses this (not bare isNum) so even a legacy-persisted round with
// an absurd figure can never overflow the cents math into Infinity.
const isMoney = (n) => isNum(n) && Math.abs(n) < LIMITS.MAX_ABS_MONEY;
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
// time, so a replay looks freshly timed. So the background keeps a capped
// FIFO of appended round ids (state.knownRounds, persisted with the rest of
// the state) and consults it before appending, no matter which session the
// id first landed in.
//
// The memory is SHARDED PER GAME: a single shared FIFO would let high-volume
// autobet on one game evict another game's keys (2000 plinko drops arm that
// in under 4 minutes at ~10/s), so its archived rounds would resurrect as
// fresh live rounds on the next reload's history replay. Each game gets its
// own FIFO capped at MAX_KNOWN_ROUND_IDS — same per-game bound, immune to
// cross-game flooding — with the shard COUNT itself capped (hostile game
// strings can't grow the state without bound; least-recently-written shard
// evicted). Persisted shape (JSON-safe; a Set mirror per shard is cached in
// a WeakMap and rebuilt after storage round-trips so lookups are O(1), not a
// 2000-entry linear scan per round at autobet speed):
//   knownRounds = { ['g:' + game]: { keys: [id, ...], t: lastWriteMs,
//                                    n?: liveRepeatCounter } }
// ('g:' prefixing keeps hostile game names like "__proto__" inert.) The
// legacy flat shape ({keys: ["game:id", ...]}) is read in place by
// hasKnownRound and migrated to shards by the first rememberRound.

const knownSets = new WeakMap(); // shard -> Set(ids), rebuilt on cache miss

function shardSet(shard) {
  let s = knownSets.get(shard);
  if (!s || s.size !== shard.keys.length) {
    s = new Set(shard.keys);
    knownSets.set(shard, s);
  }
  return s;
}

function migrateKnownRounds(log) {
  if (!log || typeof log !== 'object') return {};
  if (!Array.isArray(log.keys)) return log; // already sharded
  const sharded = {};
  for (const key of log.keys) {
    const i = typeof key === 'string' ? key.indexOf(':') : -1;
    if (i <= 0) continue;
    const g = 'g:' + key.slice(0, i);
    const shard = sharded[g] || (sharded[g] = { keys: [], t: 0 });
    shard.keys.push(key.slice(i + 1));
  }
  return sharded;
}

/**
 * True when this game's round id was already appended to ANY session
 * (current, archived, or evicted) still inside that game's id-memory window.
 */
export function hasKnownRound(log, game, id) {
  if (id == null || !log || typeof log !== 'object') return false;
  if (Array.isArray(log.keys)) return log.keys.includes(game + ':' + id); // legacy flat shape
  const shard = log['g:' + game];
  if (!shard || !Array.isArray(shard.keys)) return false;
  return shardSet(shard).has(String(id));
}

/**
 * Record an appended round's id in its game's shard, evicting the oldest past
 * `max`. Returns the log (creating/migrating it when absent or legacy-shaped)
 * so callers can assign it back: `state.knownRounds = rememberRound(...)`.
 */
export function rememberRound(log, game, id, max = LIMITS.MAX_KNOWN_ROUND_IDS, now = Date.now()) {
  if (id == null) return log;
  log = migrateKnownRounds(log);
  const shard = getShard(log, game);
  shard.t = now;
  const set = shardSet(shard);
  const key = String(id);
  if (set.has(key)) return log;
  shard.keys.push(key);
  set.add(key);
  while (shard.keys.length > max) set.delete(shard.keys.shift());
  return log;
}

/** A game's shard, created (evicting the least-recently-written shard past
 *  the count cap) when absent. `log` must already be shard-shaped. */
function getShard(log, game) {
  let shard = log['g:' + game];
  if (!shard || !Array.isArray(shard.keys)) {
    const games = Object.keys(log);
    if (games.length >= LIMITS.MAX_KNOWN_GAMES) {
      let oldest = null;
      for (const g of games) {
        if (oldest === null || (log[g].t || 0) < (log[oldest].t || 0)) oldest = g;
      }
      if (oldest !== null) delete log[oldest];
    }
    shard = log['g:' + game] = { keys: [], t: 0 };
  }
  return shard;
}

/**
 * Allocate a collision-free variant of a LIVE round's id after a dedupe hit.
 * A live round whose id collides with the known-round memory is a genuine
 * identical-outcome repeat whose page-local synthetic-id counter reset on
 * reload (normalize.js regenerates 'sqx-SIG', 'sqx-SIG#2', ... from #1 every
 * page load, while this memory persists) — dropping it would silently eat
 * every bet of an identical-outcome autobet run after a reload. Uniqueness
 * must come from where the dedupe memory lives, so the suffix counter
 * (`shard.n`) is persisted IN the game's shard: it survives worker restarts
 * and page reloads alike, and can only move forward. Returns { log, id } —
 * callers assign the log back and append under the new id (replay-shaped
 * events must NOT come through here; they keep drop semantics).
 */
export function liveRepeatId(log, game, id, now = Date.now()) {
  log = migrateKnownRounds(log);
  const shard = getShard(log, game);
  shard.t = now;
  const set = shardSet(shard);
  const base = String(id).slice(0, LIMITS.MAX_ID_LEN - 14); // room for '~' + counter
  let next;
  do {
    shard.n = (Number.isInteger(shard.n) && shard.n >= 0 ? shard.n : 0) + 1;
    next = base + '~' + shard.n;
  } while (set.has(next));
  return { log, id: next };
}

// --- round sanitizing ---------------------------------------------------------

/**
 * Whitelist-copy a round at the trust boundary (content script → background).
 * computeStats already guards every numeric read, but sanitizing on append
 * makes the "no NaN/Infinity/garbage in persisted rounds" invariant local to
 * one place instead of distributed across every consumer. Unknown fields are
 * dropped; malformed known fields are dropped (money) or defaulted (ts,
 * result) rather than poisoning storage. Bounds enforced here:
 *  - money/multiplier magnitude < MAX_ABS_MONEY: a finite-but-absurd figure
 *    (1e308) would overflow the cents math to Infinity one multiply later;
 *  - id length ≤ MAX_ID_LEN (truncated, deterministically, so dedupe on the
 *    truncated id still works) and detail ≤ MAX_DETAIL_JSON serialized (a
 *    megabyte detail blob would burn the chrome.storage.local quota in a
 *    handful of rounds and silently kill every later save).
 */
export function sanitizeRound(raw, now = Date.now()) {
  const r = raw && typeof raw === 'object' ? raw : {};
  let id = typeof r.id === 'string' || (typeof r.id === 'number' && isNum(r.id)) ? r.id : null;
  if (typeof id === 'string' && id.length > LIMITS.MAX_ID_LEN) id = id.slice(0, LIMITS.MAX_ID_LEN);
  const round = {
    id,
    ts: isNum(r.ts) ? r.ts : now,
    result: r.result === 'win' || r.result === 'loss' || r.result === 'push' ? r.result : 'unknown',
  };
  if (isMoney(r.bet) && r.bet >= 0) round.bet = r.bet;
  if (isMoney(r.payout) && r.payout >= 0) round.payout = r.payout;
  if (isMoney(r.profit)) round.profit = r.profit;
  if (isMoney(r.multiplier) && r.multiplier >= 0) round.multiplier = r.multiplier;
  if (typeof r.currency === 'string' && r.currency.length < 32) round.currency = r.currency;
  if (r.detail && typeof r.detail === 'object' && !Array.isArray(r.detail)) {
    try {
      const json = JSON.stringify(r.detail);
      if (typeof json === 'string' && json.length <= LIMITS.MAX_DETAIL_JSON) round.detail = r.detail;
    } catch {
      // circular / hostile detail — dropped, the round itself survives
    }
  }
  return round;
}

/**
 * Trust-boundary gate for the non-round event payloads: a plain object whose
 * serialized size fits `cap` passes through untouched, anything else
 * (array/scalar/circular/oversized) returns null and the caller drops the
 * event. Rounds get the field-by-field treatment in sanitizeRound; patches
 * and ticks are free-form by design, so a size bound is the invariant —
 * without it one hostile 400KiB state patch persists straight into the
 * storage quota that MAX_DETAIL_JSON exists to protect.
 */
export function boundedPlainObject(obj, cap) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return null;
  try {
    const json = JSON.stringify(obj);
    if (typeof json !== 'string' || json.length > cap) return null;
  } catch {
    return null; // circular / hostile serializer
  }
  return obj;
}

export const sanitizePatch = (patch) => boundedPlainObject(patch, LIMITS.MAX_PATCH_JSON);
export const sanitizeTick = (tick) => boundedPlainObject(tick, LIMITS.MAX_TICK_JSON);

/**
 * Replace a previously appended payout-LESS round with a payout-bearing one
 * carrying the same id (the ack-then-push API shape: a placement ack that
 * slipped through as a result-unknown round, followed by the real settle).
 * Only an upgrade — same id, stored round lacks a payout, new round has one —
 * qualifies; returns false otherwise so the caller falls back to normal
 * dedupe. Only the kept window is searched: an evicted round's totals are
 * already folded into carry and can't be unwound.
 */
export function upgradeRound(session, round) {
  if (round.id == null || !isNum(round.payout)) return false;
  const i = session.rounds.findIndex((r) => r.id === round.id);
  if (i < 0 || isNum(session.rounds[i].payout)) return false;
  session.rounds[i] = round;
  return true;
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
  while (session.rounds.length > max) evictOldest(session);
}

/** Shift the oldest round off the window, folding its totals (and id) into
 *  session.carry. Shared by the append cap and archive compaction. */
function evictOldest(session) {
  const ev = session.rounds.shift();
  const c = session.carry || (session.carry = emptyCarry());
  c.rounds++;
  if (ev.result === 'win') c.wins++;
  else if (ev.result === 'loss') c.losses++;
  else if (ev.result === 'push') c.pushes++;
  if (isMoney(ev.bet)) c.wageredC += cents(ev.bet);
  if (isMoney(ev.payout)) c.returnedC += cents(ev.payout);
  if (isMoney(ev.profit)) {
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

/**
 * Shrink a session for the archive: all but the newest MAX_ARCHIVED_ROUNDS
 * rounds are folded into carry through the same eviction path the live cap
 * uses (lifetime totals, streaks and dedupe ids stay exact), and per-round
 * detail is dropped from the kept tail. Rationale: 30 archived sessions of
 * max-detail rounds would serialize far past the chrome.storage.local quota
 * — persistFailing would surface it, but nothing would shed the load, so the
 * extension would pin itself in memory-only mode. The popup renders archived
 * sessions from their summary; the tail is kept for export/inspection.
 * Callers should recompute stats afterwards so the cached series shrinks too.
 */
export function compactSession(session, max = LIMITS.MAX_ARCHIVED_ROUNDS) {
  while (session.rounds.length > max) evictOldest(session);
  for (const r of session.rounds) delete r.detail;
  session.compacted = true;
  return session;
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
    if (isMoney(r.bet)) wageredC += cents(r.bet);
    if (isMoney(r.payout)) returnedC += cents(r.payout);
    if (isMoney(r.profit)) {
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
