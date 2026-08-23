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

  const fmtDur = (ms) => {
    if (typeof ms !== 'number' || ms < 0) return null;
    const m = Math.floor(ms / 60000);
    if (m < 1) return '<1m';
    if (m < 60) return m + 'm';
    return Math.floor(m / 60) + 'h' + String(m % 60).padStart(2, '0') + 'm';
  };

  const posNegCls = (n) => (n > 0 ? 'sqx-pos' : n < 0 ? 'sqx-neg' : 'sqx-dim');

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
    box.appendChild(h('div', 'sqx-empty-t', title));
    if (sub) box.appendChild(h('div', 'sqx-empty-s', sub));
    return box;
  }

  function renderCurrent(body, session) {
    const cur = session.current;
    if (!cur) return;
    const box = h('div', 'sqx-current');

    const top = h('div', 'sqx-current-top');
    top.appendChild(h('span', 'sqx-live-dot'));
    top.appendChild(h('span', 'sqx-phase', cur.phase || 'deal'));
    if (typeof cur.bet === 'number') {
      const bet = h('span', 'sqx-current-bet');
      bet.appendChild(document.createTextNode('bet '));
      bet.appendChild(num(cur.bet.toFixed(2)));
      top.appendChild(bet);
    }
    box.appendChild(top);

    if (typeof cur.multiplier === 'number') {
      box.appendChild(h('div', 'sqx-mult-big', cur.multiplier.toFixed(2) + '×'));
    }

    const d = cur.detail || {};
    if (session.game === 'blackjack' && (d.player || d.dealer)) {
      const cards = (arr) => (Array.isArray(arr) ? arr.map(cardText).join(' ') : '?');
      box.appendChild(h('div', 'sqx-detail', 'You: ' + cards(d.player) + (d.playerTotal ? ' (' + d.playerTotal + ')' : '')));
      box.appendChild(h('div', 'sqx-detail', 'Dealer: ' + cards(d.dealer) + (d.dealerTotal ? ' (' + d.dealerTotal + ')' : '')));
    } else if (session.game === 'mines') {
      const bits = [];
      if (d.mines != null) bits.push(d.mines + ' mines');
      if (d.revealedCount != null) bits.push(d.revealedCount + ' revealed');
      if (bits.length) box.appendChild(h('div', 'sqx-detail', bits.join(' · ')));
    } else if (session.game === 'crash' && d.crashPoint != null) {
      box.appendChild(h('div', 'sqx-detail', 'crashed at ' + d.crashPoint + '×'));
    } else if (session.game === 'roulette' && d.number != null) {
      box.appendChild(h('div', 'sqx-detail', 'landed ' + d.number + ' (' + d.color + ')'));
    }
    body.appendChild(box);
  }

  function cardText(c) {
    if (c == null) return '?';
    if (typeof c === 'string') return c;
    if (typeof c === 'object') {
      const rank = c.rank ?? c.value ?? c.face ?? '?';
      const suit = { hearts: '♥', diamonds: '♦', clubs: '♣', spades: '♠' }[String(c.suit || '').toLowerCase()] || c.suit || '';
      return String(rank) + suit;
    }
    return String(c);
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
  // with a tiny "0" label, and a dot on the latest point. No other furniture.
  function renderGraph(body, session) {
    const s = session.stats;
    if (!s || !s.rounds) return;
    const vals = profitSeries(session);

    const box = h('div', 'sqx-graph');
    const top = h('div', 'sqx-graph-top');
    top.appendChild(h('span', 'sqx-graph-l', 'Profit'));
    top.appendChild(h('span', 'sqx-count', s.rounds + (s.rounds === 1 ? ' bet' : ' bets')));
    top.appendChild(num(fmtMoney(s.net), 'sqx-graph-net ' + posNegCls(s.net)));
    box.appendChild(top);

    if (vals.length >= 2) {
      const W = 272, H = 54, PT = 5, PB = 5;
      let min = 0, max = 0;
      for (const v of vals) {
        if (v < min) min = v;
        if (v > max) max = v;
      }
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
      cell('wagered', fmtAmount(s.wagered)),
      cell('avg bet', avgBet == null ? '—' : fmtAmount(avgBet)),
      cell('rtp', rtp == null ? '—' : rtp + '%', rtp == null ? '' : rtp >= 100 ? 'sqx-pos' : ''),
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

  function renderExtras(body, session) {
    const x = session.stats && session.stats.extra;
    if (!x) return;
    const box = h('div', 'sqx-extra');
    const lab = h('div', 'sqx-label');
    lab.appendChild(h('span', null, x.label));
    if (x.count != null) lab.appendChild(h('span', 'sqx-count', String(x.count)));
    box.appendChild(lab);
    const parts = [];
    if (x.median != null) parts.push('median ' + x.median + '×');
    if (x.under2x != null) parts.push(x.under2x + ' under 2×');
    if (x.avg != null) parts.push('avg ' + x.avg + '×');
    if (x.best != null) parts.push('best ' + x.best + '×');
    if (x.bestMultiplier != null) parts.push('best cashout ' + x.bestMultiplier + '×');
    if (x.cashouts != null) parts.push(x.cashouts + ' cashouts / ' + x.busts + ' busts');
    if (x.record) parts.push(x.record);
    if (x.hot) parts.push('hot: ' + x.hot.join(' '));
    if (x.colors) parts.push('R' + x.colors.red + ' B' + x.colors.black + ' G' + x.colors.green);
    if (parts.length) box.appendChild(h('div', 'sqx-detail', parts.join(' · ')));
    if (Array.isArray(x.last) && x.last.length) {
      const strip = h('div', 'sqx-strip');
      for (const v of x.last) {
        const chip = h('span', 'sqx-chip', String(v));
        if (session.game === 'crash') chip.classList.add(v < 2 ? 'sqx-neg' : 'sqx-pos');
        strip.appendChild(chip);
      }
      box.appendChild(strip);
    }
    body.appendChild(box);
  }

  function renderHistory(body, session) {
    if (!session.rounds.length) return;
    const list = h('div', 'sqx-history');
    const lab = h('div', 'sqx-label');
    lab.appendChild(h('span', null, 'History'));
    lab.appendChild(h('span', 'sqx-count', String(session.rounds.length)));
    list.appendChild(lab);

    const headRow = h('div', 'sqx-row sqx-row-head');
    headRow.append(h('span', null, 'time'), h('span', null, 'bet'), h('span', null, 'mult'), h('span', null, 'net'));
    list.appendChild(headRow);

    const shown = session.rounds.slice(-8).reverse();
    for (const r of shown) {
      const row = h('div', 'sqx-row');
      row.appendChild(h('span', 'sqx-dim', fmtTime(r.ts)));
      row.appendChild(h('span', null, typeof r.bet === 'number' ? r.bet.toFixed(2) : '—'));
      row.appendChild(h('span', 'sqx-dim', typeof r.multiplier === 'number' ? r.multiplier.toFixed(2) + '×' : ''));
      row.appendChild(
        h('span', r.result === 'win' ? 'sqx-pos' : r.result === 'loss' ? 'sqx-neg' : 'sqx-dim',
          typeof r.profit === 'number' ? fmtMoney(r.profit) : r.result)
      );
      list.appendChild(row);
    }
    if (session.rounds.length > shown.length) {
      list.appendChild(h('div', 'sqx-more', 'showing last ' + shown.length + ' of ' + session.rounds.length));
    }
    body.appendChild(list);
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
