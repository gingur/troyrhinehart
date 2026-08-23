'use strict';

const $ = (sel) => document.querySelector(sel);

const fmtMoney = (n) => {
  if (typeof n !== 'number') return '—';
  return (n > 0 ? '+' : '') + n.toFixed(2);
};

function render(state) {
  const main = $('#content');
  main.textContent = '';

  const games = Object.keys(state.active || {});
  if (!games.length) {
    const p = document.createElement('p');
    p.className = 'dim';
    p.textContent = 'No active sessions. Open a game on spinquest.com and play a round.';
    main.appendChild(p);
  }

  for (const game of games) {
    const s = state.active[game];
    const stats = s.stats || {};
    const box = document.createElement('div');
    box.className = 'session';

    const h2 = document.createElement('h2');
    h2.textContent = game.toUpperCase() + (state.focusedGame === game ? ' · active tab' : '');
    box.appendChild(h2);

    const rows = [
      ['rounds', stats.rounds ?? 0],
      ['win rate', stats.winRate == null ? '—' : stats.winRate + '%'],
      ['wagered', (stats.wagered ?? 0).toFixed ? stats.wagered.toFixed(2) : stats.wagered],
      ['net', fmtMoney(stats.net)],
      ['streak', !stats.streak ? '—' : (stats.streak > 0 ? 'W' : 'L') + Math.abs(stats.streak)],
    ];
    for (const [label, value] of rows) {
      const line = document.createElement('div');
      line.className = 'line';
      const l = document.createElement('span');
      l.className = 'dim';
      l.textContent = label;
      const v = document.createElement('span');
      v.textContent = String(value);
      if (label === 'net' && typeof stats.net === 'number' && stats.net !== 0) {
        v.className = stats.net > 0 ? 'pos' : 'neg';
      }
      line.append(l, v);
      box.appendChild(line);
    }
    main.appendChild(box);
  }

  if (state.archivedSummaries && state.archivedSummaries.length) {
    const div = document.createElement('div');
    div.className = 'archived';
    const title = document.createElement('div');
    title.className = 'dim';
    title.textContent = 'Past sessions:';
    div.appendChild(title);
    for (const s of state.archivedSummaries.slice(0, 8)) {
      const line = document.createElement('div');
      line.className = 'line';
      const l = document.createElement('span');
      l.textContent = `${s.game} · ${s.rounds} rounds · ${new Date(s.startedAt).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`;
      const v = document.createElement('span');
      v.textContent = fmtMoney(s.net);
      v.className = s.net > 0 ? 'pos' : s.net < 0 ? 'neg' : 'dim';
      line.append(l, v);
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
