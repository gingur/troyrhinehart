// Deterministic fixture snapshots for the dev harness. Every fixture is a
// full background-broadcast snapshot: { focusedGame, active, archivedSummaries }
// (see background.js snapshot()). Stats are computed with the same rules as
// background.js computeStats()/gameExtras() so numbers are self-consistent.
//
// Plain script (no modules) so it loads in the mock page via <script> and in
// Node via reading globalThis after import. Exposes:
//   globalThis.__SQX_FIXTURES  — { name: { state, rawLog } }
'use strict';

(() => {
  // --- tiny seeded PRNG (mulberry32) — stable output across runs ------------
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0;
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const r2 = (n) => Math.round(n * 100) / 100;

  // Fixed "now" so timestamps (and the HUD's HH:MM rendering) are stable.
  // Parsed as local time on purpose — screenshots match the machine's clock fmt.
  const NOW = Date.parse('2026-08-23T20:05:00');
  const MIN = 60 * 1000;

  // --- stats replica of src/lib/stats.js -------------------------------------
  // Kept in sync with the canonical ES module (computeStats/gameExtras there):
  // integer-cent money math, push-transparent streaks, cumulative-net series,
  // duration/pace, best/worst streak runs. Fixture sessions never exceed the
  // 300-round cap, so the carry/eviction branch is intentionally omitted.
  const isNum = Number.isFinite;
  const r1 = (n) => Math.round(n * 10) / 10;
  const cents = (n) => Math.round(n * 100);

  function stepStreak(run, result) {
    if (result === 'win') return run > 0 ? run + 1 : 1;
    if (result === 'loss') return run < 0 ? run - 1 : -1;
    if (result === 'push') return run;
    return 0;
  }

  function computeStats(session, now) {
    const rounds = session.rounds;
    const stats = {
      rounds: rounds.length, wins: 0, losses: 0, pushes: 0,
      biggestWin: 0, biggestLoss: 0, streak: 0,
    };
    let wageredC = 0, returnedC = 0, netC = 0;
    const series = [];
    let run = 0, bestWinStreak = 0, worstLossStreak = 0;
    for (const r of rounds) {
      if (r.result === 'win') stats.wins++;
      else if (r.result === 'loss') stats.losses++;
      else if (r.result === 'push') stats.pushes++;
      if (isNum(r.bet)) wageredC += cents(r.bet);
      if (isNum(r.payout)) returnedC += cents(r.payout);
      if (isNum(r.profit)) {
        netC += cents(r.profit);
        if (r.profit > stats.biggestWin) stats.biggestWin = r.profit;
        if (r.profit < stats.biggestLoss) stats.biggestLoss = r.profit;
      }
      run = stepStreak(run, r.result);
      if (run > bestWinStreak) bestWinStreak = run;
      if (run < worstLossStreak) worstLossStreak = run;
      series.push({ ts: isNum(r.ts) ? r.ts : null, net: netC / 100 });
    }
    stats.wagered = wageredC / 100;
    stats.returned = returnedC / 100;
    stats.net = netC / 100;
    stats.biggestWin = r2(stats.biggestWin);
    stats.biggestLoss = r2(stats.biggestLoss);
    const decided = stats.wins + stats.losses;
    stats.winRate = decided ? Math.round((stats.wins / decided) * 100) : null;
    stats.bestWinStreak = bestWinStreak;
    stats.worstLossStreak = worstLossStreak;
    stats.series = series;
    for (let i = rounds.length - 1; i >= 0; i--) {
      const res = rounds[i].result;
      if (res === 'push') continue;
      if (res !== 'win' && res !== 'loss') break;
      const dir = res === 'win' ? 1 : -1;
      if (stats.streak === 0) stats.streak = dir;
      else if (Math.sign(stats.streak) === dir) stats.streak += dir;
      else break;
    }
    const endAt = isNum(session.endedAt) ? session.endedAt : (now ?? NOW);
    stats.durationMs = Math.max(0, endAt - (isNum(session.startedAt) ? session.startedAt : endAt));
    stats.betsPerMinute =
      stats.durationMs >= 1000 ? r1((stats.rounds * 60000) / stats.durationMs) : null;
    stats.extra = gameExtras(session);
    return stats;
  }

  function median(sorted) {
    const n = sorted.length;
    if (!n) return null;
    const mid = n >> 1;
    return n % 2 ? sorted[mid] : r2((sorted[mid - 1] + sorted[mid]) / 2);
  }

  function gameExtras(session) {
    const { game, rounds, ticks } = session;
    if (game === 'crash') {
      const points = ticks.map((t) => t.crashPoint).filter(isNum);
      if (!points.length) return null;
      const sorted = [...points].sort((a, b) => a - b);
      return {
        label: 'crash points (all rounds seen)',
        count: points.length,
        median: median(sorted),
        under2x: Math.round((points.filter((p) => p < 2).length / points.length) * 100) + '%',
        last: points.slice(-15).reverse(),
      };
    }
    if (game === 'roulette') {
      const nums = ticks.map((t) => t.number).filter(isNum);
      if (!nums.length) return null;
      const freq = {};
      let red = 0, black = 0, green = 0;
      for (const t of ticks) {
        if (!isNum(t.number)) continue;
        freq[t.number] = (freq[t.number] || 0) + 1;
        if (t.color === 'red') red++;
        else if (t.color === 'black') black++;
        else if (t.color === 'green') green++;
      }
      const byFreq = Object.entries(freq).sort((a, b) => b[1] - a[1]);
      return {
        label: 'spins seen', count: nums.length,
        hot: byFreq.slice(0, 4).map(([n, c]) => n + '×' + c),
        colors: { red, black, green },
        last: nums.slice(-15).reverse(),
      };
    }
    if (game === 'plinko') {
      const mults = rounds.map((r) => r.multiplier).filter(isNum);
      if (!mults.length) return null;
      return {
        label: 'drop multipliers', count: mults.length,
        avg: r2(mults.reduce((a, b) => a + b, 0) / mults.length),
        best: Math.max(...mults),
        last: mults.slice(-15).reverse(),
      };
    }
    if (game === 'mines') {
      const cashed = rounds.filter((r) => r.result === 'win');
      const cashedMults = cashed.map((r) => r.multiplier).filter(isNum);
      return {
        label: 'games', count: rounds.length,
        cashouts: cashed.length,
        busts: rounds.filter((r) => r.result === 'loss').length,
        bestMultiplier: cashedMults.length ? Math.max(...cashedMults) : null,
      };
    }
    if (game === 'blackjack') {
      return {
        label: 'hands', count: rounds.length,
        record: `${rounds.filter((r) => r.result === 'win').length}W-` +
                `${rounds.filter((r) => r.result === 'loss').length}L-` +
                `${rounds.filter((r) => r.result === 'push').length}P`,
      };
    }
    return null;
  }

  // --- session builders ------------------------------------------------------
  // Each spreads rounds over ~spanMin minutes ending near NOW.

  function baseSession(game, seed, spanMin) {
    return {
      id: game + '-dev' + seed.toString(36),
      game,
      startedAt: NOW - spanMin * MIN,
      lastActivityAt: NOW - 0.4 * MIN,
      rounds: [],
      ticks: [],
      current: null,
    };
  }

  // Rounds carry the denomination the adapters mapped (src/lib/stats.js keeps
  // round.currency); fixtures denominate in USD like the dev payloads do.
  const tagCurrency = (s) => {
    for (const r of s.rounds) r.currency = 'usd';
    return s;
  };

  const BETS = [0.5, 1, 2, 2.5, 5, 10, 15, 25];
  const pickBet = (rand, streakBias) => BETS[Math.floor(rand() * (streakBias ? 5 : BETS.length))];

  // Crash multiplier distribution: heavy under 2x, occasional big spike.
  function crashPoint(rand) {
    const u = rand();
    if (u < 0.05) return r2(1 + rand() * 0.05); // instabust ~1.0x
    const p = 1 / (1 - rand() * 0.99); // pareto-ish
    return r2(Math.min(p, 150));
  }

  function makeCrashSession(seed, nRounds, spanMin) {
    const rand = mulberry32(seed);
    const s = baseSession('crash', seed, spanMin);
    const step = (spanMin - 2) * MIN / Math.max(nRounds * 1.6, 1);
    let ts = s.startedAt + MIN;
    let i = 0;
    // Player sits out ~40% of rounds; every shared round yields a tick.
    const total = Math.ceil(nRounds / 0.6);
    for (let k = 0; k < total; k++) {
      ts += step;
      const cp = crashPoint(rand);
      s.ticks.push({ ts: Math.round(ts), crashPoint: cp });
      if (i < nRounds && rand() < 0.62) {
        const bet = pickBet(rand);
        const target = r2(1.2 + rand() * 3.2);
        const won = cp >= target && rand() < 0.9; // sometimes ride it and bust
        const mult = won ? target : cp;
        const payout = won ? r2(bet * target) : 0;
        s.rounds.push({
          id: 'c' + seed + '-' + k, ts: Math.round(ts),
          bet, payout,
          multiplier: won ? target : r2(cp),
          profit: r2(payout - bet),
          result: won ? 'win' : 'loss',
          detail: { crashPoint: cp, cashedOutAt: won ? target : null },
        });
        i++;
      }
    }
    s.ticks = s.ticks.slice(-100);
    tagCurrency(s);
    s.stats = computeStats(s);
    return s;
  }

  const ROULETTE_REDS = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);
  function makeRouletteSession(seed, nRounds, spanMin) {
    const rand = mulberry32(seed);
    const s = baseSession('roulette', seed, spanMin);
    const step = (spanMin - 2) * MIN / Math.max(nRounds * 1.3, 1);
    let ts = s.startedAt + MIN;
    let placed = 0;
    const totalSpins = Math.ceil(nRounds * 1.3);
    for (let k = 0; k < totalSpins; k++) {
      ts += step;
      const num = Math.floor(rand() * 37);
      const color = num === 0 ? 'green' : ROULETTE_REDS.has(num) ? 'red' : 'black';
      s.ticks.push({ ts: Math.round(ts), number: num, color });
      if (placed < nRounds && rand() < 0.8) {
        const bet = pickBet(rand);
        // Mix of even-money and straight-up bets.
        const straight = rand() < 0.15;
        const won = straight ? rand() < 1 / 37 * 4 : (color === 'red') === (rand() < 0.5) && color !== 'green';
        const mult = won ? (straight ? 36 : 2) : 0;
        const payout = r2(bet * mult);
        s.rounds.push({
          id: 'r' + seed + '-' + k, ts: Math.round(ts),
          bet, payout, multiplier: mult || 0,
          profit: r2(payout - bet),
          result: won ? 'win' : 'loss',
          detail: { number: num, color, betType: straight ? 'straight' : 'color' },
        });
        placed++;
      }
    }
    s.ticks = s.ticks.slice(-100);
    tagCurrency(s);
    s.stats = computeStats(s);
    return s;
  }

  // Fair-ish mines multiplier for `picks` safe reveals on a 25-tile board
  // (product of survival odds inverted, 1% house edge).
  function minesMult(mines, picks) {
    let m = 1;
    for (let i = 0; i < picks; i++) m *= (25 - i) / (25 - mines - i);
    return r2(m * 0.99);
  }

  function makeMinesSession(seed, nRounds, spanMin) {
    const rand = mulberry32(seed);
    const s = baseSession('mines', seed, spanMin);
    const step = (spanMin - 2) * MIN / Math.max(nRounds, 1);
    let ts = s.startedAt + MIN;
    for (let k = 0; k < nRounds; k++) {
      ts += step;
      const bet = pickBet(rand);
      const mines = [3, 5, 5, 10][Math.floor(rand() * 4)];
      // Player aims for `target` picks; each pick survives with true odds, so
      // bust depth and cashout multiplier stay mutually consistent.
      const target = 1 + Math.floor(rand() * 7);
      let picks = 0;
      let bombed = false;
      while (picks < target) {
        const safeLeft = 25 - mines - picks;
        const tilesLeft = 25 - picks;
        if (rand() < safeLeft / tilesLeft) picks++;
        else { bombed = true; break; }
      }
      const won = !bombed;
      const mult = won ? minesMult(mines, picks) : 0;
      const payout = r2(bet * mult);
      s.rounds.push({
        id: 'm' + seed + '-' + k, ts: Math.round(ts),
        bet, payout, multiplier: mult,
        profit: r2(payout - bet),
        result: won ? 'win' : 'loss',
        detail: { mines, revealedCount: picks },
      });
    }
    tagCurrency(s);
    s.stats = computeStats(s);
    return s;
  }

  const RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A'];
  const SUITS = ['hearts', 'diamonds', 'clubs', 'spades'];
  const card = (rand) => ({ rank: RANKS[Math.floor(rand() * 13)], suit: SUITS[Math.floor(rand() * 4)] });

  // Blackjack hand total with soft aces.
  const BJ_VAL = { A: 11, K: 10, Q: 10, J: 10, '10': 10 };
  function bjTotal(cards) {
    let total = 0, aces = 0;
    for (const c of cards) {
      const v = BJ_VAL[c.rank] || parseInt(c.rank, 10);
      if (c.rank === 'A') aces++;
      total += v;
    }
    while (total > 21 && aces) { total -= 10; aces--; }
    return total;
  }

  // Real dealt hands: player hits to a seeded stand threshold (15-18),
  // dealer draws to 17 — so busts, dealer busts, pushes and blackjacks all
  // emerge from actual card play instead of a coin flip.
  function makeBlackjackSession(seed, nRounds, spanMin) {
    const rand = mulberry32(seed);
    const s = baseSession('blackjack', seed, spanMin);
    const step = (spanMin - 2) * MIN / Math.max(nRounds, 1);
    let ts = s.startedAt + MIN;
    for (let k = 0; k < nRounds; k++) {
      ts += step;
      const bet = pickBet(rand);
      const player = [card(rand), card(rand)];
      const dealer = [card(rand), card(rand)];
      let pt = bjTotal(player);
      const blackjack = pt === 21;
      const dealerBJ = bjTotal(dealer) === 21;
      if (!blackjack) {
        const stand = 15 + Math.floor(rand() * 4);
        while (pt < stand) { player.push(card(rand)); pt = bjTotal(player); }
      }
      let dt = bjTotal(dealer);
      if (!blackjack && pt <= 21) {
        while (dt < 17) { dealer.push(card(rand)); dt = bjTotal(dealer); }
      }
      let result;
      if (blackjack) result = dealerBJ ? 'push' : 'win';
      else if (pt > 21) result = 'loss';
      else if (dt > 21) result = 'win';
      else result = pt > dt ? 'win' : pt < dt ? 'loss' : 'push';
      const mult = result === 'win' ? (blackjack ? 2.5 : 2) : result === 'push' ? 1 : 0;
      const payout = r2(bet * mult);
      s.rounds.push({
        id: 'b' + seed + '-' + k, ts: Math.round(ts),
        bet, payout, multiplier: mult,
        profit: r2(payout - bet),
        result,
        detail: {
          player, dealer,
          playerTotal: pt, dealerTotal: dt,
          blackjack: blackjack && result === 'win',
        },
      });
    }
    tagCurrency(s);
    s.stats = computeStats(s);
    return s;
  }

  const PLINKO_SLOTS = [110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3, 0.5, 1, 1.5, 3, 5, 10, 41, 110];
  function makePlinkoSession(seed, nRounds, spanMin) {
    const rand = mulberry32(seed);
    const s = baseSession('plinko', seed, spanMin);
    const step = (spanMin - 2) * MIN / Math.max(nRounds, 1);
    let ts = s.startedAt + MIN;
    for (let k = 0; k < nRounds; k++) {
      ts += step;
      const bet = [0.1, 0.2, 0.5, 1, 1][Math.floor(rand() * 5)];
      // Binomial-ish landing slot (center-heavy).
      let pos = 0;
      for (let d = 0; d < 16; d++) pos += rand() < 0.5 ? 0 : 1;
      const mult = PLINKO_SLOTS[pos];
      const payout = r2(bet * mult);
      s.rounds.push({
        id: 'p' + seed + '-' + k, ts: Math.round(ts),
        bet, payout, multiplier: mult,
        profit: r2(payout - bet),
        result: mult >= 1 ? 'win' : 'loss',
        detail: { slot: pos, risk: 'high' },
      });
    }
    tagCurrency(s);
    s.stats = computeStats(s);
    return s;
  }

  // --- raw-capture log fixture (for the HUD "raw" tab) -----------------------
  function makeRawLog(game) {
    const paths = {
      crash: ['/api/crash/round', '/ws/crash', '/api/wallet/balance'],
      roulette: ['/api/roulette/spin', '/ws/roulette', '/api/bets/place'],
      mines: ['/api/mines/reveal', '/api/mines/cashout', '/api/bets/place'],
      blackjack: ['/api/blackjack/action', '/api/blackjack/deal', '/api/wallet/balance'],
      plinko: ['/api/plinko/drop', '/api/bets/place', '/api/wallet/balance'],
    }[game] || ['/api/unknown'];
    const kinds = ['ws', 'fetch', 'xhr'];
    const keySets = [
      ['id', 'status', 'multiplier', 'payout'],
      ['roundId', 'bet', 'currency', 'state'],
      ['balance', 'currency'],
    ];
    const out = [];
    for (let i = 0; i < 12; i++) {
      out.push({
        ts: NOW - i * 9000,
        kind: kinds[i % 3],
        direction: i % 4 === 0 ? 'out' : 'in',
        url: 'https://spinquest.com' + paths[i % paths.length],
        keys: keySets[i % 3],
      });
    }
    return out;
  }

  // --- archived summaries ----------------------------------------------------
  function archivedSummaries(seed, n) {
    const rand = mulberry32(seed);
    const games = ['crash', 'mines', 'roulette', 'plinko', 'blackjack'];
    const out = [];
    for (let i = 0; i < n; i++) {
      const startedAt = NOW - (i + 2) * 55 * MIN;
      out.push({
        id: games[i % 5] + '-arch' + i,
        game: games[i % 5],
        startedAt,
        endedAt: startedAt + 38 * MIN,
        rounds: 12 + Math.floor(rand() * 90),
        net: r2((rand() - 0.55) * 120),
      });
    }
    return out;
  }

  // --- assemble fixtures -----------------------------------------------------
  const snap = (focusedGame, sessions, archived) => ({
    focusedGame,
    active: sessions,
    archivedSummaries: archived || [],
  });

  const fixtures = {};

  // CRASH — mid-deal: multiplier climbing, player has a live bet.
  {
    const s = makeCrashSession(101, 26, 34);
    s.current = { phase: 'flying', bet: 5, multiplier: 1.87, updatedAt: NOW, detail: { autoCashout: 2.5 } };
    fixtures['crash-mid-deal'] = { state: snap('crash', { crash: s }, archivedSummaries(7, 3)), rawLog: makeRawLog('crash') };
  }
  // CRASH — between deals, long history (68 player rounds over ~40 min).
  {
    const s = makeCrashSession(202, 68, 41);
    s.current = null;
    fixtures['crash-long-history'] = { state: snap('crash', { crash: s }, archivedSummaries(8, 4)), rawLog: makeRawLog('crash') };
  }
  // ROULETTE — between spins with a solid history + hot/cold numbers.
  {
    const s = makeRouletteSession(303, 42, 38);
    fixtures['roulette-history'] = { state: snap('roulette', { roulette: s }, archivedSummaries(9, 3)), rawLog: makeRawLog('roulette') };
  }
  // ROULETTE — mid-spin: bet placed, wheel spinning.
  {
    const s = makeRouletteSession(304, 17, 22);
    s.current = { phase: 'spinning', bet: 10, updatedAt: NOW, detail: { betType: 'red', payoutMult: 2 } };
    fixtures['roulette-mid-spin'] = { state: snap('roulette', { roulette: s }, []), rawLog: makeRawLog('roulette') };
  }
  // MINES — mid-deal: 6 tiles revealed, running multiplier.
  {
    const s = makeMinesSession(405, 23, 31);
    // nextMultiplier is the game's own paytable value for pick 7 (per-pick
    // house edge, so slightly under the fair 2.90 the HUD would derive).
    s.current = { phase: 'picking', bet: 2.5, multiplier: 2.14, updatedAt: NOW, detail: { mines: 5, revealedCount: 6, tilesTotal: 25, nextMultiplier: 2.87 } };
    fixtures['mines-mid-deal'] = { state: snap('mines', { mines: s }, archivedSummaries(10, 2)), rawLog: makeRawLog('mines') };
  }
  // MINES — between games.
  {
    const s = makeMinesSession(406, 31, 36);
    fixtures['mines-history'] = { state: snap('mines', { mines: s }, []), rawLog: makeRawLog('mines') };
  }
  // BLACKJACK — mid-hand: player on 17 vs dealer ace.
  {
    const s = makeBlackjackSession(507, 29, 39);
    s.current = {
      phase: 'player turn', bet: 15, updatedAt: NOW,
      detail: {
        player: [{ rank: 'K', suit: 'hearts' }, { rank: '7', suit: 'clubs' }],
        playerTotal: 17,
        dealer: [{ rank: 'A', suit: 'spades' }, '?'],
        dealerTotal: 11,
      },
    };
    fixtures['blackjack-mid-hand'] = { state: snap('blackjack', { blackjack: s }, archivedSummaries(11, 3)), rawLog: makeRawLog('blackjack') };
  }
  // BLACKJACK — between hands.
  {
    const s = makeBlackjackSession(515, 41, 40);
    fixtures['blackjack-history'] = { state: snap('blackjack', { blackjack: s }, []), rawLog: makeRawLog('blackjack') };
  }
  // PLINKO — mid-drop.
  {
    const s = makePlinkoSession(609, 34, 28);
    s.current = { phase: 'dropping', bet: 1, updatedAt: NOW, detail: { risk: 'high', rows: 16, maxMult: 110 } };
    fixtures['plinko-mid-drop'] = { state: snap('plinko', { plinko: s }, []), rawLog: makeRawLog('plinko') };
  }
  // PLINKO — long drop history (61 rounds).
  {
    const s = makePlinkoSession(610, 61, 40);
    fixtures['plinko-history'] = { state: snap('plinko', { plinko: s }, archivedSummaries(12, 2)), rawLog: makeRawLog('plinko') };
  }
  // Empty session: on a crash page, session open but nothing recorded yet.
  {
    const s = baseSession('crash', 700, 1);
    s.stats = computeStats(s);
    fixtures['empty-session'] = { state: snap('crash', { crash: s }, []), rawLog: [] };
  }
  // On a game page but no data yet (no session at all).
  fixtures['game-no-session'] = { state: snap('mines', {}, []), rawLog: [] };
  // Not on a recognized game page.
  fixtures['no-game'] = { state: snap(null, {}, archivedSummaries(13, 2)), rawLog: [] };

  // --- popup fixtures --------------------------------------------------------
  // The popup renders every active session + archived summaries.
  {
    const crash = makeCrashSession(801, 45, 40);
    const mines = makeMinesSession(802, 18, 25);
    const bj = makeBlackjackSession(803, 33, 37);
    fixtures['popup-busy'] = {
      state: snap('crash', { crash, mines, blackjack: bj }, archivedSummaries(14, 6)),
      rawLog: [],
    };
  }
  {
    const roulette = makeRouletteSession(804, 26, 33);
    fixtures['popup-single'] = { state: snap('roulette', { roulette }, archivedSummaries(15, 2)), rawLog: [] };
  }
  fixtures['popup-empty'] = { state: snap(null, {}, []), rawLog: [] };

  globalThis.__SQX_FIXTURES = fixtures;
})();
