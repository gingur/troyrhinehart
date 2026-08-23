// Crash adapter. Two data streams matter: the shared game (rising multiplier,
// then the crash point — usually over WebSocket) and the player's own bet /
// cashout. Crash points are recorded even on rounds the player sat out, since
// the recent-crash list is half the point of watching.
'use strict';

SQX.adapters.push({
  game: 'crash',

  match(evt, activeGame) {
    if (SQX.mentions(evt, 'crash')) return true;
    if (activeGame !== 'crash') return false;
    return SQX.hasKey(evt.body, /^(crashPoint|crash_point|cashout|cashOut|cashout_at|autoCashout)$/i);
  },

  parse(evt) {
    if (evt.direction !== 'in') return [];
    const body = evt.body;
    const out = [];

    const crashPoint = SQX.deepNum(body, /^(crashPoint|crash_point|crashedAt|crashed_at|bustedAt)$/i);
    const liveMult = SQX.deepNum(body, /^(multiplier|currentMultiplier|current_multiplier|mult)$/i);
    const status = SQX.deepStr(body, SQX.KEYS.state) || '';

    if (crashPoint !== undefined || /crash|bust|ended/i.test(status)) {
      // Shared round ended. Record the crash point regardless of participation.
      out.push({ type: 'tick', tick: { ts: evt.ts, crashPoint: crashPoint ?? liveMult } });
      const round = SQX.extractRound(evt);
      if (round) {
        round.detail = { crashPoint: crashPoint ?? liveMult, cashedOutAt: SQX.deepNum(body, /^(cashout|cashOut|cashoutAt|cashout_at|cashedOutAt)$/i) };
        out.push({ type: 'round', round });
      } else {
        out.push({ type: 'state', patch: { phase: 'crashed', detail: { crashPoint: crashPoint ?? liveMult } } });
      }
      return out;
    }

    if (liveMult !== undefined) {
      // Rising multiplier tick — update the current deal only.
      return [{ type: 'state', patch: { phase: 'flying', multiplier: liveMult } }];
    }

    const round = SQX.extractRound(evt);
    if (round && SQX.looksSettled(evt)) {
      round.detail = { cashedOutAt: round.multiplier };
      return [{ type: 'round', round }];
    }
    if (round) {
      return [{ type: 'state', patch: { phase: 'betting', bet: round.bet } }];
    }
    return [];
  },
});
