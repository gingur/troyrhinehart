// Plinko adapter. Each drop settles immediately: bet in, ball path + landing
// multiplier out. Detail captured: risk level, row count, landing slot/path.
// Autobet batches and history refetches arrive as arrays of drops — each
// entry becomes its own round.
'use strict';

const SQX_PLINKO_DETAIL = (src) => ({
  risk: SQX.deepStr(src, /^(risk|riskLevel|risk_level|difficulty)$/i),
  rows: SQX.deepNum(src, /^(rows|rowCount|row_count|pins|lines)$/i),
  slot: SQX.deepNum(src, /^(slot|bucket|index|slotIndex|bucket_index)$/i),
  path: SQX.deepFind(src, /^(path|route|directions|drops)$/i, (v) => Array.isArray(v)),
});

SQX.adapters.push({
  game: 'plinko',

  match(evt, activeGame) {
    return SQX.mentions(evt, 'plinko') || activeGame === 'plinko';
  },

  parse(evt) {
    if (evt.direction !== 'in') return [];

    const list = SQX.roundsFromList(evt, (round, item) => {
      round.detail = SQX_PLINKO_DETAIL(item);
    });
    if (list) return list;

    const round = SQX.extractRound(evt);
    if (!round) return [];
    // A drop settles instantly, so a real plinko round always carries settle
    // evidence (a payout/net leg or a settled status). A money-bearing
    // payload WITHOUT it is a bet-placement ack ({betId, bet, state:
    // "placed"}) — recording it as a round would make the dedupe layers drop
    // the real settle pushed seconds later under the same betId. There is no
    // meaningful in-flight phase for an instant game: emit nothing and let
    // the settle frame carry the round.
    if (!SQX.hasSettledEvidence(evt)) return [];
    round.detail = SQX_PLINKO_DETAIL(evt.body);
    return [{ type: 'round', round }];
  },
});
