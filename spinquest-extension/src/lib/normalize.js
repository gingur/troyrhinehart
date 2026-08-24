// Heuristic extraction of the common round fields (bet, payout, multiplier,
// result) from arbitrary casino API payloads. Adapters call these and then
// layer game-specific detail on top.
//
// Round ids are extracted with a two-tier ranking: per-bet keys (betId,
// roundId, nonce, ...) always beat page-constant-ish keys (gameId, id, ...)
// no matter how deep they sit. On top of that, a constant-id detector watches
// for the same extracted id arriving with different payload content — the
// signature of a payload-constant key like gameId — and switches those rounds
// to deterministic synthetic ids so the dedupe layers (content.js seenRounds,
// background hasRound) never silently drop real rounds. Exact byte-identical
// replays (history re-fetches) keep the same id so dedupe still catches them.
'use strict';

SQX.KEYS = {
  bet: /^(bet|betAmount|bet_amount|wager|stake|amount)$/i,
  // bet without the ambiguous `amount` — used when path context matters.
  betCore: /^(bet|betAmount|bet_amount|betValue|bet_value|wager|stake)$/i,
  amount: /^(amount|value|total)$/i,
  payout: /^(payout|payoutAmount|payout_amount|win|winAmount|win_amount|reward|returned)$/i,
  // Net-profit-shaped keys: value is payout MINUS bet, not gross payout.
  net: /^(profit|netProfit|net_profit|netWin|net_win|netGain|net_gain)$/i,
  multiplier: /^(multiplier|payoutMultiplier|payout_multiplier|mult|odds|coefficient|crashPoint|crash_point)$/i,
  currency: /^(currency|coin|token|asset)$/i,
  // Ranked: strong keys are per-bet by convention; weak ones are often
  // payload constants (a gameId names the game, not the round).
  roundIdStrong: /^(betId|bet_id|roundId|round_id|ticketId|ticket_id|txId|tx_id|nonce|hash)$/i,
  roundIdWeak: /^(gameId|game_id|id|uuid)$/i,
  state: /^(state|status|phase)$/i,
  // Display-identity keys: an array whose elements carry these is a public
  // multiplayer bet board (everyone's bets), not the player's own history.
  playerName: /^(username|user_name|playerName|player_name|nickname|displayName|display_name|avatar)$/i,
};

const SQX_ID_OK = (value) =>
  (typeof value === 'string' && value !== '' && value.length < 120) ||
  (typeof value === 'number' && Number.isFinite(value));

/** First strong-keyed id anywhere in the tree; weak-keyed id as fallback. */
SQX.findRoundId = function findRoundId(body) {
  const r = SQX.findRoundIdRanked(body);
  return r ? r.id : undefined;
};

/** Like findRoundId but reports whether the winning key was per-bet-strong. */
SQX.findRoundIdRanked = function findRoundIdRanked(body) {
  let strong;
  let weak;
  SQX.walk(body, (key, value) => {
    if (strong !== undefined) return;
    if (!SQX_ID_OK(value)) return;
    if (SQX.KEYS.roundIdStrong.test(key)) strong = value;
    else if (weak === undefined && SQX.KEYS.roundIdWeak.test(key)) weak = value;
  });
  if (strong !== undefined) return { id: strong, strong: true };
  if (weak !== undefined) return { id: weak, strong: false };
  return null;
};

/**
 * First strong-keyed (per-bet) id only — weak ids (gameId, id) are never
 * consulted. Used for tick identity, where a payload-constant weak id would
 * wrongly collapse every tick into one.
 */
SQX.findStrongId = function findStrongId(body) {
  let found;
  SQX.walk(body, (key, value) => {
    if (found !== undefined) return;
    if (SQX_ID_OK(value) && SQX.KEYS.roundIdStrong.test(key)) found = value;
  });
  return found;
};

/**
 * Id for SHARED-outcome ticks. Prefers round-shaped keys (roundId) over
 * bet-shaped ones (betId, nonce): a personal settle frame carries both, and
 * keying its tick by betId would re-tick a crash point the broadcast frame
 * already recorded under roundId.
 */
const SQX_TICK_ROUND_KEY = /^(roundId|round_id|gameRoundId|game_round_id)$/i;
SQX.findTickId = function findTickId(body) {
  let roundKeyed;
  let strong;
  SQX.walk(body, (key, value) => {
    if (roundKeyed !== undefined) return;
    if (!SQX_ID_OK(value)) return;
    if (SQX_TICK_ROUND_KEY.test(key)) roundKeyed = value;
    else if (strong === undefined && SQX.KEYS.roundIdStrong.test(key)) strong = value;
  });
  return roundKeyed !== undefined ? roundKeyed : strong;
};

/**
 * The payload half of a socket.io-style `["event:name", {...}]` pair (an
 * optional ack callback slot may follow). Array ELEMENTS are never keyed
 * values, so key-driven walks (LIST_KEYS scans) cannot see a bare array at
 * body[1] — list-detection paths must probe this unwrapping explicitly.
 */
SQX.sioPayload = function sioPayload(body) {
  if (
    Array.isArray(body) && body.length >= 2 && body.length <= 3 &&
    typeof body[0] === 'string' && body[0].length < 200 &&
    body[1] !== null && typeof body[1] === 'object'
  ) return body[1];
  return undefined;
};

(() => {
  const ID_MEMORY_MAX = 200;
  const BAD_IDS_MAX = 50;
  const idSig = new Map(); // extracted id -> content signature of its first round
  const badIds = new Set(); // ids proven payload-constant (repeat w/ different content)

  /**
   * Content signature of a round payload: full-body hash + the money legs.
   * Capture time (evt.ts) is deliberately excluded so a byte-identical
   * history replay signs the same and keeps its original id for dedupe.
   */
  function contentSig(body, bet, payout) {
    let raw = '';
    try {
      raw = JSON.stringify(body) || '';
    } catch {
      // circular / hostile body — fall back to the money legs only
    }
    let h = 0x811c9dc5; // FNV-1a 32-bit
    for (let i = 0; i < raw.length; i++) {
      h ^= raw.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return (h >>> 0).toString(36) + ':' + (bet ?? '') + ':' + (payout ?? '');
  }

  /**
   * Resolve the id for a round. A candidate id seen before with DIFFERENT
   * content is a payload constant — it (and every later occurrence) gets a
   * deterministic synthetic id instead, so no real round collides away.
   */
  SQX.resolveRoundId = function resolveRoundId(body, bet, payout) {
    const found = SQX.findRoundIdRanked(body);
    if (!found) return SQX.shortId();
    const id = String(found.id);
    // Strong keys (betId, roundId, nonce, ...) are per-bet by convention:
    // trust them outright. Running them through the constant-id detector would
    // misfire on history refetches whose entries differ only by a volatile
    // field (a server timestamp, a seq) — same betId, different bytes — and
    // the synthetic fallback would double-count the round.
    if (found.strong) return id;
    const sig = contentSig(body, bet, payout);
    if (badIds.has(id)) return 'sqx-' + sig;
    const prev = idSig.get(id);
    if (prev === undefined) {
      idSig.set(id, sig);
      if (idSig.size > ID_MEMORY_MAX) idSig.delete(idSig.keys().next().value);
      return id;
    }
    if (prev === sig) return id; // exact replay of the same round — keep id, let dedupe drop it
    badIds.add(id);
    if (badIds.size > BAD_IDS_MAX) badIds.delete(badIds.values().next().value);
    return 'sqx-' + sig;
  };

  /** Test hook: forget id history (a fresh page load does this naturally). */
  SQX._resetRoundIds = function _resetRoundIds() {
    idSig.clear();
    badIds.clear();
  };
})();

// Sitewide win feeds push ONE bet at a time, and real feeds (Stake et al.)
// carry per-entry bet ids — so "has a strong id" is not proof a namey object
// is OUR settle echo. When the payload names a feed/broadcast channel
// anywhere (event:"feed:win", channel:"bigwin", ...), namey objects are
// dropped even when id-bearing.
const SQX_FEED_CHAN_KEY = /^(event|channel|topic|room|type|name)$/i;
const SQX_FEED_WORD = /(feed|broadcast|bigwin|big[-_]win|highroller|high[-_]roller|leaderboard|top[-_]?win|luckywin|lucky[-_]win)/i;
const SQX_IS_FEEDISH = (body) =>
  SQX.deepFind(body, SQX_FEED_CHAN_KEY, (v) =>
    typeof v === 'string' && v.length < 200 && SQX_FEED_WORD.test(v)
  ) !== undefined ||
  (Array.isArray(body) && typeof body[0] === 'string' && body[0].length < 200 && SQX_FEED_WORD.test(body[0]));

/**
 * Deep-clone a payload with public multiplayer content removed, so
 * extractRound never mistakes another player's bet for ours:
 *  - arrays whose elements carry display-identity keys (username, avatar,
 *    ...) are the whole table's bets — dropped wholesale;
 *  - a LONE object with a display-identity own key is a broadcast about some
 *    player ("bigwin by whale42") — dropped too, unless it also carries a
 *    per-bet strong id (a personal settle echoing our own username is keyed)
 *    AND the payload doesn't name a feed/broadcast channel (win feeds carry
 *    per-entry bet ids too — the channel word outranks the id).
 * Plain-data payloads only (everything here came out of JSON.parse /
 * structuredClone), so the clone is cheap and cycle-free.
 */
SQX.stripPublicBoards = function stripPublicBoards(node, depth = 0, feedish) {
  if (node === null || typeof node !== 'object' || depth > 6) return node;
  if (feedish === undefined) feedish = SQX_IS_FEEDISH(node);
  if (Array.isArray(node)) {
    const objs = node.filter((el) => el && typeof el === 'object' && !Array.isArray(el));
    if (objs.length) {
      const namey = objs.reduce((c, el) => c + (SQX.hasKey(el, SQX.KEYS.playerName) ? 1 : 0), 0);
      if (namey * 2 >= objs.length) return undefined; // drop the board wholesale
    }
    const out = [];
    for (const el of node) {
      const v = SQX.stripPublicBoards(el, depth + 1, feedish);
      if (v !== undefined) out.push(v);
    }
    return out;
  }
  const keys = Object.keys(node);
  if (keys.some((k) => SQX.KEYS.playerName.test(k)) &&
      (feedish || SQX.findStrongId(node) === undefined)) {
    return undefined; // somebody's broadcast, not our bet
  }
  const out = {};
  for (const key of keys) {
    const v = SQX.stripPublicBoards(node[key], depth + 1, feedish);
    if (v !== undefined) out[key] = v;
  }
  return out;
};

// Money legs may be scalars ({payout: 4.4}), nested objects
// ({payout: {amount: "4.40", currency: "usd"}}), or a bare `amount` at the
// top ({amount: 5, state: "settled"}). The bare-amount fallback is path-vetoed
// so `payout.amount` / `winnings.amount` never masquerade as the bet — and
// EVERY money-leg walk is vetoed under wallet-shaped envelopes: a
// `balance.amount` push or a `user.profit` delta is account state, never a
// round's stake or return.
const SQX_WALLET_BAN = /(balance|wallet|account|user)/i;
const SQX_AMOUNT_BAN = /(payout|win|reward|returned|profit|net|balance|wallet|account|user)/i;

// Integer minor-unit money: {amount: 121000000, currency: "btc", scale: 8}
// means 1.21, not 121 million. Applied only when both the amount and the
// scale are integers — a float amount is already in major units.
const SQX_SCALE_KEY = /^(scale|decimals|exponent)$/i;

const SQX_MONEY_LEG = (body, keyRe) => {
  const direct = SQX.deepMoneyAt(body, keyRe, SQX_WALLET_BAN);
  if (direct !== undefined) return direct;
  let nested;
  SQX.walk(body, (key, value, path) => {
    if (nested !== undefined) return;
    if (!keyRe.test(key)) return;
    if (SQX_WALLET_BAN.test(path)) return;
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) nested = value;
  });
  if (nested === undefined) return undefined;
  const amount = SQX.deepMoney(nested, SQX.KEYS.amount);
  if (amount === undefined) return undefined;
  const scale = SQX.deepNum(nested, SQX_SCALE_KEY);
  if (Number.isInteger(amount) && Number.isInteger(scale) && scale >= 2 && scale <= 18) {
    return amount / Math.pow(10, scale);
  }
  return amount;
};

/** The bet leg, shared by extractRound and looksSettled: real bet keys, then
 *  a bare `amount` outside payout/net/wallet paths. */
const SQX_BET_LEG = (body) => {
  const bet = SQX_MONEY_LEG(body, SQX.KEYS.betCore);
  return bet !== undefined ? bet : SQX.deepMoneyAt(body, /^amount$/i, SQX_AMOUNT_BAN);
};

// Status words that mean "this bet is finished" wherever they appear in a
// state/status/phase field.
const SQX_SETTLED_STATUS = /^(complete|completed|settled|finished|resolved|cashout|cashed_out|busted|lost|won|ended)$/i;

// Status words that mean "this bet is NOT finished": the bet-placement ack
// (`{betId, bet, state:"placed"}`) of every ack-then-push API. These veto all
// settled heuristics — an ack must never become a round, or the real settle
// arriving seconds later on the same betId gets deduped away.
const SQX_PLACED_STATUS = /^(placed|pending|accepted|open|created|queued|awaiting)$/i;

// Multi-leg settles: a blackjack split (or multi-seat) payload carries its
// money in a `hands` array — one bet/payout pair per hand. The round is the
// SUM of the legs; taking hands[0] alone halves the stake and misreports the
// outcome (win 10 on one hand + lose 5 on the other is a push, not a win).
const SQX_HANDS_KEY = /^(hands|splitHands|split_hands|seats)$/i;
const SQX_MULTI_HAND = (v) =>
  Array.isArray(v) && v.length >= 2 && v.length <= 8 &&
  v.every((el) => el && typeof el === 'object' && !Array.isArray(el) &&
    SQX_MONEY_LEG(el, SQX.KEYS.betCore) !== undefined);

const SQX_HAND_LEGS = (body) => {
  const hands = SQX.deepFind(body, SQX_HANDS_KEY, SQX_MULTI_HAND);
  if (!hands) return null;
  let bet = 0;
  let payout;
  for (const el of hands) {
    bet += SQX_MONEY_LEG(el, SQX.KEYS.betCore);
    const p = SQX_MONEY_LEG(el, SQX.KEYS.payout);
    if (p !== undefined) payout = (payout ?? 0) + p;
  }
  return { bet: SQX.round2(bet), payout: payout === undefined ? undefined : SQX.round2(payout) };
};

/**
 * Extract the shared skeleton of a completed round from a payload.
 * Returns null when the payload doesn't look like a bet/round at all.
 */
SQX.extractRound = function extractRound(evt) {
  try {
    return SQX._extractRound(evt);
  } catch {
    return null; // hostile shape — a failed extraction must never throw upward
  }
};

SQX._extractRound = function _extractRound(evt) {
  const body = SQX.stripPublicBoards(evt.body);
  const legs = SQX_HAND_LEGS(body); // split/multi-seat payloads: sum the hands
  const bet = legs ? legs.bet : SQX_BET_LEG(body);
  let payout = legs && legs.payout !== undefined ? legs.payout : SQX_MONEY_LEG(body, SQX.KEYS.payout);
  const net = SQX.deepNumAt(body, SQX.KEYS.net, SQX_WALLET_BAN); // signed: profit-shaped keys are net of the bet
  // Per-hand multipliers don't describe the summed round — derive instead.
  const multiplier = legs ? undefined : SQX.deepMoney(body, SQX.KEYS.multiplier);

  // A round needs at least one money leg to be meaningful.
  if (bet === undefined && payout === undefined && net === undefined) return null;

  // A payout/net leg WITHOUT a bet needs corroboration that this is our
  // settled bet: a per-bet strong id or an explicit settled status. A lone
  // {win: 1250.5} broadcast or wallet {profit: 2.5} delta has neither.
  if (bet === undefined) {
    const status = SQX.deepStr(body, SQX.KEYS.state);
    const settledWord = status !== undefined && SQX_SETTLED_STATUS.test(status);
    const strong = SQX.findStrongId(body) !== undefined;
    if (!settledWord && !strong) return null;
    // profit:0 as the ONLY money evidence is the shape of a round-end
    // broadcast to spectators ({status:"finished", profit:0}) — settled
    // status is broadcast to everyone, so it needs a per-bet id on top.
    if (payout === undefined && net === 0 && !strong) return null;
  }

  const round = {
    id: SQX.resolveRoundId(body, bet, payout ?? net),
    ts: evt.ts || Date.now(),
    bet: bet,
    payout: payout,
    multiplier: multiplier,
    currency: SQX.deepStr(body, SQX.KEYS.currency),
  };

  // Derive what we can: a net-profit field beats a multiplier for the missing
  // payout leg (it's exact); payout = bet * multiplier otherwise.
  if (round.payout === undefined && round.bet !== undefined && net !== undefined) {
    round.payout = Math.max(0, SQX.round2(round.bet + net));
  }
  if (round.payout === undefined && round.bet !== undefined && round.multiplier !== undefined) {
    round.payout = SQX.round2(round.bet * round.multiplier);
  }
  if (round.multiplier === undefined && round.bet > 0 && round.payout !== undefined) {
    round.multiplier = SQX.round2(round.payout / round.bet);
  }

  if (round.bet !== undefined && round.payout !== undefined) {
    round.profit = SQX.round2(round.payout - round.bet);
    round.result = round.profit > 0 ? 'win' : round.profit < 0 ? 'loss' : 'push';
  } else if (net !== undefined) {
    // Net-only payload (no usable bet/payout legs): keep the outcome.
    round.profit = SQX.round2(net);
    round.result = round.profit > 0 ? 'win' : round.profit < 0 ? 'loss' : 'push';
  } else {
    round.result = 'unknown';
  }

  return round;
};

/** True when the payload looks like a settled bet rather than an in-flight state. */
SQX.looksSettled = function looksSettled(evt) {
  try {
    const status = SQX.deepStr(evt.body, SQX.KEYS.state);
    if (status) {
      if (SQX_PLACED_STATUS.test(status)) return false; // explicit "not settled yet"
      if (SQX_SETTLED_STATUS.test(status)) return true;
    }
    // A payout (or net profit) figure alongside a bet is a strong settled
    // signal. Same wallet-path vetoes as extractRound: a balance push with a
    // profit delta must not read as "our bet settled".
    const bet = SQX_BET_LEG(evt.body);
    if (bet === undefined) return false;
    return SQX_MONEY_LEG(evt.body, SQX.KEYS.payout) !== undefined ||
      SQX.deepNumAt(evt.body, SQX.KEYS.net, SQX_WALLET_BAN) !== undefined;
  } catch {
    return false;
  }
};

/**
 * Weaker settle gate for adapters whose fall-through would otherwise emit a
 * round from ANY money-bearing payload: is there positive evidence the bet is
 * finished — a settled status word, or a payout/net leg (outside wallet
 * envelopes)? A bet-placement ack ({betId, bet, state:"placed"}) has neither
 * and must become a state patch, not a round: emitting the ack as a
 * result-unknown round makes the dedupe layers drop the REAL settle that
 * arrives seconds later under the same betId.
 */
SQX.hasSettledEvidence = function hasSettledEvidence(evt) {
  try {
    const status = SQX.deepStr(evt.body, SQX.KEYS.state);
    if (status) {
      if (SQX_PLACED_STATUS.test(status)) return false;
      if (SQX_SETTLED_STATUS.test(status)) return true;
    }
    const body = SQX.stripPublicBoards(evt.body);
    const legs = SQX_HAND_LEGS(body);
    if (legs && legs.payout !== undefined) return true;
    return SQX_MONEY_LEG(body, SQX.KEYS.payout) !== undefined ||
      SQX.deepNumAt(body, SQX.KEYS.net, SQX_WALLET_BAN) !== undefined;
  } catch {
    return false;
  }
};

// --- batched / history payloads ----------------------------------------------
// Real APIs deliver settled rounds in arrays at least as often as one at a
// time: history endpoints, GraphQL connections, autobet batches. These
// helpers find such a list and map every entry through extractRound.

SQX.LIST_KEYS = /^(results?|rounds?|history|bets?|items|list|entries|data|records|games|edges|nodes)$/i;

/** Does this list element look like one settled bet of the player's own? */
SQX._roundish = function _roundish(el) {
  if (!el || typeof el !== 'object' || Array.isArray(el)) return false;
  if (SQX.hasKey(el, SQX.KEYS.payout) || SQX.hasKey(el, SQX.KEYS.net)) return true;
  return SQX.findStrongId(el) !== undefined && SQX.hasKey(el, SQX.KEYS.bet);
};

/**
 * Find an array of settled-round-like objects: the body itself, or the first
 * qualifying array under a list-ish key (results, history, data, edges, ...).
 * Arrays whose elements carry display-identity keys are public multiplayer
 * bet boards — everyone's bets, not ours — and never qualify.
 */
SQX.findRoundArray = function findRoundArray(body) {
  const qualifies = (arr) => {
    if (!Array.isArray(arr) || !arr.length || arr.length > 500) return false;
    if (!arr.every((el) => el && typeof el === 'object' && !Array.isArray(el))) return false;
    const namey = arr.reduce((c, el) => c + (SQX.hasKey(el, SQX.KEYS.playerName) ? 1 : 0), 0);
    if (namey * 2 >= arr.length) return false;
    const n = arr.reduce((c, el) => c + (SQX._roundish(el) ? 1 : 0), 0);
    return n >= 1 && n * 2 >= arr.length;
  };
  if (qualifies(body)) return body;
  // socket.io pair with a BARE array payload: ["game:history", [...]] — the
  // array is an element, not a keyed value, so the walk below can't see it.
  const sio = SQX.sioPayload(body);
  if (sio !== undefined && qualifies(sio)) return sio;
  let found;
  SQX.walk(body, (key, value) => {
    if (found !== undefined) return;
    if (SQX.LIST_KEYS.test(key) && qualifies(value)) found = value;
  });
  return found;
};

/**
 * Per-entry timestamp of a history item, normalized to epoch ms (seconds are
 * scaled). Undefined when absent or implausible — callers fall back to the
 * capture time.
 */
SQX.itemTs = function itemTs(item) {
  const raw = SQX.deepFind(
    item,
    /^(ts|time|timestamp|createdAt|created_at|settledAt|settled_at|playedAt|played_at|date)$/i,
    (v) => typeof v === 'number' && Number.isFinite(v)
  );
  if (raw === undefined) return undefined;
  if (raw > 1e12 && raw < 1e13) return raw; // epoch ms
  if (raw > 1e9 && raw < 1e10) return Math.round(raw * 1000); // epoch seconds
  return undefined;
};

/**
 * Adapter helper: when the payload is a list of settled rounds, return one
 * `{type:'round'}` event per extractable entry (capped), else null so the
 * caller falls through to its single-payload logic. `decorate(round, item)`
 * lets adapters attach per-entry detail; a throwing decorator is contained.
 */
SQX.roundsFromList = function roundsFromList(evt, decorate) {
  let list;
  try {
    list = SQX.findRoundArray(evt.body);
  } catch {
    return null;
  }
  if (!list) return null;
  const out = [];
  for (const item of list.slice(0, 50)) {
    if (!SQX._roundish(item)) continue;
    const round = SQX.extractRound({ ts: SQX.itemTs(item) ?? evt.ts, body: item });
    if (!round) continue;
    if (decorate) {
      try {
        decorate(round, item);
      } catch {
        /* a bad decorator loses detail, never the round */
      }
    }
    out.push({ type: 'round', round });
  }
  return out.length ? out : null;
};
