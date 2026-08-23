// Blackjack adapter. Tracks the live deal (player/dealer hands and totals as
// cards arrive) and emits a round when the hand settles. Card arrays are kept
// in the detail so the HUD can render the actual hand.
'use strict';

SQX.adapters.push({
  game: 'blackjack',

  match(evt, activeGame) {
    if (SQX.mentions(evt, 'blackjack')) return true;
    if (activeGame !== 'blackjack') return false;
    return SQX.hasKey(evt.body, /^(dealer|dealerHand|dealer_hand|playerHand|player_hand|cards|hand)$/i);
  },

  parse(evt) {
    if (evt.direction !== 'in') return [];
    const body = evt.body;

    const pickHand = (re) =>
      SQX.deepFind(body, re, (v) => Array.isArray(v) && v.length && v.length <= 12);

    const playerCards = pickHand(/^(playerHand|player_hand|playerCards|player_cards|hand|cards)$/i);
    const dealerCards = pickHand(/^(dealerHand|dealer_hand|dealerCards|dealer_cards)$/i);

    const detail = {
      player: playerCards,
      dealer: dealerCards,
      playerTotal: SQX.deepNum(body, /^(playerTotal|player_total|playerValue|player_value|playerScore)$/i),
      dealerTotal: SQX.deepNum(body, /^(dealerTotal|dealer_total|dealerValue|dealer_value|dealerScore)$/i),
      actions: SQX.deepFind(body, /^(actions|allowedActions|allowed_actions|moves)$/i, (v) => Array.isArray(v)),
    };

    const status = SQX.deepStr(body, SQX.KEYS.state) || '';
    const outcome = SQX.deepStr(body, /^(outcome|result|winner)$/i) || '';
    const settled =
      /win|lose|lost|push|bust|blackjack|settled|complete|finished/i.test(status + ' ' + outcome) ||
      SQX.looksSettled(evt);

    if (!settled) {
      if (!playerCards && !dealerCards) return [];
      return [{ type: 'state', patch: { phase: 'in-hand', detail, bet: SQX.deepNum(body, SQX.KEYS.bet) } }];
    }

    const round = SQX.extractRound(evt);
    if (!round) return [];
    if (/push|tie|draw/i.test(status + ' ' + outcome)) round.result = 'push';
    round.detail = { ...detail, outcome: outcome || status };
    return [{ type: 'round', round }];
  },
});
