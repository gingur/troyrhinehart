// Crash adapter. Two data streams matter: the shared game (rising multiplier,
// then the crash point — usually over WebSocket) and the player's own bet /
// cashout. Crash points are recorded even on rounds the player sat out, since
// the recent-crash list is half the point of watching. History payloads (a
// list of past rounds) yield one tick per entry — id-tagged when the entry
// carries a per-round id, so a refetch dedupes cleanly.
'use strict';

const SQX_CRASH_POINT = /^(crashPoint|crash_point|crashedAt|crashed_at|bustedAt|bustPoint|bust_point)$/i;

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

    // History/batch payloads: a list of past rounds, each with its own crash
    // point and sometimes the player's own bet on it.
    const hist = SQX.deepFind(body, SQX.LIST_KEYS, (v) =>
      Array.isArray(v) && v.length > 0 && v.length <= 500 &&
      v.every((x) => x && typeof x === 'object' && !Array.isArray(x)) &&
      v.filter((x) => SQX.hasKey(x, SQX_CRASH_POINT)).length * 2 >= v.length
    );
    if (hist) {
      for (const item of hist.slice(0, 60)) {
        const cp = SQX.deepNum(item, SQX_CRASH_POINT);
        if (cp === undefined) continue;
        const tick = { ts: SQX.itemTs(item) ?? evt.ts, crashPoint: cp };
        const tid = SQX.findStrongId(item);
        if (tid !== undefined) tick.id = tid;
        out.push({ type: 'tick', tick });
        if (SQX._roundish(item)) {
          const round = SQX.extractRound({ ts: tick.ts, body: item });
          if (round) {
            round.detail = { crashPoint: cp };
            out.push({ type: 'round', round });
          }
        }
      }
      return out;
    }

    const crashPoint = SQX.deepNum(body, SQX_CRASH_POINT);
    const liveMult = SQX.deepNum(body, /^(multiplier|currentMultiplier|current_multiplier|mult)$/i);
    const status = SQX.deepStr(body, SQX.KEYS.state) || '';

    if (crashPoint !== undefined || /crash|bust|ended/i.test(status)) {
      // Shared round ended. Record the crash point regardless of participation.
      const endPoint = crashPoint ?? liveMult;
      if (endPoint !== undefined) {
        const tick = { ts: evt.ts, crashPoint: endPoint };
        const tid = SQX.findStrongId(SQX.stripPublicBoards(body));
        if (tid !== undefined) tick.id = tid;
        out.push({ type: 'tick', tick });
      }
      const round = SQX.extractRound(evt);
      if (round) {
        round.detail = { crashPoint: endPoint, cashedOutAt: SQX.deepNum(body, /^(cashout|cashOut|cashoutAt|cashout_at|cashedOutAt)$/i) };
        out.push({ type: 'round', round });
      } else {
        out.push({ type: 'state', patch: { phase: 'crashed', detail: { crashPoint: endPoint } } });
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
