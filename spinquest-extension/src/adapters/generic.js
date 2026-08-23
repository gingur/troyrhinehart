// Fallback adapter: when no game-specific adapter claims an event but the
// payload still looks like a settled bet on a known game page, record it so
// the session ledger stays complete. Must stay LAST in the manifest's script
// order — content.js takes the first adapter whose match() returns true.
'use strict';

SQX.adapters.push({
  game: null, // resolves to whatever game page is active

  match(evt, activeGame) {
    return activeGame != null;
  },

  parse(evt) {
    if (evt.direction !== 'in' || !SQX.looksSettled(evt)) return [];
    const round = SQX.extractRound(evt);
    if (!round) return [];
    round.detail = { source: 'generic' };
    return [{ type: 'round', round }];
  },
});
