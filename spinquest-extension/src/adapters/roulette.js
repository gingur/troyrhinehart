// Roulette adapter. Captures the winning number for every spin (fuel for the
// hot/cold + color/parity breakdown) and the player's own bets when present.
// Spin-history payloads (arrays of past numbers, plain or object-shaped)
// yield one tick per entry — id-tagged when possible so refetches dedupe.
'use strict';

const SQX_ROULETTE_RED = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);
const SQX_ROULETTE_NUM = /^(winningNumber|winning_number|pocket|wheelResult|wheel_result|resultNumber|result_number|number)$/i;

const SQX_ROULETTE_COLOR = (n) =>
  n === 0 ? 'green' : SQX_ROULETTE_RED.has(n) ? 'red' : 'black';

// A pocket value as a European wheel number. American "00" (a string — there
// is no numeric 00) must NOT coerce to 0: the pipeline has no double-zero
// representation, and recording a green single-zero that never happened is
// worse than skipping the spin.
const SQX_ROULETTE_POCKET = (v) => {
  if (typeof v === 'string' && /^\s*0\d/.test(v)) return undefined; // "00", "000"
  const n = SQX.parseNum(v);
  return Number.isInteger(n) && n >= 0 && n <= 36 ? n : undefined;
};

/** First pocket-valued number under a winning-number key, "00"-safe. */
const SQX_ROULETTE_FIND_NUM = (obj) => {
  let found;
  SQX.walk(obj, (key, value) => {
    if (found !== undefined) return;
    if (!SQX_ROULETTE_NUM.test(key)) return;
    const n = SQX_ROULETTE_POCKET(value);
    if (n !== undefined) found = n;
  });
  return found;
};

SQX.adapters.push({
  game: 'roulette',

  match(evt, activeGame) {
    if (SQX.mentions(evt, 'roulette')) return true;
    if (activeGame !== 'roulette') return false;
    return SQX.hasKey(evt.body, /^(winningNumber|winning_number|pocket|wheelResult|wheel_result)$/i);
  },

  parse(evt) {
    if (evt.direction !== 'in') return [];
    const body = evt.body;
    const out = [];

    // Spin history: an array of past winning numbers — plain integers
    // ({history:[32,0,15]}) or objects each carrying a number key. Also
    // probed on the unwrapped socket.io payload (["roulette:history", [...]])
    // since a bare array element is invisible to key-driven walks.
    const histQualifies = (v) => {
      if (!Array.isArray(v) || !v.length || v.length > 500) return false;
      if (v.length >= 3 && v.every((x) => Number.isInteger(x) && x >= 0 && x <= 36)) return true;
      return (
        v.every((x) => x && typeof x === 'object' && !Array.isArray(x)) &&
        v.filter((x) => SQX.hasKey(x, SQX_ROULETTE_NUM)).length * 2 >= v.length
      );
    };
    let hist = SQX.deepFind(body, /^(history|results?|spins?|numbers|past|recent|last)$/i, histQualifies);
    if (!hist) {
      const sio = SQX.sioPayload(body);
      if (sio !== undefined && histQualifies(sio)) hist = sio;
    }
    if (hist) {
      for (const item of hist.slice(0, 60)) {
        const isObj = item !== null && typeof item === 'object';
        const n = isObj ? SQX_ROULETTE_FIND_NUM(item) : item;
        if (!Number.isInteger(n) || n < 0 || n > 36) continue;
        const tick = {
          ts: (isObj ? SQX.itemTs(item) : undefined) ?? evt.ts,
          number: n,
          color: SQX_ROULETTE_COLOR(n),
        };
        const tid = isObj ? SQX.findTickId(item) : undefined;
        if (tid !== undefined) tick.id = tid;
        out.push({ type: 'tick', tick });
        if (isObj && SQX._roundish(item)) {
          const round = SQX.extractRound({ ts: tick.ts, body: item });
          if (round) {
            round.detail = { number: n, color: tick.color };
            out.push({ type: 'round', round });
          }
        }
      }
      return out;
    }

    const number = SQX_ROULETTE_FIND_NUM(body);

    if (number !== undefined) {
      const color = SQX_ROULETTE_COLOR(number);
      const tick = { ts: evt.ts, number, color };
      const tid = SQX.findTickId(SQX.stripPublicBoards(body));
      if (tid !== undefined) tick.id = tid;
      out.push({ type: 'tick', tick });

      const round = SQX.extractRound(evt);
      if (round) {
        round.detail = {
          number,
          color,
          parity: number === 0 ? 'zero' : number % 2 === 0 ? 'even' : 'odd',
          bets: SQX.deepFind(body, /^(bets|placedBets|placed_bets|positions)$/i, (v) => Array.isArray(v)),
        };
        out.push({ type: 'round', round });
      } else {
        out.push({ type: 'state', patch: { phase: 'result', detail: { number, color } } });
      }
      return out;
    }

    // Fall-through without a winning number: settle evidence (payout/net leg
    // or settled status) gates round emission — a bet-placement ack is a
    // betting patch, never a round.
    const round = SQX.extractRound(evt);
    if (round && SQX.hasSettledEvidence(evt)) {
      out.push({ type: 'round', round });
    } else if (round) {
      out.push({ type: 'state', patch: { phase: 'betting', bet: round.bet } });
    }
    return out;
  },
});
