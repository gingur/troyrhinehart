// Roulette adapter. Captures the winning number for every spin (fuel for the
// hot/cold + color/parity breakdown) and the player's own bets when present.
'use strict';

const SQX_ROULETTE_RED = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);

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

    const number = SQX.deepNum(
      body,
      /^(winningNumber|winning_number|pocket|wheelResult|wheel_result|resultNumber|result_number|number)$/i
    );

    const out = [];
    if (number !== undefined && number >= 0 && number <= 36) {
      const color = number === 0 ? 'green' : SQX_ROULETTE_RED.has(number) ? 'red' : 'black';
      out.push({ type: 'tick', tick: { ts: evt.ts, number, color } });

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

    const round = SQX.extractRound(evt);
    if (round && SQX.looksSettled(evt)) {
      out.push({ type: 'round', round });
    } else if (round) {
      out.push({ type: 'state', patch: { phase: 'betting', bet: round.bet } });
    }
    return out;
  },
});
