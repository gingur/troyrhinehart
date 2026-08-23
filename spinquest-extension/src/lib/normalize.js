// Heuristic extraction of the common round fields (bet, payout, multiplier,
// result) from arbitrary casino API payloads. Adapters call these and then
// layer game-specific detail on top.
'use strict';

SQX.KEYS = {
  bet: /^(bet|betAmount|bet_amount|wager|stake|amount)$/i,
  payout: /^(payout|payoutAmount|win|winAmount|win_amount|profit|reward|returned)$/i,
  multiplier: /^(multiplier|payoutMultiplier|payout_multiplier|mult|odds|coefficient|crashPoint|crash_point)$/i,
  currency: /^(currency|coin|token|asset)$/i,
  roundId: /^(roundId|round_id|gameId|game_id|betId|bet_id|id|nonce|hash)$/i,
  state: /^(state|status|phase)$/i,
};

/**
 * Extract the shared skeleton of a completed round from a payload.
 * Returns null when the payload doesn't look like a bet/round at all.
 */
SQX.extractRound = function extractRound(evt) {
  const body = evt.body;
  const bet = SQX.deepNum(body, SQX.KEYS.bet);
  const payout = SQX.deepNum(body, SQX.KEYS.payout);
  const multiplier = SQX.deepNum(body, SQX.KEYS.multiplier);

  // A round needs at least a bet or a payout to be meaningful.
  if (bet === undefined && payout === undefined) return null;

  const round = {
    id: String(SQX.deepFind(body, SQX.KEYS.roundId, (v) => typeof v === 'string' || typeof v === 'number') ?? SQX.shortId()),
    ts: evt.ts || Date.now(),
    bet: bet,
    payout: payout,
    multiplier: multiplier,
    currency: SQX.deepStr(body, SQX.KEYS.currency),
  };

  // Derive what we can: payout = bet * multiplier when one leg is missing.
  if (round.payout === undefined && round.bet !== undefined && round.multiplier !== undefined) {
    round.payout = SQX.round2(round.bet * round.multiplier);
  }
  if (round.multiplier === undefined && round.bet > 0 && round.payout !== undefined) {
    round.multiplier = SQX.round2(round.payout / round.bet);
  }

  if (round.bet !== undefined && round.payout !== undefined) {
    round.profit = SQX.round2(round.payout - round.bet);
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
  // A payout figure alongside a bet is a strong settled signal.
  const bet = SQX.deepNum(evt.body, SQX.KEYS.bet);
  const payout = SQX.deepNum(evt.body, SQX.KEYS.payout);
  return bet !== undefined && payout !== undefined;
};
