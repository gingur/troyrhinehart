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

  const fmtMoney = (n) => {
    if (typeof n !== 'number') return '—';
    const sign = n > 0 ? '+' : '';
    return sign + n.toFixed(2);
  };

  const fmtTime = (ts) => new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

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

    const game = latest && latest.focusedGame;
    const session = game && latest.active ? latest.active[game] : null;

    // Header
    const head = h('div', 'sqx-head');
    head.appendChild(h('span', 'sqx-title', 'SpinQuest HUD'));
    head.appendChild(h('span', 'sqx-game', game ? game.toUpperCase() : 'no game detected'));
    const btns = h('span', 'sqx-btns');
    const rawBtn = h('button', 'sqx-btn', tab === 'raw' ? 'stats' : 'raw');
    rawBtn.title = 'Toggle raw capture inspector';
    rawBtn.onclick = () => {
      tab = tab === 'raw' ? 'session' : 'raw';
      render();
      if (tab === 'raw') loadRawLog();
    };
    const collapseBtn = h('button', 'sqx-btn', collapsed ? '▸' : '▾');
    collapseBtn.onclick = () => {
      collapsed = !collapsed;
      render();
    };
    btns.append(rawBtn, collapseBtn);
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
        h('div', 'sqx-empty', game
          ? 'Waiting for game data… place a bet and rounds will appear here.'
          : 'Open a Plinko, Mines, Crash, Blackjack, or Roulette page.')
      );
      return;
    }

    renderCurrent(body, session);
    renderStats(body, session);
    renderExtras(body, session);
    renderHistory(body, session);

    const foot = h('div', 'sqx-foot');
    const newBtn = h('button', 'sqx-btn', 'new session');
    newBtn.onclick = () => chrome.runtime.sendMessage({ type: 'SQX_NEW_SESSION', game }).catch(() => {});
    foot.append(
      h('span', 'sqx-dim', 'since ' + fmtTime(session.startedAt)),
      newBtn
    );
    body.appendChild(foot);
  }

  function renderCurrent(body, session) {
    const cur = session.current;
    if (!cur) return;
    const box = h('div', 'sqx-current');
    box.appendChild(h('div', 'sqx-label', 'CURRENT ' + (cur.phase || 'deal').toUpperCase()));
    const line = h('div', 'sqx-current-line');
    if (typeof cur.bet === 'number') line.appendChild(h('span', null, 'bet ' + cur.bet));
    if (typeof cur.multiplier === 'number') line.appendChild(h('span', 'sqx-mult', cur.multiplier.toFixed(2) + '×'));
    box.appendChild(line);

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

  function renderStats(body, session) {
    const s = session.stats;
    if (!s || !s.rounds) return;
    const grid = h('div', 'sqx-stats');
    const cell = (label, value, cls) => {
      const c = h('div', 'sqx-stat');
      c.appendChild(h('div', 'sqx-stat-v' + (cls ? ' ' + cls : ''), String(value)));
      c.appendChild(h('div', 'sqx-stat-l', label));
      return c;
    };
    grid.append(
      cell('rounds', s.rounds),
      cell('win rate', s.winRate == null ? '—' : s.winRate + '%'),
      cell('net', fmtMoney(s.net), s.net > 0 ? 'sqx-pos' : s.net < 0 ? 'sqx-neg' : ''),
      cell('streak', s.streak === 0 ? '—' : (s.streak > 0 ? 'W' : 'L') + Math.abs(s.streak),
        s.streak > 0 ? 'sqx-pos' : s.streak < 0 ? 'sqx-neg' : ''),
      cell('wagered', s.wagered.toFixed(2)),
      cell('best / worst', fmtMoney(s.biggestWin) + ' / ' + fmtMoney(s.biggestLoss))
    );
    body.appendChild(grid);
  }

  function renderExtras(body, session) {
    const x = session.stats && session.stats.extra;
    if (!x) return;
    const box = h('div', 'sqx-extra');
    box.appendChild(h('div', 'sqx-label', (session.game + ' — ' + x.label).toUpperCase()));
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
    list.appendChild(h('div', 'sqx-label', 'HISTORY'));
    for (const r of session.rounds.slice(-8).reverse()) {
      const row = h('div', 'sqx-row');
      row.appendChild(h('span', 'sqx-dim', fmtTime(r.ts)));
      row.appendChild(h('span', null, typeof r.bet === 'number' ? r.bet.toFixed(2) : '—'));
      row.appendChild(h('span', 'sqx-mult', typeof r.multiplier === 'number' ? r.multiplier.toFixed(2) + '×' : ''));
      row.appendChild(
        h('span', r.result === 'win' ? 'sqx-pos' : r.result === 'loss' ? 'sqx-neg' : 'sqx-dim',
          typeof r.profit === 'number' ? fmtMoney(r.profit) : r.result)
      );
      list.appendChild(row);
    }
    body.appendChild(list);
  }

  function renderRaw(body) {
    body.appendChild(
      h('div', 'sqx-empty',
        'Recent captured payloads (newest first). Use this to see what the site actually sends, then extend the adapters in src/adapters/.')
    );
    const list = h('div', 'sqx-raw');
    body.appendChild(list);
    fillRaw(list, lastRawLog);
  }

  let lastRawLog = [];
  function fillRaw(list, entries) {
    list.textContent = '';
    if (!entries.length) {
      list.appendChild(h('div', 'sqx-dim', 'Nothing captured yet.'));
      return;
    }
    for (const e of entries.slice(0, 25)) {
      const row = h('div', 'sqx-raw-row');
      row.appendChild(h('div', null, `[${e.kind} ${e.direction}] ${fmtTime(e.ts)} ${shortUrl(e.url)}`));
      if (e.keys && e.keys.length) row.appendChild(h('div', 'sqx-dim', 'keys: ' + e.keys.join(', ')));
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
