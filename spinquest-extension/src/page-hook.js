// Runs in the page's MAIN world at document_start. Hooks fetch, XHR, and
// WebSocket so every JSON payload the game exchanges with its backend is
// mirrored to the content script via window.postMessage. Capture only —
// nothing here alters requests, responses, or timing.
(() => {
  'use strict';

  if (window.__SQX_HOOKED__) return;
  window.__SQX_HOOKED__ = true;

  const CHANNEL = 'sqx-capture';
  const MAX_BODY_BYTES = 64 * 1024; // ignore huge payloads (assets, blobs)

  const post = (kind, url, direction, body) => {
    try {
      window.postMessage(
        { channel: CHANNEL, kind, url: String(url || ''), direction, body, ts: Date.now() },
        window.location.origin
      );
    } catch {
      // body not structured-cloneable — drop it
    }
  };

  const parseMaybeJson = (text) => {
    if (typeof text !== 'string' || !text.length || text.length > MAX_BODY_BYTES) return undefined;
    const c = text[0];
    if (c !== '{' && c !== '[') return undefined;
    try {
      return JSON.parse(text);
    } catch {
      return undefined;
    }
  };

  // --- fetch ---------------------------------------------------------------
  const origFetch = window.fetch;
  window.fetch = function (...args) {
    const req = args[0];
    const url = typeof req === 'string' ? req : (req && req.url) || '';
    const init = args[1] || {};

    const reqBody = typeof init.body === 'string' ? parseMaybeJson(init.body) : undefined;
    if (reqBody !== undefined) post('fetch', url, 'out', reqBody);

    return origFetch.apply(this, args).then((res) => {
      try {
        const ct = res.headers.get('content-type') || '';
        if (ct.includes('json')) {
          res
            .clone()
            .text()
            .then((text) => {
              const body = parseMaybeJson(text);
              if (body !== undefined) post('fetch', res.url || url, 'in', body);
            })
            .catch(() => {});
        }
      } catch {
        /* never break the page's own fetch */
      }
      return res;
    });
  };

  // --- XMLHttpRequest ------------------------------------------------------
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__sqxUrl = String(url || '');
    return origOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.send = function (body) {
    const url = this.__sqxUrl || '';
    const reqBody = typeof body === 'string' ? parseMaybeJson(body) : undefined;
    if (reqBody !== undefined) post('xhr', url, 'out', reqBody);

    this.addEventListener('load', () => {
      try {
        if (this.responseType === '' || this.responseType === 'text') {
          const resBody = parseMaybeJson(this.responseText);
          if (resBody !== undefined) post('xhr', url, 'in', resBody);
        } else if (this.responseType === 'json' && this.response != null) {
          post('xhr', url, 'in', this.response);
        }
      } catch {
        /* ignore */
      }
    });

    return origSend.call(this, body);
  };

  // --- WebSocket -----------------------------------------------------------
  const OrigWebSocket = window.WebSocket;
  window.WebSocket = function (url, protocols) {
    const ws =
      protocols === undefined ? new OrigWebSocket(url) : new OrigWebSocket(url, protocols);

    ws.addEventListener('message', (evt) => {
      const body = parseMaybeJson(evt.data);
      if (body !== undefined) post('ws', url, 'in', body);
    });

    const origWsSend = ws.send.bind(ws);
    ws.send = (data) => {
      const body = parseMaybeJson(data);
      if (body !== undefined) post('ws', url, 'out', body);
      return origWsSend(data);
    };

    return ws;
  };
  window.WebSocket.prototype = OrigWebSocket.prototype;
  Object.setPrototypeOf(window.WebSocket, OrigWebSocket);
})();
