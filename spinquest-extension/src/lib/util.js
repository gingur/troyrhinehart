// Shared namespace + helpers for the isolated-world scripts. Content scripts
// listed in the manifest share one global scope; everything hangs off SQX.
'use strict';

var SQX = window.SQX || (window.SQX = { adapters: [] });

SQX.GAMES = ['plinko', 'mines', 'crash', 'blackjack', 'roulette'];

/** Walk an object tree (depth-capped) calling visit(key, value, path). */
SQX.walk = function walk(obj, visit, path = '', depth = 0) {
  if (obj == null || depth > 6) return;
  if (Array.isArray(obj)) {
    for (let i = 0; i < Math.min(obj.length, 50); i++) {
      SQX.walk(obj[i], visit, path + '[' + i + ']', depth + 1);
    }
    return;
  }
  if (typeof obj === 'object') {
    for (const key of Object.keys(obj)) {
      const value = obj[key];
      visit(key, value, path ? path + '.' + key : key);
      SQX.walk(value, visit, path ? path + '.' + key : key, depth + 1);
    }
  }
};

/**
 * Find the first value in an object tree whose key matches `keyRe` and whose
 * value passes `accept` (default: finite number, possibly numeric string).
 */
SQX.deepFind = function deepFind(obj, keyRe, accept) {
  let found;
  SQX.walk(obj, (key, value) => {
    if (found !== undefined) return;
    if (!keyRe.test(key)) return;
    if (accept ? accept(value) : value !== undefined && value !== null) found = value;
  });
  return found;
};

// Anything at or past this magnitude is not money or a multiplier — it's a
// timestamp, a big-int-ish id, or garbage. Also the ceiling for accepting
// string-encoded numbers.
SQX.NUM_MAX = 1e12;

/**
 * Parse a raw payload value as a number: numbers pass through, numeric
 * strings ("1.23", " 2 ") convert. Everything else returns NaN — including
 * big-int-ish strings too long to represent exactly (those are ids, and
 * Number() would silently corrupt them) and absurd magnitudes.
 */
SQX.parseNum = function parseNum(v) {
  let n;
  if (typeof v === 'number') n = v;
  else if (typeof v === 'string') {
    const t = v.trim();
    if (!t || t.length > 24) return NaN;
    n = Number(t);
  } else return NaN;
  return Number.isFinite(n) && Math.abs(n) < SQX.NUM_MAX ? n : NaN;
};

/** deepFind specialized to numbers ("12.5" counts). Returns undefined if absent. */
SQX.deepNum = function deepNum(obj, keyRe) {
  const raw = SQX.deepFind(obj, keyRe, (v) => !Number.isNaN(SQX.parseNum(v)));
  return raw === undefined ? undefined : SQX.parseNum(raw);
};

/**
 * deepNum restricted to sane non-negative values — bets, payouts and
 * multipliers are never negative, so a negative match (a balance delta, a
 * signed net) is skipped and the walk keeps looking for a better key.
 */
SQX.deepMoney = function deepMoney(obj, keyRe) {
  const raw = SQX.deepFind(obj, keyRe, (v) => {
    const n = SQX.parseNum(v);
    return !Number.isNaN(n) && n >= 0;
  });
  return raw === undefined ? undefined : SQX.parseNum(raw);
};

/**
 * deepMoney with a path veto: skips matches whose dotted path also matches
 * `banRe`. Lets a bare `amount` count as the bet while `payout.amount` stays
 * the payout's.
 */
SQX.deepMoneyAt = function deepMoneyAt(obj, keyRe, banRe) {
  let found;
  SQX.walk(obj, (key, value, path) => {
    if (found !== undefined) return;
    if (!keyRe.test(key)) return;
    if (banRe && banRe.test(path)) return;
    const n = SQX.parseNum(value);
    if (!Number.isNaN(n) && n >= 0) found = n;
  });
  return found;
};

SQX.deepStr = function deepStr(obj, keyRe) {
  return SQX.deepFind(obj, keyRe, (v) => typeof v === 'string' && v.length < 200);
};

/** True if any key in the tree matches keyRe. */
SQX.hasKey = function hasKey(obj, keyRe) {
  return SQX.deepFind(obj, keyRe, () => true) !== undefined;
};

/** Case-insensitive check that the URL or any key hints at a game name. */
SQX.mentions = function mentions(evt, word) {
  const re = new RegExp(word, 'i');
  if (re.test(String(evt.url || ''))) return true;
  const body = evt.body;
  // socket.io-style frames arrive as ["event:name", {...}] — the event name
  // is often the only place the game is spelled out.
  if (Array.isArray(body) && typeof body[0] === 'string' && body[0].length < 200 && re.test(body[0])) {
    return true;
  }
  return SQX.deepFind(body, /^(game|type|gameName|game_type|kind|slug|event|channel|topic)$/i, (v) =>
    typeof v === 'string' && v.length < 200 && re.test(v)
  ) !== undefined;
};

SQX.round2 = (n) => Math.round(n * 100) / 100;

SQX.shortId = () => Math.random().toString(36).slice(2, 10);
