// Plinko adapter. Each drop settles immediately: bet in, ball path + landing
// multiplier out. Detail captured: risk level, row count, landing slot/path.
'use strict';

SQX.adapters.push({
  game: 'plinko',

  match(evt, activeGame) {
    return SQX.mentions(evt, 'plinko') || activeGame === 'plinko';
  },

  parse(evt) {
    if (evt.direction !== 'in') return [];
    const round = SQX.extractRound(evt);
    if (!round) return [];

    const body = evt.body;
    round.detail = {
      risk: SQX.deepStr(body, /^(risk|riskLevel|risk_level|difficulty)$/i),
      rows: SQX.deepNum(body, /^(rows|rowCount|row_count|pins|lines)$/i),
      slot: SQX.deepNum(body, /^(slot|bucket|index|slotIndex|bucket_index)$/i),
      path: SQX.deepFind(body, /^(path|route|directions|drops)$/i, (v) => Array.isArray(v)),
    };

    return [{ type: 'round', round }];
  },
});
