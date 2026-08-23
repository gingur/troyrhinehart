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
  payout: /^(payout|payoutAmount|win|winAmount|win_amount|reward|returned)$/i,
  // Net-profit-shaped keys: value is payout MINUS bet, not gross payout.
  net: /^(profit|netProfit|net_profit|netWin|net_win|netGain|net_gain)$/i,
  multiplier: /^(multiplier|payoutMultiplier|payout_multiplier|mult|odds|coefficient|crashPoint|crash_point)$/i,
  currency: /^(currency|coin|token|asset)$/i,
  // Ranked: strong keys are per-bet by convention; weak ones are often
  // payload constants (a gameId names the game, not the round).
  roundIdStrong: /^(betId|bet_id|roundId|round_id|ticketId|ticket_id|txId|tx_id|nonce|hash)$/i,
  roundIdWeak: /^(gameId|game_id|id|uuid)$/i,
  state: /^(state|status|phase)$/i,
};

/** First strong-keyed id anywhere in the tree; weak-keyed id as fallback. */
SQX.findRoundId = function findRoundId(body) {
  let strong;
  let weak;
  SQX.walk(body, (key, value) => {
    if (strong !== undefined) return;
    const ok =
      (typeof value === 'string' && value !== '' && value.length < 120) ||
      (typeof value === 'number' && Number.isFinite(value));
    if (!ok) return;
    if (SQX.KEYS.roundIdStrong.test(key)) strong = value;
    else if (weak === undefined && SQX.KEYS.roundIdWeak.test(key)) weak = value;
  });
  return strong !== undefined ? strong : weak;
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
    const found = SQX.findRoundId(body);
    if (found === undefined) return SQX.shortId();
    const id = String(found);
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

/**
 * Extract the shared skeleton of a completed round from a payload.
 * Returns null when the payload doesn't look like a bet/round at all.
 */
SQX.extractRound = function extractRound(evt) {
  const body = evt.body;
  const bet = SQX.deepMoney(body, SQX.KEYS.bet);
  let payout = SQX.deepMoney(body, SQX.KEYS.payout);
  const net = SQX.deepNum(body, SQX.KEYS.net); // signed: profit-shaped keys are net of the bet
  const multiplier = SQX.deepMoney(body, SQX.KEYS.multiplier);

  // A round needs at least one money leg to be meaningful.
  if (bet === undefined && payout === undefined && net === undefined) return null;

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
  const status = SQX.deepStr(evt.body, SQX.KEYS.state);
  if (status && /^(complete|completed|settled|finished|resolved|cashout|cashed_out|busted|lost|won|ended)$/i.test(status)) {
    return true;
  }
  // A payout (or net profit) figure alongside a bet is a strong settled signal.
  const bet = SQX.deepMoney(evt.body, SQX.KEYS.bet);
  if (bet === undefined) return false;
  return SQX.deepMoney(evt.body, SQX.KEYS.payout) !== undefined ||
    SQX.deepNum(evt.body, SQX.KEYS.net) !== undefined;
};
