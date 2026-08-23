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

/** deepFind specialized to numbers ("12.5" counts). Returns undefined if absent. */
SQX.deepNum = function deepNum(obj, keyRe) {
  const raw = SQX.deepFind(obj, keyRe, (v) => {
    if (typeof v === 'number') return Number.isFinite(v);
    if (typeof v === 'string') return v !== '' && Number.isFinite(Number(v));
    return false;
  });
  return raw === undefined ? undefined : Number(raw);
};

/**
 * deepNum restricted to sane non-negative values — bets, payouts and
 * multipliers are never negative, so a negative match (a balance delta, a
 * signed net) is skipped and the walk keeps looking for a better key.
 */
SQX.deepMoney = function deepMoney(obj, keyRe) {
  const raw = SQX.deepFind(obj, keyRe, (v) => {
    const n = typeof v === 'number' ? v : typeof v === 'string' && v !== '' ? Number(v) : NaN;
    return Number.isFinite(n) && n >= 0;
  });
  return raw === undefined ? undefined : Number(raw);
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
  if (re.test(evt.url)) return true;
  return SQX.deepFind(evt.body, /^(game|type|gameName|game_type|kind|slug)$/i, (v) =>
    typeof v === 'string' && re.test(v)
  ) !== undefined;
};

SQX.round2 = (n) => Math.round(n * 100) / 100;

SQX.shortId = () => Math.random().toString(36).slice(2, 10);
