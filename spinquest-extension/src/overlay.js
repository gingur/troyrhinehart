// In-page HUD. Renders the focused game's session: current deal, stats bar,
// round history, game-specific extras, and a raw-capture inspector for
// discovering payload shapes the adapters don't map yet.
'use strict';

(() => {
  let root = null;
  let latest = null;
  let collapsed = false;
  let tab = 'session'; // 'session' | 'raw'

  const h = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  };

  // Static inline SVG icons (stroke inherits currentColor via CSS).
  const ICONS = {
    grip:
      '<svg viewBox="0 0 8 14" aria-hidden="true">' +
      '<circle cx="2" cy="2.5" r="1.15"/><circle cx="6" cy="2.5" r="1.15"/>' +
      '<circle cx="2" cy="7" r="1.15"/><circle cx="6" cy="7" r="1.15"/>' +
      '<circle cx="2" cy="11.5" r="1.15"/><circle cx="6" cy="11.5" r="1.15"/></svg>',
    code:
      '<svg viewBox="0 0 16 16" aria-hidden="true">' +
      '<path d="M5.6 4.5 2.4 8l3.2 3.5"/><path d="M10.4 4.5 13.6 8l-3.2 3.5"/></svg>',
    chevDown: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.2 6.2 8 10l3.8-3.8"/></svg>',
    chevRight: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.2 4.2 10 8l-3.8 3.8"/></svg>',
    reset:
      '<svg viewBox="0 0 16 16" aria-hidden="true">' +
      '<path d="M3.4 6.2a5 5 0 1 1-.4 3"/><path d="M3.4 2.8v3.4h3.4"/></svg>',
    chart:
      '<svg viewBox="0 0 20 20" aria-hidden="true">' +
      '<path d="M3.5 3.5v13h13"/><path d="M6.5 12.5 9.5 9l2.5 2 4.5-5.5"/></svg>',
  };

  const icon = (name) => {
    const s = h('span', 'sqx-icon');
    s.innerHTML = ICONS[name];
    return s;
  };

  const iconBtn = (name, title, onClick, active) => {
    const b = h('button', 'sqx-ibtn' + (active ? ' sqx-on' : ''));
    b.type = 'button';
    b.title = title;
    b.setAttribute('aria-label', title);
    b.innerHTML = ICONS[name];
    b.onclick = onClick;
    return b;
  };

  const num = (text, cls) => h('span', 'sqx-num' + (cls ? ' ' + cls : ''), text);

  const fmtMoney = (n) => {
    if (typeof n !== 'number') return '—';
    const sign = n > 0 ? '+' : '';
    if (Math.abs(n) >= 10000) return sign + (n / 1000).toFixed(1) + 'k';
    return sign + n.toFixed(2);
  };

  const fmtAmount = (n) => {
    if (typeof n !== 'number') return '—';
    if (n >= 10000) return (n / 1000).toFixed(1) + 'k';
    return n.toFixed(2);
  };

  const fmtTime = (ts) => new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const fmtClock = (ts) =>
    new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  // Compact "time ago": 45s / 12m / 1h05.
  const fmtAgo = (ms) => {
    if (typeof ms !== 'number' || !(ms >= 0)) ms = 0;
    const s = Math.floor(ms / 1000);
    if (s < 60) return s + 's';
    const m = Math.floor(s / 60);
    if (m < 60) return m + 'm';
    return Math.floor(m / 60) + 'h' + String(m % 60).padStart(2, '0');
  };

  // Multiplier with precision that fits a narrow column: 110× / 12.4× / 2.01×.
  const fmtMult = (m) => {
    if (typeof m !== 'number') return '';
    if (m >= 100) return Math.round(m) + '×';
    if (m >= 10) return m.toFixed(1) + '×';
    return m.toFixed(2) + '×';
  };

  const fmtDur = (ms) => {
    if (typeof ms !== 'number' || ms < 0) return null;
    const m = Math.floor(ms / 60000);
    if (m < 1) return '<1m';
    if (m < 60) return m + 'm';
    return Math.floor(m / 60) + 'h' + String(m % 60).padStart(2, '0') + 'm';
  };

  const posNegCls = (n) => (n > 0 ? 'sqx-pos' : n < 0 ? 'sqx-neg' : 'sqx-dim');

  // Compact signed value for the graph's min/max scale labels: +34 / -80 /
  // +4.5 / -0.42 / +12.3k — small enough for a corner, precise enough to scale.
  const fmtAxis = (v) => {
    const sign = v > 0 ? '+' : v < 0 ? '-' : '';
    const a = Math.abs(v);
    if (a >= 10000) return sign + (a / 1000).toFixed(1) + 'k';
    if (a >= 10) return sign + Math.round(a);
    if (a >= 1) return sign + a.toFixed(1);
    return sign + a.toFixed(2);
  };

  // Session display currency, from the most recent round that carried one.
  const sessionCurrency = (session) => {
    const rounds = session.rounds || [];
    for (let i = rounds.length - 1; i >= 0; i--) {
      const c = rounds[i].currency;
      if (typeof c === 'string' && c) return c.toUpperCase().slice(0, 5);
    }
    return null;
  };

  const isNum = Number.isFinite;

  const pctOf = (n, d) => (d ? Math.round((n / d) * 100) + '%' : '—');

  // Duration/pace fallbacks for snapshots whose stats predate durationMs.
  const sessionDurationMs = (session) => {
    const s = session.stats || {};
    if (typeof s.durationMs === 'number') return s.durationMs;
    if (typeof session.startedAt === 'number' && typeof session.lastActivityAt === 'number') {
      return Math.max(0, session.lastActivityAt - session.startedAt);
    }
    return null;
  };

  function ensureRoot() {
    if (root && document.body.contains(root)) return root;
    root = h('div', 'sqx-hud');
    root.id = 'sqx-hud';

    // Draggable via the header.
    let drag = null;
    root.addEventListener('mousedown', (e) => {
      if (!e.target.closest('.sqx-head')) return;
      if (e.target.closest('button')) return;
      drag = { x: e.clientX - root.offsetLeft, y: e.clientY - root.offsetTop };
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return;
      root.style.left = Math.max(0, e.clientX - drag.x) + 'px';
      root.style.top = Math.max(0, e.clientY - drag.y) + 'px';
      root.style.right = 'auto';
    });
    window.addEventListener('mouseup', () => (drag = null));

    document.body.appendChild(root);
    return root;
  }

  function render() {
    if (!document.body) return;
    const el = ensureRoot();
    el.textContent = '';
    el.classList.toggle('sqx-collapsed', collapsed);

    const game = latest && latest.focusedGame;
    const session = game && latest.active ? latest.active[game] : null;

    // Header: grip · title · game badge · (net when collapsed) · icon buttons.
    const head = h('div', 'sqx-head');
    const grip = h('span', 'sqx-grip');
    grip.innerHTML = ICONS.grip;
    head.appendChild(grip);
    head.appendChild(h('span', 'sqx-title', 'SpinQuest'));
    head.appendChild(h('span', 'sqx-badge' + (game ? '' : ' sqx-badge-off'), game ? game.toUpperCase() : 'NO GAME'));
    if (collapsed && session && session.stats && session.stats.rounds) {
      const net = session.stats.net;
      head.appendChild(
        num(fmtMoney(net), 'sqx-head-net ' + (net > 0 ? 'sqx-pos' : net < 0 ? 'sqx-neg' : 'sqx-dim'))
      );
    }
    const btns = h('span', 'sqx-btns');
    btns.appendChild(
      iconBtn('code', tab === 'raw' ? 'Back to session view' : 'Raw capture inspector', () => {
        tab = tab === 'raw' ? 'session' : 'raw';
        render();
        if (tab === 'raw') loadRawLog();
      }, tab === 'raw')
    );
    btns.appendChild(
      iconBtn(collapsed ? 'chevRight' : 'chevDown', collapsed ? 'Expand' : 'Collapse', () => {
        collapsed = !collapsed;
        render();
      })
    );
    head.appendChild(btns);
    el.appendChild(head);

    if (collapsed) return;

    const body = h('div', 'sqx-body');
    el.appendChild(body);

    if (tab === 'raw') {
      renderRaw(body);
      return;
    }

    if (!session) {
      body.appendChild(
        emptyState(
          game ? 'Waiting for game data' : 'No game detected',
          game
            ? 'Place a bet — rounds appear here automatically.'
            : 'Open a Plinko, Mines, Crash, Blackjack, or Roulette page.'
        )
      );
      return;
    }

    renderCurrent(body, session);
    renderGraph(body, session);
    renderStats(body, session);
    renderExtras(body, session);
    renderHistory(body, session);

    if (!session.rounds.length && !session.current) {
      body.appendChild(emptyState('Session open', 'No rounds recorded yet — play a round.'));
    }

    const foot = h('div', 'sqx-foot');
    const newBtn = h('button', 'sqx-reset');
    newBtn.type = 'button';
    newBtn.title = 'Archive this session and start fresh';
    newBtn.innerHTML = ICONS.reset + '<span>new session</span>';
    newBtn.onclick = () => chrome.runtime.sendMessage({ type: 'SQX_NEW_SESSION', game }).catch(() => {});
    const metaBits = ['since ' + fmtTime(session.startedAt)];
    const dur = fmtDur(sessionDurationMs(session));
    if (dur) metaBits.push(dur);
    const stats = session.stats || {};
    const pace = typeof stats.betsPerMinute === 'number' ? stats.betsPerMinute : null;
    if (pace != null && pace > 0) metaBits.push(pace + '/min');
    foot.append(h('span', 'sqx-foot-meta', metaBits.join(' · ')), newBtn);
    body.appendChild(foot);
  }

  function emptyState(title, sub) {
    const box = h('div', 'sqx-empty');
    const glyph = h('div', 'sqx-empty-i');
    glyph.innerHTML = ICONS.chart;
    box.appendChild(glyph);
    box.appendChild(h('div', 'sqx-empty-t', title));
    if (sub) box.appendChild(h('div', 'sqx-empty-s', sub));
    return box;
  }

  // ---- current deal ---------------------------------------------------------
  // One card per game, tuned so the decision-relevant number dominates:
  // crash/mines lead with the live multiplier + cash-out-now value, blackjack
  // renders card tiles and a totals duel, roulette/plinko lead with the bet
  // at risk + potential payout. Everything degrades gracefully to whatever
  // fields the adapter managed to map.

  function renderCurrent(body, session) {
    const cur = session.current;
    if (!cur) return;
    const d = cur.detail || {};
    const game = session.game;
    const box = h('div', 'sqx-current');

    const top = h('div', 'sqx-current-top');
    top.appendChild(h('span', 'sqx-live-dot'));
    top.appendChild(h('span', 'sqx-phase', cur.phase || 'deal'));
    // Roulette/plinko show the bet as the hero number — no duplicate up top.
    const betIsHero = (game === 'roulette' || game === 'plinko') && typeof cur.bet === 'number';
    if (typeof cur.bet === 'number' && !betIsHero) {
      const bet = h('span', 'sqx-current-bet');
      bet.appendChild(document.createTextNode('bet '));
      bet.appendChild(num(cur.bet.toFixed(2)));
      top.appendChild(bet);
    }
    box.appendChild(top);

    if (game === 'blackjack' && (d.player || d.dealer)) {
      renderBlackjackDeal(box, d);
    } else if (game === 'mines') {
      renderMinesDeal(box, cur, d);
    } else if (game === 'crash') {
      renderCrashDeal(box, cur, d);
    } else if (game === 'roulette') {
      renderRouletteDeal(box, cur, d, session);
    } else if (game === 'plinko') {
      renderPlinkoDeal(box, cur, d, session);
    } else if (typeof cur.multiplier === 'number') {
      box.appendChild(heroRow(null, cur.multiplier.toFixed(2), '×', 'sqx-hero-live', null));
    }
    body.appendChild(box);
  }

  // Big-number row: [label?] value+unit on the left, optional right block.
  function heroRow(label, value, unit, cls, right) {
    const row = h('div', 'sqx-hero');
    const main = h('div', 'sqx-hero-main');
    if (label) main.appendChild(h('div', 'sqx-hero-l', label));
    const v = h('div', 'sqx-hero-num' + (cls ? ' ' + cls : ''));
    v.appendChild(h('span', null, value));
    if (unit) v.appendChild(h('span', 'sqx-hero-unit', unit));
    main.appendChild(v);
    row.appendChild(main);
    if (right) row.appendChild(right);
    return row;
  }

  // Right-aligned "what you'd get" block next to the hero number.
  function cashBlock(label, mainText, mainCls, subText, subCls) {
    const b = h('div', 'sqx-cash');
    b.appendChild(h('div', 'sqx-cash-l', label));
    const v = h('div', 'sqx-cash-v');
    v.appendChild(h('span', mainCls || null, mainText));
    if (subText) v.appendChild(h('span', 'sqx-cash-sub' + (subCls ? ' ' + subCls : ''), subText));
    b.appendChild(v);
    return b;
  }

  // Row of tiny label/value stats under the hero. items: [label, value|node, cls?]
  function miniRow(items) {
    const row = h('div', 'sqx-mini');
    for (const [label, value, cls] of items) {
      const c = h('div', 'sqx-mini-c');
      c.appendChild(h('div', 'sqx-mini-l', label));
      const v = h('div', 'sqx-mini-v' + (cls ? ' ' + cls : ''));
      if (value instanceof Node) v.appendChild(value);
      else v.textContent = value;
      c.appendChild(v);
      row.appendChild(c);
    }
    return row;
  }

  function cashOutRight(cur) {
    if (typeof cur.multiplier !== 'number' || typeof cur.bet !== 'number') return null;
    const val = cur.bet * cur.multiplier;
    const prof = Math.round((val - cur.bet) * 100) / 100;
    return cashBlock('cash out now', fmtAmount(val), null, fmtMoney(prof), posNegCls(prof));
  }

  function renderCrashDeal(box, cur, d) {
    if (typeof cur.multiplier === 'number') {
      box.appendChild(heroRow(null, cur.multiplier.toFixed(2), '×', 'sqx-hero-live', cashOutRight(cur)));
    }
    const minis = [];
    if (typeof d.autoCashout === 'number') {
      minis.push(['auto cash', d.autoCashout.toFixed(2) + '×']);
      if (typeof cur.bet === 'number') {
        const w = Math.round(cur.bet * (d.autoCashout - 1) * 100) / 100;
        minis.push(['win @ auto', fmtMoney(w), posNegCls(w)]);
      }
    }
    if (d.crashPoint != null) minis.push(['crashed at', d.crashPoint + '×', 'sqx-neg']);
    if (minis.length) box.appendChild(miniRow(minis));
  }

  function renderMinesDeal(box, cur, d) {
    if (typeof cur.multiplier === 'number') {
      box.appendChild(heroRow(null, cur.multiplier.toFixed(2), '×', 'sqx-hero-live', cashOutRight(cur)));
    }
    const total = typeof d.tilesTotal === 'number' ? d.tilesTotal : 25;
    const mines = typeof d.mines === 'number' ? d.mines : null;
    const picked = typeof d.revealedCount === 'number' ? d.revealedCount : null;
    const minis = [];
    if (mines != null && picked != null && picked + mines <= total) {
      const left = total - picked; // unrevealed tiles
      const safeLeft = left - mines; // safe tiles among them
      if (safeLeft > 0 && typeof cur.multiplier === 'number') {
        minis.push(['next tile', ((cur.multiplier * left) / safeLeft).toFixed(2) + '×']);
      }
      if (left > 0) minis.push(['safe odds', Math.round((safeLeft / left) * 100) + '%']);
      minis.push(['picked', picked + '/' + (total - mines)]);
      minis.push(['mines', String(mines)]);
    } else {
      if (picked != null) minis.push(['revealed', String(picked)]);
      if (mines != null) minis.push(['mines', String(mines)]);
    }
    if (minis.length) box.appendChild(miniRow(minis));
  }

  function renderRouletteDeal(box, cur, d, session) {
    const pays = typeof d.payoutMult === 'number' ? d.payoutMult : null;
    if (typeof cur.bet === 'number') {
      const right = pays != null
        ? cashBlock('to win', fmtMoney(Math.round(cur.bet * (pays - 1) * 100) / 100), 'sqx-pos', null, null)
        : null;
      box.appendChild(heroRow('bet at risk', cur.bet.toFixed(2), null, null, right));
    }
    const minis = [];
    if (d.betType) minis.push(['bet on', wheelValue(d.betType, null)]);
    if (pays != null) minis.push(['pays', pays + '×']);
    const ticks = Array.isArray(session.ticks) ? session.ticks : [];
    const lastTick = ticks.length ? ticks[ticks.length - 1] : null;
    if (lastTick && typeof lastTick.number === 'number') {
      minis.push(['last spin', wheelValue(lastTick.color, lastTick.number)]);
    }
    if (d.number != null) minis.push(['landed', wheelValue(d.color, d.number)]);
    if (minis.length) box.appendChild(miniRow(minis));
  }

  // "red 14" / "RED" with a little wheel-color swatch.
  function wheelValue(color, number) {
    const wrap = h('span', 'sqx-wheel');
    const c = String(color || '').toLowerCase();
    if (c === 'red' || c === 'black' || c === 'green') {
      wrap.appendChild(h('span', 'sqx-wheel-dot sqx-wheel-' + c));
    }
    wrap.appendChild(h('span', null, number != null ? String(number) : String(color || '?').toUpperCase()));
    return wrap;
  }

  function renderPlinkoDeal(box, cur, d, session) {
    const maxMult = typeof d.maxMult === 'number' ? d.maxMult : null;
    if (typeof cur.bet === 'number') {
      const right = maxMult != null
        ? cashBlock('max win', fmtAmount(cur.bet * maxMult), null, maxMult + '×', 'sqx-dim')
        : null;
      box.appendChild(heroRow('bet at risk', cur.bet.toFixed(2), null, null, right));
    }
    const minis = [];
    if (d.risk) minis.push(['risk', String(d.risk), String(d.risk).toLowerCase() === 'high' ? 'sqx-live' : '']);
    if (typeof d.rows === 'number') minis.push(['rows', String(d.rows)]);
    const rounds = Array.isArray(session.rounds) ? session.rounds : [];
    const last = rounds.length ? rounds[rounds.length - 1] : null;
    if (last && typeof last.multiplier === 'number') {
      minis.push(['last drop', last.multiplier + '×', last.multiplier >= 1 ? 'sqx-pos' : 'sqx-neg']);
    }
    if (minis.length) box.appendChild(miniRow(minis));
  }

  // -- blackjack: card tiles + totals duel ------------------------------------

  const SUIT_GLYPH = { hearts: '♥', diamonds: '♦', clubs: '♣', spades: '♠' };
  const SUIT_LETTER = { h: 'hearts', d: 'diamonds', c: 'clubs', s: 'spades', '♥': 'hearts', '♦': 'diamonds', '♣': 'clubs', '♠': 'spades' };

  // -> { rank, suit } or null for a hidden/unknown card.
  function parseCard(c) {
    if (c == null) return null;
    if (typeof c === 'object') {
      const rank = c.rank ?? c.value ?? c.face;
      if (rank == null) return null;
      return { rank: String(rank), suit: String(c.suit || '').toLowerCase() };
    }
    const s = String(c).trim();
    if (!s || s === '?') return null;
    const m = s.match(/^(10|[2-9]|[atjqk])\s*([hdcs♥♦♣♠]?)$/i);
    if (m) {
      let rank = m[1].toUpperCase();
      if (rank === 'T') rank = '10';
      return { rank, suit: SUIT_LETTER[m[2].toLowerCase()] || '' };
    }
    return { rank: s, suit: '' };
  }

  function cardTile(c) {
    const p = parseCard(c);
    if (!p) {
      const t = h('span', 'sqx-card sqx-card-down');
      t.appendChild(h('span', 'sqx-card-rank', '?'));
      return t;
    }
    const red = p.suit === 'hearts' || p.suit === 'diamonds';
    const t = h('span', 'sqx-card' + (red ? ' sqx-card-red' : ''));
    t.appendChild(h('span', 'sqx-card-rank', p.rank));
    const g = SUIT_GLYPH[p.suit];
    if (g) t.appendChild(h('span', 'sqx-card-suit', g));
    return t;
  }

  function cardsRow(arr, alignRight) {
    const row = h('div', 'sqx-cards' + (alignRight ? ' sqx-cards-r' : ''));
    if (Array.isArray(arr) && arr.length) for (const c of arr) row.appendChild(cardTile(c));
    else row.appendChild(cardTile(null));
    return row;
  }

  function totalEl(total, alignRight) {
    const n = typeof total === 'number' ? total : null;
    const cls = n == null ? ' sqx-dim' : n > 21 ? ' sqx-neg' : n === 21 ? ' sqx-pos' : '';
    const el = h('div', 'sqx-duel-total' + cls + (alignRight ? ' sqx-duel-tr' : ''));
    el.appendChild(h('span', null, n == null ? (total != null ? String(total) : '—') : String(n)));
    if (n != null && n > 21) el.appendChild(h('span', 'sqx-duel-flag', 'bust'));
    if (n === 21) el.appendChild(h('span', 'sqx-duel-flag', '21!'));
    return el;
  }

  function renderBlackjackDeal(box, d) {
    const duel = h('div', 'sqx-duel');

    const you = h('div', 'sqx-duel-side');
    you.appendChild(h('div', 'sqx-duel-l', 'you'));
    you.appendChild(cardsRow(d.player, false));
    you.appendChild(totalEl(d.playerTotal, false));
    duel.appendChild(you);

    duel.appendChild(h('div', 'sqx-duel-vs', 'vs'));

    const dealerCards = Array.isArray(d.dealer) ? d.dealer : [];
    const hidden = dealerCards.some((c) => parseCard(c) == null);
    const dealer = h('div', 'sqx-duel-side sqx-duel-right');
    dealer.appendChild(h('div', 'sqx-duel-l', hidden ? 'dealer shows' : 'dealer'));
    dealer.appendChild(cardsRow(d.dealer, true));
    if (hidden) {
      // Up-card rank is the number a player actually reasons against.
      const up = dealerCards.map(parseCard).find(Boolean);
      const el = h('div', 'sqx-duel-total sqx-duel-tr', up ? up.rank : d.dealerTotal != null ? String(d.dealerTotal) : '—');
      dealer.appendChild(el);
    } else {
      dealer.appendChild(totalEl(d.dealerTotal, true));
    }
    duel.appendChild(dealer);
    box.appendChild(duel);
  }

  // Cumulative-profit values for the sparkline: prefer the background-computed
  // stats.series, fall back to summing session.rounds. Always starts at 0.
  function profitSeries(session) {
    const s = session.stats;
    const vals = [0];
    if (s && Array.isArray(s.series) && s.series.length) {
      for (const p of s.series) if (typeof p.net === 'number') vals.push(p.net);
      return vals;
    }
    let cum = 0;
    for (const r of session.rounds) {
      if (typeof r.profit === 'number') {
        cum = Math.round((cum + r.profit) * 100) / 100;
        vals.push(cum);
      }
    }
    return vals;
  }

  // Stake-style session profit chart: one point per bet, value-colored stroke
  // + faint area fill (green at/above zero, red below), a dashed zero baseline
  // with a tiny "0" label, auto-scaled max/min labels in the right corners,
  // and a dot on the latest point. No other furniture.
  function renderGraph(body, session) {
    const s = session.stats;
    if (!s || !s.rounds) return;
    const vals = profitSeries(session);

    const box = h('div', 'sqx-graph');
    const top = h('div', 'sqx-graph-top');
    top.appendChild(h('span', 'sqx-graph-l', 'Profit'));
    const cur = sessionCurrency(session);
    if (cur) top.appendChild(h('span', 'sqx-cur', cur));
    top.appendChild(h('span', 'sqx-count', s.rounds + (s.rounds === 1 ? ' bet' : ' bets')));
    top.appendChild(num(fmtMoney(s.net), 'sqx-graph-net ' + posNegCls(s.net)));
    box.appendChild(top);

    if (vals.length >= 2) {
      // W matches the card's rendered inner width so SVG text isn't scaled;
      // PT/PB reserve corner bands for the max/min scale labels.
      const W = 260, H = 72, PT = 12, PB = 12;
      let min = 0, max = 0;
      for (const v of vals) {
        if (v < min) min = v;
        if (v > max) max = v;
      }
      const realMin = min, realMax = max;
      if (max - min < 1e-9) { max = 0.5; min = -0.5; }
      const ih = H - PT - PB;
      const y = (v) => PT + ((max - v) / (max - min)) * ih;
      const x = (i) => (i / (vals.length - 1)) * W;
      const y0 = y(0);
      let line = '';
      for (let i = 0; i < vals.length; i++) {
        line += (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(vals[i]).toFixed(1);
      }
      const area = line + 'L' + W + ' ' + y0.toFixed(1) + 'L0 ' + y0.toFixed(1) + 'Z';
      const lx = x(vals.length - 1).toFixed(1);
      const ly = y(vals[vals.length - 1]).toFixed(1);
      const lastCol = vals[vals.length - 1] < 0 ? 'var(--sqx-neg)' : 'var(--sqx-pos)';
      const zeroLabelY = y0 > 13 ? y0 - 3.5 : y0 + 9.5;
      // Auto-scale labels: max at top-right, min at bottom-right, sitting in
      // the reserved bands so they never collide with the line. Skipped when
      // they'd merely restate the zero baseline.
      const axisText = (yPos, v) =>
        '<text x="' + (W - 2) + '" y="' + yPos + '" text-anchor="end"' +
        ' style="fill:var(--sqx-faint);font-family:var(--sqx-mono);font-size:9px;font-variant-numeric:tabular-nums">' +
        fmtAxis(v) + '</text>';
      let axisLabels = '';
      if (realMax > 0) axisLabels += axisText(9, realMax);
      if (realMin < 0) axisLabels += axisText(H - 3, realMin);
      const svg =
        '<svg class="sqx-spark" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<defs>' +
        '<clipPath id="sqx-clip-up"><rect x="-2" y="-2" width="' + (W + 4) + '" height="' + (y0 + 2).toFixed(1) + '"/></clipPath>' +
        '<clipPath id="sqx-clip-dn"><rect x="-2" y="' + y0.toFixed(1) + '" width="' + (W + 4) + '" height="' + (H - y0 + 2).toFixed(1) + '"/></clipPath>' +
        '</defs>' +
        '<line x1="0" y1="' + y0.toFixed(1) + '" x2="' + W + '" y2="' + y0.toFixed(1) + '"' +
        ' style="stroke:var(--sqx-hair);stroke-width:1;stroke-dasharray:3 3" vector-effect="non-scaling-stroke"/>' +
        '<path d="' + area + '" clip-path="url(#sqx-clip-up)" style="fill:var(--sqx-pos);fill-opacity:0.12"/>' +
        '<path d="' + area + '" clip-path="url(#sqx-clip-dn)" style="fill:var(--sqx-neg);fill-opacity:0.12"/>' +
        '<path d="' + line + '" clip-path="url(#sqx-clip-up)"' +
        ' style="fill:none;stroke:var(--sqx-pos);stroke-width:1.8;stroke-linejoin:round;stroke-linecap:round" vector-effect="non-scaling-stroke"/>' +
        '<path d="' + line + '" clip-path="url(#sqx-clip-dn)"' +
        ' style="fill:none;stroke:var(--sqx-neg);stroke-width:1.8;stroke-linejoin:round;stroke-linecap:round" vector-effect="non-scaling-stroke"/>' +
        '<circle cx="' + lx + '" cy="' + ly + '" r="2.3" style="fill:' + lastCol + '"/>' +
        '<text x="3" y="' + zeroLabelY.toFixed(1) + '"' +
        ' style="fill:var(--sqx-faint);font-family:var(--sqx-mono);font-size:8px">0</text>' +
        axisLabels +
        '</svg>';
      const wrap = h('div', 'sqx-spark-wrap');
      wrap.innerHTML = svg;
      box.appendChild(wrap);
    }
    body.appendChild(box);
  }

  function renderStats(body, session) {
    const s = session.stats;
    if (!s || !s.rounds) return;
    const grid = h('div', 'sqx-stats');
    const cell = (label, value, cls, small) => {
      const c = h('div', 'sqx-stat');
      c.appendChild(h('div', 'sqx-stat-l', label));
      const v = h('div', 'sqx-stat-v' + (cls ? ' ' + cls : '') + (small ? ' sqx-sm' : ''));
      if (typeof value === 'string') v.textContent = value;
      else v.append(...value); // array of nodes
      c.appendChild(v);
      return c;
    };
    const pair = (a, aCls, b, bCls) => [
      h('span', aCls, a),
      h('span', 'sqx-dim', '/'),
      h('span', bCls, b),
    ];

    // Derived stats with fallbacks so older snapshots (no series/duration/
    // best-worst streaks) still fill every cell.
    const cur = sessionCurrency(session);
    const durationMs = sessionDurationMs(session);
    const avgBet = s.rounds ? s.wagered / s.rounds : null;
    const rtp = s.wagered > 0 && typeof s.returned === 'number'
      ? Math.round((s.returned / s.wagered) * 1000) / 10 : null;
    const netHr = durationMs != null && durationMs >= 60000
      ? Math.round((s.net * 3600000) / durationMs * 100) / 100 : null;
    let bestRun = s.bestWinStreak;
    let worstRun = s.worstLossStreak;
    if (typeof bestRun !== 'number' || typeof worstRun !== 'number') {
      bestRun = 0; worstRun = 0;
      let run = 0;
      for (const r of session.rounds) {
        if (r.result === 'win') run = run > 0 ? run + 1 : 1;
        else if (r.result === 'loss') run = run < 0 ? run - 1 : -1;
        else if (r.result !== 'push') run = 0;
        if (run > bestRun) bestRun = run;
        if (run < worstRun) worstRun = run;
      }
    }

    grid.append(
      cell('w–l', [
        h('span', s.wins ? 'sqx-pos' : 'sqx-dim', String(s.wins)),
        h('span', 'sqx-dim', '–'),
        h('span', s.losses ? 'sqx-neg' : 'sqx-dim', String(s.losses)),
      ]),
      cell('win rate', s.winRate == null ? '—' : s.winRate + '%'),
      cell('streak', s.streak === 0 ? '—' : (s.streak > 0 ? 'W' : 'L') + Math.abs(s.streak),
        posNegCls(s.streak)),
      cell('wagered', cur
        ? [h('span', null, fmtAmount(s.wagered)), h('span', 'sqx-cur-sfx', cur)]
        : fmtAmount(s.wagered)),
      cell('avg bet', avgBet == null ? '—' : fmtAmount(avgBet)),
      // Session payout ratio (returned / wagered) — "payout", not "rtp", so it
      // can't be mistaken for the game's theoretical RTP.
      cell('payout', rtp == null ? '—' : rtp + '%', rtp == null ? '' : rtp >= 100 ? 'sqx-pos' : ''),
      cell('best / worst', pair(
        fmtMoney(s.biggestWin), s.biggestWin > 0 ? 'sqx-pos' : '',
        fmtMoney(s.biggestLoss), s.biggestLoss < 0 ? 'sqx-neg' : ''
      ), '', true),
      cell('runs', pair(
        'W' + bestRun, bestRun > 0 ? 'sqx-pos' : 'sqx-dim',
        'L' + Math.abs(worstRun), worstRun < 0 ? 'sqx-neg' : 'sqx-dim'
      ), '', true),
      cell('net / hr', netHr == null ? '—' : fmtMoney(netHr), posNegCls(netHr == null ? 0 : netHr), true)
    );
    body.appendChild(grid);
  }

  // ---- game extras ----------------------------------------------------------
  // Purpose-built per-game stat sections, computed straight off the snapshot's
  // round/tick arrays (richer than the background's stats.extra summary).
  // Grammar borrowed from PT4: terse labels, bare mono values, a dash for no
  // data, and the raw made/opportunity fraction beside every rate so the
  // sample size is never hidden. Color stays rationed: green/red = outcome,
  // amber = big hit, wheel chips use the wheel's own colors.

  function xSection(title, count) {
    const wrap = h('div', 'sqx-extra');
    const lab = h('div', 'sqx-label');
    lab.appendChild(h('span', null, title));
    if (count != null) lab.appendChild(h('span', 'sqx-count', String(count)));
    wrap.appendChild(lab);
    const card = h('div', 'sqx-x-card');
    wrap.appendChild(card);
    return { wrap, card };
  }

  // Row of stat cells: [label, value|node, cls?, subline?]. The subline is the
  // PT4-style sample fraction ("17/31") rendered small under the value.
  function xStats(cells) {
    const row = h('div', 'sqx-xstats');
    for (const [label, value, cls, sub] of cells) {
      const c = h('div', 'sqx-xstat');
      c.appendChild(h('div', 'sqx-mini-l', label));
      const v = h('div', 'sqx-mini-v' + (cls ? ' ' + cls : ''));
      if (value instanceof Node) v.appendChild(value);
      else v.textContent = value;
      c.appendChild(v);
      if (sub != null) c.appendChild(h('div', 'sqx-xsub', sub));
      row.appendChild(c);
    }
    return row;
  }

  const xCap = (text) => h('div', 'sqx-xcap', text);

  // Fixed-column chip grid so values ring up in even columns.
  function chipStrip(cols, chips) {
    const grid = h('div', 'sqx-xchips');
    grid.style.setProperty('--sqx-cols', String(cols));
    for (const c of chips) {
      const el = h('span', 'sqx-xchip' + (c.cls ? ' ' + c.cls : ''), c.text);
      if (c.title) el.title = c.title;
      grid.appendChild(el);
    }
    return grid;
  }

  // Segmented distribution bar: segs = [[cls, count], ...], zero segs skipped.
  function segBar(segs) {
    const bar = h('div', 'sqx-rbar');
    for (const [cls, count] of segs) {
      if (!count) continue;
      const seg = h('span', 'sqx-rbar-s ' + cls);
      seg.style.flexGrow = String(count);
      bar.appendChild(seg);
    }
    return bar;
  }

  // Tiny stacked-column histogram. bars: [{label, segs: [[cls, count], ...]}].
  function histo(bars) {
    let maxTotal = 1;
    for (const b of bars) {
      const t = b.segs.reduce((a, s) => a + s[1], 0);
      if (t > maxTotal) maxTotal = t;
    }
    const box = h('div', 'sqx-histo');
    for (const b of bars) {
      const col = h('div', 'sqx-histo-c');
      const total = b.segs.reduce((a, s) => a + s[1], 0);
      col.appendChild(h('div', 'sqx-histo-n', total ? String(total) : ''));
      const barEl = h('div', 'sqx-histo-b');
      for (const [cls, count] of b.segs) {
        if (!count) continue;
        const seg = h('div', 'sqx-histo-s ' + cls);
        seg.style.height = Math.max(2, Math.round((count / maxTotal) * 30)) + 'px';
        barEl.appendChild(seg);
      }
      if (!total) barEl.appendChild(h('div', 'sqx-histo-s sqx-histo-zero'));
      col.appendChild(barEl);
      col.appendChild(h('div', 'sqx-histo-l', b.label));
      box.appendChild(col);
    }
    return box;
  }

  // Multiplier chip text tuned for narrow columns: 1.89 / 12.4 / 110.
  const fmtPoint = (v) => (v >= 100 ? String(Math.round(v)) : v >= 10 ? v.toFixed(1) : v.toFixed(2));

  // "0.5×" / "1.5×" / "41×" — for plinko slot values that are already round.
  const fmtSlotMult = (v) => (v >= 10 ? Math.round(v) : v) + '×';

  const multChipCls = (v) => (v >= 10 ? 'sqx-xchip-hot' : v < 1 ? 'sqx-xchip-neg' : v === 1 ? 'sqx-xchip-dim' : 'sqx-xchip-pos');

  function crashExtras(session) {
    const points = (session.ticks || []).map((t) => t.crashPoint).filter(isNum);
    const n = points.length;
    if (!n) return null;
    const sorted = [...points].sort((a, b) => a - b);
    const mid = n >> 1;
    const med = n % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    const under2 = points.filter((p) => p < 2).length;
    const big = points.filter((p) => p >= 10).length;
    // Longest (and current) run of rounds without a 10×+ payout window.
    let maxDry = 0, run = 0;
    for (const p of points) {
      if (p >= 10) run = 0;
      else if (++run > maxDry) maxDry = run;
    }
    let nowDry = 0;
    for (let i = n - 1; i >= 0 && points[i] < 10; i--) nowDry++;

    const { wrap, card } = xSection('Crash points', n);
    card.appendChild(xStats([
      ['median', fmtMult(med)],
      ['< 2×', pctOf(under2, n), under2 * 2 >= n ? 'sqx-neg' : '', under2 + '/' + n],
      ['≥ 10×', String(big), big ? 'sqx-hot' : 'sqx-dim', big + '/' + n],
      ['10× drought', String(maxDry), '', 'now ' + nowDry],
    ]));
    const k = Math.min(15, n);
    card.appendChild(xCap('last ' + k + ' rounds · newest first'));
    card.appendChild(chipStrip(5, points.slice(-k).reverse().map((v) => ({
      text: fmtPoint(v),
      cls: v >= 10 ? 'sqx-xchip-hot' : v < 2 ? 'sqx-xchip-neg' : 'sqx-xchip-pos',
    }))));
    return wrap;
  }

  const WHEEL_REDS = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);
  const wheelColorOf = (num) => (num === 0 ? 'green' : WHEEL_REDS.has(num) ? 'red' : 'black');

  // A wheel-colored number chip, optionally stacked over a tiny hit count.
  function wheelChipCell(num, sub) {
    const cell = h('span', 'sqx-wcell');
    cell.appendChild(h('span', 'sqx-wchip sqx-wchip-' + wheelColorOf(num), String(num)));
    if (sub != null) cell.appendChild(h('span', 'sqx-wsub', sub));
    return cell;
  }

  function rouletteExtras(session) {
    const ticks = (session.ticks || []).filter((t) => isNum(t.number));
    const n = ticks.length;
    if (!n) return null;
    const freq = new Array(37).fill(0);
    const lastSeen = new Array(37).fill(-1);
    let red = 0, black = 0, green = 0;
    ticks.forEach((t, i) => {
      freq[t.number]++;
      lastSeen[t.number] = i;
      const c = t.color || wheelColorOf(t.number);
      if (c === 'red') red++;
      else if (c === 'green') green++;
      else black++;
    });
    const idx = Array.from({ length: 37 }, (_, i) => i);
    const hot = idx
      .filter((i) => freq[i] > 0)
      .sort((a, b) => freq[b] - freq[a] || lastSeen[b] - lastSeen[a])
      .slice(0, 5);
    const cold = idx
      .slice()
      .sort((a, b) => freq[a] - freq[b] || lastSeen[a] - lastSeen[b])
      .slice(0, 5);

    const { wrap, card } = xSection('Wheel', n);
    card.appendChild(segBar([
      ['sqx-rbar-red', red],
      ['sqx-rbar-black', black],
      ['sqx-rbar-green', green],
    ]));
    const leg = h('div', 'sqx-rleg');
    const legItem = (cls, letter, c) => {
      const it = h('span', 'sqx-rleg-i');
      it.appendChild(h('span', 'sqx-wheel-dot sqx-wheel-' + cls));
      it.appendChild(num(letter + ' ' + c));
      it.appendChild(h('span', 'sqx-rleg-p', pctOf(c, n)));
      return it;
    };
    leg.append(legItem('red', 'R', red), legItem('black', 'B', black), legItem('green', 'G', green));
    card.appendChild(leg);

    const wrow = (label, nums) => {
      const row = h('div', 'sqx-wrow');
      row.appendChild(h('span', 'sqx-wrow-l', label));
      const chips = h('span', 'sqx-wrow-chips');
      for (const i of nums) chips.appendChild(wheelChipCell(i, '×' + freq[i]));
      row.appendChild(chips);
      return row;
    };
    if (hot.length) card.appendChild(wrow('hot', hot));
    card.appendChild(wrow('cold', cold));

    const k = Math.min(12, n);
    card.appendChild(xCap('last ' + k + ' spins · newest first'));
    const strip = h('div', 'sqx-wstrip');
    for (const t of ticks.slice(-k).reverse()) {
      strip.appendChild(h('span', 'sqx-wchip sqx-wchip-' + (t.color || wheelColorOf(t.number)), String(t.number)));
    }
    card.appendChild(strip);
    return wrap;
  }

  function minesExtras(session) {
    const done = (session.rounds || []).filter((r) => r.result === 'win' || r.result === 'loss');
    if (!done.length) return null;
    const wins = done.filter((r) => r.result === 'win');
    const busts = done.filter((r) => r.result === 'loss');
    const mults = wins.map((r) => r.multiplier).filter(isNum);
    const avg = mults.length ? mults.reduce((a, b) => a + b, 0) / mults.length : null;
    const best = mults.length ? Math.max(...mults) : null;
    const depthOf = (r) => (r.detail && isNum(r.detail.revealedCount) ? r.detail.revealedCount : null);
    const wDepths = wins.map(depthOf).filter(isNum);
    const bDepths = busts.map(depthOf).filter(isNum);
    const avgD = (a) => (a.length ? (a.reduce((x, y) => x + y, 0) / a.length).toFixed(1) : '—');

    const { wrap, card } = xSection('Mines', done.length);
    card.appendChild(xStats([
      ['cashed', pctOf(wins.length, done.length),
        wins.length * 2 >= done.length ? 'sqx-pos' : 'sqx-neg', wins.length + '/' + done.length],
      ['avg cash', avg == null ? '—' : fmtMult(avg), avg == null ? 'sqx-dim' : ''],
      ['best', best == null ? '—' : fmtMult(best), best != null && best >= 5 ? 'sqx-hot' : ''],
      ['picks ✓/✗', avgD(wDepths) + ' / ' + avgD(bDepths)],
    ]));

    // Depth pattern: how many safe picks games reach before cashing (green)
    // or hitting a bomb (red), bucketed per pick count.
    if (wDepths.length || bDepths.length) {
      const maxDepth = Math.min(10, Math.max(1, ...wDepths, ...bDepths));
      const minDepth = bDepths.includes(0) ? 0 : 1;
      const bars = [];
      for (let d = minDepth; d <= maxDepth; d++) {
        bars.push({
          label: String(d),
          segs: [
            ['sqx-hpos', wDepths.filter((x) => x === d).length],
            ['sqx-hneg', bDepths.filter((x) => x === d).length],
          ],
        });
      }
      card.appendChild(xCap('depth pattern · picks at cashout ✓ / bust ✗'));
      card.appendChild(histo(bars));
    }

    const k = Math.min(12, done.length);
    card.appendChild(xCap('last ' + k + ' games · newest first'));
    card.appendChild(chipStrip(6, done.slice(-k).reverse().map((r) => {
      if (r.result === 'win') {
        return { text: isNum(r.multiplier) ? fmtMult(r.multiplier) : '✓', cls: 'sqx-xchip-pos' };
      }
      const d = depthOf(r);
      return { text: '✗' + (d != null ? d : ''), cls: 'sqx-xchip-neg', title: d != null ? 'bomb on pick ' + (d + 1) : 'bust' };
    })));
    return wrap;
  }

  function plinkoExtras(session) {
    const mults = (session.rounds || []).map((r) => r.multiplier).filter(isNum);
    const n = mults.length;
    if (!n) return null;
    const sorted = [...mults].sort((a, b) => a - b);
    const mid = n >> 1;
    const med = n % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    const avg = mults.reduce((a, b) => a + b, 0) / n;
    const best = sorted[n - 1];
    const big = mults.filter((v) => v >= 10).length;

    const { wrap, card } = xSection('Drops', n);
    card.appendChild(xStats([
      ['avg', fmtMult(avg), avg >= 1 ? 'sqx-pos' : 'sqx-neg'],
      ['median', fmtMult(med), med < 1 ? 'sqx-neg' : ''],
      ['best', fmtSlotMult(best), best >= 10 ? 'sqx-hot' : best > 1 ? 'sqx-pos' : ''],
      ['≥ 10×', String(big), big ? 'sqx-hot' : 'sqx-dim', big + '/' + n],
    ]));

    // Histogram over the slot multipliers actually hit this session.
    const freq = new Map();
    for (const v of mults) freq.set(v, (freq.get(v) || 0) + 1);
    const values = [...freq.keys()].sort((a, b) => a - b);
    card.appendChild(xCap('multiplier distribution'));
    card.appendChild(histo(values.map((v) => ({
      label: fmtSlotMult(v),
      segs: [[v >= 10 ? 'sqx-hhot' : v < 1 ? 'sqx-hneg' : v === 1 ? 'sqx-hdim' : 'sqx-hpos', freq.get(v)]],
    }))));

    const k = Math.min(16, n);
    card.appendChild(xCap('last ' + k + ' drops · newest first'));
    card.appendChild(chipStrip(8, mults.slice(-k).reverse().map((v) => ({
      text: fmtSlotMult(v),
      cls: multChipCls(v),
    }))));
    return wrap;
  }

  const BJ_FACE_VAL = { A: 11, K: 10, Q: 10, J: 10 };

  // Best blackjack total for a hand (aces soften), null if any card unknown.
  function handTotalOf(cards) {
    if (!Array.isArray(cards) || !cards.length) return null;
    let total = 0, aces = 0;
    for (const c of cards) {
      const p = parseCard(c);
      if (!p) return null;
      const v = BJ_FACE_VAL[p.rank] || parseInt(p.rank, 10);
      if (!isNum(v)) return null;
      if (p.rank === 'A') aces++;
      total += v;
    }
    while (total > 21 && aces) { total -= 10; aces--; }
    return total;
  }

  function blackjackExtras(session) {
    const rounds = session.rounds || [];
    if (!rounds.length) return null;
    let w = 0, l = 0, p = 0, bj = 0, meBust = 0, dlrBust = 0, known = 0;
    const hands = [];
    for (const r of rounds) {
      if (r.result === 'win') w++;
      else if (r.result === 'loss') l++;
      else if (r.result === 'push') p++;
      const d = r.detail || {};
      if (d.blackjack) bj++;
      const pt = isNum(d.playerTotal) ? d.playerTotal : handTotalOf(d.player);
      const dt = isNum(d.dealerTotal) ? d.dealerTotal : handTotalOf(d.dealer);
      if (isNum(pt)) {
        known++;
        if (pt > 21) meBust++;
        if (isNum(dt) && dt > 21 && pt <= 21) dlrBust++;
      }
      hands.push({ pt, bj: !!d.blackjack, result: r.result });
    }
    const record = h('span', null);
    record.append(
      h('span', w ? 'sqx-pos' : 'sqx-dim', String(w)),
      h('span', 'sqx-dim', '-'),
      h('span', l ? 'sqx-neg' : 'sqx-dim', String(l)),
      h('span', 'sqx-dim', '-'),
      h('span', 'sqx-dim', String(p))
    );

    const { wrap, card } = xSection('Hands', rounds.length);
    card.appendChild(xStats([
      ['w-l-p', record, '', w + l ? pctOf(w, w + l) + ' win' : null],
      ['blackjacks', String(bj), bj ? 'sqx-hot' : 'sqx-dim', bj + '/' + rounds.length],
      ['you bust', pctOf(meBust, known), meBust ? 'sqx-neg' : 'sqx-dim', meBust + '/' + known],
      ['dlr bust', pctOf(dlrBust, known), dlrBust ? 'sqx-pos' : 'sqx-dim', dlrBust + '/' + known],
    ]));
    card.appendChild(segBar([
      ['sqx-rbar-pos', w],
      ['sqx-rbar-neg', l],
      ['sqx-rbar-dim', p],
    ]));

    const k = Math.min(12, hands.length);
    card.appendChild(xCap('last ' + k + ' hands · your total · newest first'));
    card.appendChild(chipStrip(6, hands.slice(-k).reverse().map((hd) => ({
      text: hd.bj ? 'BJ' : hd.pt != null ? String(hd.pt) : hd.result === 'win' ? 'W' : hd.result === 'loss' ? 'L' : 'P',
      cls: hd.bj ? 'sqx-xchip-hot'
        : hd.result === 'win' ? 'sqx-xchip-pos'
        : hd.result === 'loss' ? 'sqx-xchip-neg' : 'sqx-xchip-dim',
    }))));
    return wrap;
  }

  function renderExtras(body, session) {
    const builders = {
      crash: crashExtras,
      roulette: rouletteExtras,
      mines: minesExtras,
      plinko: plinkoExtras,
      blackjack: blackjackExtras,
    };
    const build = builders[session.game];
    let el = null;
    if (build) el = build(session);
    else {
      // Unknown game: fall back to whatever summary the background computed.
      const x = session.stats && session.stats.extra;
      if (x) {
        const { wrap, card } = xSection(x.label || 'extras', x.count);
        const parts = [];
        for (const key of ['median', 'avg', 'best']) if (x[key] != null) parts.push(key + ' ' + x[key] + '×');
        if (x.record) parts.push(x.record);
        if (parts.length) card.appendChild(xCap(parts.join(' · ')));
        el = parts.length ? wrap : null;
      }
    }
    if (el) body.appendChild(el);
  }

  // ---- history --------------------------------------------------------------
  // DevTools-grade round log: every round reachable in a scrollable card
  // (newest first, batched in as you scroll), 22px mono rows with a win/loss
  // severity stripe, relative age, bet / mult / net, click-to-expand per-round
  // detail, and a rolling "last N" net summary in the section label.

  const HIST_INITIAL = 50;
  const HIST_BATCH = 100;
  let histSessionId = null;
  let histExpandedKey = null;
  let histScrollTop = 0;

  const histKey = (r) => (r.id != null ? String(r.id) : 't' + r.ts);

  // Severity stripe color: alpha scales with |profit| vs the session's biggest
  // swing, so heavy hits/wins read at a glance while pushes stay quiet.
  function histStripe(r, maxAbs) {
    const stripe = h('span', 'sqx-stripe');
    const rgb =
      r.result === 'win' ? '63, 221, 139' : r.result === 'loss' ? '255, 93, 110' : '151, 163, 197';
    const p = typeof r.profit === 'number' ? Math.abs(r.profit) : 0;
    const a = r.result === 'win' || r.result === 'loss'
      ? 0.3 + 0.7 * Math.sqrt(maxAbs > 0 ? Math.min(1, p / maxAbs) : 0)
      : 0.25;
    stripe.style.background = 'rgba(' + rgb + ', ' + a.toFixed(2) + ')';
    return stripe;
  }

  // Tiny inline hand for blackjack detail rows: "K♥ 7♣" with red suits tinted.
  function miniCards(arr) {
    const s = h('span', 'sqx-rd-cards');
    for (const c of arr) {
      const p = parseCard(c);
      const red = p && (p.suit === 'hearts' || p.suit === 'diamonds');
      s.appendChild(h('span', red ? 'sqx-card-r' : null, p ? p.rank + (SUIT_GLYPH[p.suit] || '') : '?'));
    }
    return s;
  }

  // Expanded per-round detail line: exact time + payout + whatever the
  // adapter mapped for this game (crash point, wheel number, cards, ...).
  function histDetail(session, r) {
    const d = r.detail || {};
    const box = h('div', 'sqx-row-detail');
    const pair = (label, val) => {
      const g = h('span', 'sqx-rd');
      g.appendChild(h('span', 'sqx-rd-l', label));
      const v = h('span', 'sqx-rd-v');
      if (val instanceof Node) v.appendChild(val);
      else v.textContent = String(val);
      g.appendChild(v);
      box.appendChild(g);
    };
    if (typeof r.ts === 'number') pair('at', fmtClock(r.ts));
    if (typeof r.payout === 'number') pair('paid', fmtAmount(r.payout));
    const game = session.game;
    if (game === 'crash') {
      if (typeof d.crashPoint === 'number') pair('crash', d.crashPoint + '×');
      pair('cashed', typeof d.cashedOutAt === 'number' ? d.cashedOutAt + '×' : 'rode it down');
    } else if (game === 'roulette') {
      if (d.number != null) pair('landed', wheelValue(d.color, d.number));
      if (d.betType) pair('bet', d.betType);
    } else if (game === 'mines') {
      if (typeof d.mines === 'number') pair('mines', d.mines);
      if (typeof d.revealedCount === 'number') pair('revealed', d.revealedCount);
    } else if (game === 'plinko') {
      if (d.slot != null) pair('slot', '#' + d.slot);
      if (d.risk) pair('risk', d.risk);
    } else if (game === 'blackjack') {
      if (Array.isArray(d.player) && d.player.length) pair('you', miniCards(d.player));
      if (Array.isArray(d.dealer) && d.dealer.length) pair('dealer', miniCards(d.dealer));
      if (d.blackjack) box.appendChild(h('span', 'sqx-rd-flag', 'blackjack'));
    }
    if (r.result === 'push') box.appendChild(h('span', 'sqx-rd-flag sqx-dim', 'push'));
    return box;
  }

  function renderHistory(body, session) {
    const rounds = session.rounds;
    if (!rounds.length) return;
    if (session.id !== histSessionId) {
      histSessionId = session.id;
      histExpandedKey = null;
      histScrollTop = 0;
    }

    // Ages are measured against the snapshot, not the wall clock, so replayed
    // and live snapshots render identically.
    const nowRef = Math.max(
      (latest && latest.generatedAt) || 0,
      session.lastActivityAt || 0,
      rounds[rounds.length - 1].ts || 0
    ) || Date.now();

    let maxAbs = 0;
    for (const r of rounds) {
      if (typeof r.profit === 'number' && Math.abs(r.profit) > maxAbs) maxAbs = Math.abs(r.profit);
    }

    const wrap = h('div', 'sqx-history');
    const lab = h('div', 'sqx-label');
    lab.appendChild(h('span', null, 'History'));
    lab.appendChild(h('span', 'sqx-count', String(rounds.length)));
    // Rolling summary: net over the most recent N rounds.
    const n = Math.min(20, rounds.length);
    let lastNet = 0;
    for (let i = rounds.length - n; i < rounds.length; i++) {
      if (typeof rounds[i].profit === 'number') {
        lastNet = Math.round((lastNet + rounds[i].profit) * 100) / 100;
      }
    }
    const sum = h('span', 'sqx-hist-sum');
    sum.appendChild(h('span', 'sqx-hist-sum-l', 'last ' + n));
    sum.appendChild(num(fmtMoney(lastNet), posNegCls(lastNet)));
    lab.appendChild(sum);
    wrap.appendChild(lab);

    const card = h('div', 'sqx-hist-card');
    const headRow = h('div', 'sqx-hrow sqx-hrow-head');
    headRow.append(
      h('span', null, 'ago'),
      h('span', 'sqx-r', 'bet'),
      h('span', 'sqx-r', 'mult'),
      h('span', 'sqx-r', 'net')
    );
    card.appendChild(headRow);

    const scroll = h('div', 'sqx-hist-scroll');
    const list = h('div');
    scroll.appendChild(list);
    card.appendChild(scroll);
    wrap.appendChild(card);
    body.appendChild(wrap);

    const makeRow = (r) => {
      const row = h('div', 'sqx-hrow');
      row.appendChild(histStripe(r, maxAbs));
      row.appendChild(h('span', 'sqx-dim', fmtAgo(nowRef - r.ts)));
      row.appendChild(h('span', 'sqx-r', typeof r.bet === 'number' ? fmtAmount(r.bet) : '—'));
      row.appendChild(
        h('span', 'sqx-r ' + (typeof r.multiplier === 'number' && r.multiplier >= 10 ? 'sqx-hot' : 'sqx-dim'),
          fmtMult(r.multiplier))
      );
      row.appendChild(
        h('span', 'sqx-r ' + (r.result === 'win' ? 'sqx-pos' : r.result === 'loss' ? 'sqx-neg' : 'sqx-dim'),
          typeof r.profit === 'number' ? fmtMoney(r.profit) : (r.result || '—'))
      );
      row.onclick = () => {
        const wasOpen = row.classList.contains('sqx-sel');
        const oldDet = list.querySelector('.sqx-row-detail');
        const oldSel = list.querySelector('.sqx-hrow.sqx-sel');
        if (oldDet) oldDet.remove();
        if (oldSel) oldSel.classList.remove('sqx-sel');
        if (wasOpen) {
          histExpandedKey = null;
          return;
        }
        histExpandedKey = histKey(r);
        row.classList.add('sqx-sel');
        row.after(histDetail(session, r));
      };
      if (histKey(r) === histExpandedKey) {
        row.classList.add('sqx-sel');
        const frag = document.createDocumentFragment();
        frag.append(row, histDetail(session, r));
        return frag;
      }
      return row;
    };

    // Newest first, appended in batches so 300-round sessions stay light.
    let shownCount = 0;
    const moreRow = h('div', 'sqx-hist-more');
    const appendBatch = (k) => {
      const frag = document.createDocumentFragment();
      const start = rounds.length - 1 - shownCount;
      const end = Math.max(start - k + 1, 0);
      for (let i = start; i >= end; i--) frag.appendChild(makeRow(rounds[i]));
      shownCount += start - end + 1;
      list.appendChild(frag);
      const remaining = rounds.length - shownCount;
      if (remaining > 0) {
        moreRow.textContent = '↓ ' + remaining + ' earlier ' + (remaining === 1 ? 'round' : 'rounds');
        if (!moreRow.parentNode) scroll.appendChild(moreRow);
      } else {
        moreRow.remove();
      }
    };
    moreRow.onclick = () => appendBatch(HIST_BATCH);
    scroll.addEventListener('scroll', () => {
      histScrollTop = scroll.scrollTop;
      if (scroll.scrollTop + scroll.clientHeight > scroll.scrollHeight - 44 &&
          shownCount < rounds.length) {
        appendBatch(HIST_BATCH);
      }
    });

    appendBatch(Math.min(HIST_INITIAL, rounds.length));
    if (histScrollTop) scroll.scrollTop = histScrollTop;
  }

  function renderRaw(body) {
    body.appendChild(
      h('div', 'sqx-raw-hint',
        'Recent captured payloads, newest first — the shapes the site actually sends, for extending src/adapters/.')
    );
    const list = h('div', 'sqx-raw');
    body.appendChild(list);
    fillRaw(list, lastRawLog);
  }

  let lastRawLog = [];
  function fillRaw(list, entries) {
    list.textContent = '';
    if (!entries.length) {
      list.appendChild(emptyState('Nothing captured yet', 'Payloads show up as the page talks to its backend.'));
      return;
    }
    for (const e of entries.slice(0, 25)) {
      const row = h('div', 'sqx-raw-row');
      const line = h('div');
      line.appendChild(h('span', 'sqx-raw-kind', e.kind + ' ' + (e.direction === 'out' ? '↑' : '↓')));
      line.appendChild(document.createTextNode(fmtTime(e.ts) + ' ' + shortUrl(e.url)));
      row.appendChild(line);
      if (e.keys && e.keys.length) row.appendChild(h('div', 'sqx-raw-keys', 'keys: ' + e.keys.join(', ')));
      list.appendChild(row);
    }
  }

  const shortUrl = (u) => {
    try {
      const p = new URL(u, location.origin);
      return p.pathname.slice(0, 60);
    } catch {
      return String(u).slice(0, 60);
    }
  };

  function loadRawLog() {
    // content.js shares this isolated world and exposes the log on SQX.
    lastRawLog = (SQX.getRawLog && SQX.getRawLog()) || lastRawLog;
    const list = root && root.querySelector('.sqx-raw');
    if (list) fillRaw(list, lastRawLog);
  }

  // Refresh raw view periodically while open.
  setInterval(() => {
    if (tab === 'raw' && !collapsed) loadRawLog();
  }, 2000);

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === 'SQX_STATE') {
      latest = msg.state;
      render();
    }
  });

  const boot = () => {
    chrome.runtime
      .sendMessage({ type: 'SQX_GET_STATE' })
      .then((res) => {
        if (res && res.state) {
          latest = res.state;
          render();
        }
      })
      .catch(() => {});
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
