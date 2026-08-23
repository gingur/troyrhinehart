'use strict';

const $ = (sel) => document.querySelector(sel);

const fmtMoney = (n) => {
  if (typeof n !== 'number') return '—';
  return (n > 0 ? '+' : '') + n.toFixed(2);
};

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

function render(state) {
  const main = $('#content');
  main.textContent = '';

  const games = Object.keys(state.active || {});
  if (!games.length) {
    const box = el('div', 'empty');
    box.appendChild(el('div', 't', 'No active sessions'));
    box.appendChild(el('div', 's', 'Open a game on spinquest.com and play a round.'));
    main.appendChild(box);
  }

  for (const game of games) {
    const s = state.active[game];
    const stats = s.stats || {};
    const box = el('div', 'session');

    const head = el('div', 'session-head');
    head.appendChild(el('span', 'game-badge', game.toUpperCase()));
    if (state.focusedGame === game) head.appendChild(el('span', 'live-tag', 'active tab'));
    const net = typeof stats.net === 'number' ? stats.net : null;
    head.appendChild(
      el('span', 'session-net ' + (net > 0 ? 'pos' : net < 0 ? 'neg' : 'dim'), fmtMoney(net))
    );
    box.appendChild(head);

    const grid = el('div', 'session-grid');
    const cells = [
      ['rounds', String(stats.rounds ?? 0), ''],
      ['win rate', stats.winRate == null ? '—' : stats.winRate + '%', ''],
      ['wagered', typeof stats.wagered === 'number' ? stats.wagered.toFixed(2) : String(stats.wagered ?? '—'), ''],
      ['streak', !stats.streak ? '—' : (stats.streak > 0 ? 'W' : 'L') + Math.abs(stats.streak),
        stats.streak > 0 ? 'pos' : stats.streak < 0 ? 'neg' : ''],
    ];
    for (const [label, value, cls] of cells) {
      const c = el('div', 'stat');
      c.appendChild(el('div', 'l', label));
      c.appendChild(el('div', 'v' + (cls ? ' ' + cls : ''), value));
      grid.appendChild(c);
    }
    box.appendChild(grid);
    main.appendChild(box);
  }

  if (state.archivedSummaries && state.archivedSummaries.length) {
    const div = el('div', 'archived');
    const label = el('div', 'label');
    label.appendChild(el('span', null, 'Past sessions'));
    label.appendChild(el('span', 'count', String(state.archivedSummaries.length)));
    div.appendChild(label);
    for (const s of state.archivedSummaries.slice(0, 8)) {
      const line = el('div', 'arch-row');
      line.appendChild(el('span', 'arch-game', s.game));
      line.appendChild(el('span', 'arch-meta num',
        s.rounds + ' rounds · ' + new Date(s.startedAt).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })));
      line.appendChild(el('span', 'arch-net ' + (s.net > 0 ? 'pos' : s.net < 0 ? 'neg' : 'dim'), fmtMoney(s.net)));
      div.appendChild(line);
    }
    main.appendChild(div);
  }
}

function refresh() {
  chrome.runtime.sendMessage({ type: 'SQX_GET_STATE' }).then((res) => {
    if (res && res.state) render(res.state);
  }).catch(() => {});
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === 'SQX_STATE') render(msg.state);
});

$('#export').addEventListener('click', async () => {
  const res = await chrome.runtime.sendMessage({ type: 'SQX_EXPORT' });
  const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'spinquest-sessions-' + new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-') + '.json';
  a.click();
  URL.revokeObjectURL(url);
});

$('#clear').addEventListener('click', async () => {
  if (!confirm('Delete all captured sessions and history?')) return;
  await chrome.runtime.sendMessage({ type: 'SQX_CLEAR_ALL' });
  refresh();
});

refresh();
