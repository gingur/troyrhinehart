// Mines adapter. A game is a sequence of tile reveals ending in a cashout or
// a mine hit, so we track in-progress state (the current "deal") and emit a
// round only when the game resolves.
'use strict';

SQX.adapters.push({
  game: 'mines',

  match(evt, activeGame) {
    if (SQX.mentions(evt, 'mines?')) return true;
    if (activeGame !== 'mines') return false;
    return SQX.hasKey(evt.body, /^(mines?|mineCount|mine_count|tiles?|revealed|grid|cells?|gems?)$/i);
  },

  parse(evt) {
    if (evt.direction !== 'in') return [];
    const body = evt.body;

    // History payloads: a list of settled games, one round per entry.
    const list = SQX.roundsFromList(evt, (round, item) => {
      round.detail = {
        mines: SQX.deepNum(item, /^(mines?|mineCount|mine_count|bombs?)$/i),
        revealedCount: SQX.deepNum(item, /^(revealedCount|revealed_count|picksCount)$/i),
      };
    });
    if (list) return list;

    const mineCount = SQX.deepNum(body, /^(mines?|mineCount|mine_count|bombs?)$/i);
    const revealed = SQX.deepFind(body, /^(revealed|revealedTiles|opened|picks|selectedTiles)$/i, (v) => Array.isArray(v));
    const status = SQX.deepStr(body, SQX.KEYS.state);
    const detail = {
      mines: mineCount,
      revealedCount: Array.isArray(revealed) ? revealed.length : SQX.deepNum(body, /^(revealedCount|revealed_count|picksCount)$/i),
      revealed: Array.isArray(revealed) ? revealed.slice(0, 30) : undefined,
      gridSize: SQX.deepNum(body, /^(gridSize|grid_size|size|tilesTotal)$/i),
    };

    const busted = /bust|lost|exploded|mine_hit|gameover|game_over/i.test(status || '') ||
      SQX.deepFind(body, /^(exploded|busted|hitMine|hit_mine)$/i, (v) => v === true) === true;
    const settled = busted || SQX.looksSettled(evt);

    if (!settled) {
      // In-progress reveal: update the current deal with running multiplier.
      // A null-riddled body ({tiles:null, bet:null, ...}) yields no signal at
      // all — emit nothing rather than an empty "revealing" patch.
      const multiplier = SQX.deepNum(body, SQX.KEYS.multiplier);
      const bet = SQX.deepNum(body, SQX.KEYS.bet);
      const hasSignal =
        detail.mines !== undefined || detail.revealedCount !== undefined ||
        detail.revealed !== undefined || detail.gridSize !== undefined ||
        multiplier !== undefined || bet !== undefined;
      if (!hasSignal) return [];
      return [{
        type: 'state',
        patch: { phase: 'revealing', detail, multiplier, bet },
      }];
    }

    const round = SQX.extractRound(evt);
    if (!round) return [];
    if (busted) {
      round.result = 'loss';
      if (round.bet !== undefined) {
        round.payout = 0;
        round.profit = -round.bet;
      }
    }
    round.detail = detail;
    return [{ type: 'round', round }];
  },
});
