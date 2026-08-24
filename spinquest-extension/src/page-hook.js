// Runs in the page's MAIN world at document_start. Hooks fetch, XHR, and
// WebSocket so every JSON payload the game exchanges with its backend is
// mirrored to the content script via window.postMessage. Capture only —
// nothing here alters requests, responses, or timing — and NO code path may
// throw into the page: every hook body is individually guarded so a hostile
// or malformed payload degrades to "not captured", never to a broken game.
(() => {
  'use strict';

  try {
    if (window.__SQX_HOOKED__) return;
    window.__SQX_HOOKED__ = true;
  } catch {
    return; // frozen/hostile window — do nothing at all
  }

  const CHANNEL = 'sqx-capture';
  const MAX_BODY_BYTES = 64 * 1024; // ignore huge payloads (assets, blobs)

  const post = (kind, url, direction, body) => {
    try {
      // targetOrigin '/' = same origin; works even in frames whose
      // location.origin serializes to the string "null".
      window.postMessage(
        { channel: CHANNEL, kind, url: String(url || ''), direction, body, ts: Date.now() },
        '/'
      );
    } catch {
      // body not structured-cloneable — drop it
    }
  };

  // "42[...]", "42/game,[...]", "421[...]", "42/game,17[...]" — engine.io /
  // socket.io text frames: packet-type digits, an optional namespace, and an
  // optional ack id in front of the JSON payload.
  const SIO_PREFIX = /^\d{1,3}(?:\/[^,{[]*,)?\d{0,20}(?=[[{])/;

  const parseMaybeJson = (text) => {
    try {
      if (typeof text !== 'string' || !text.length || text.length > MAX_BODY_BYTES) return undefined;
      let t = text;
      const c = t[0];
      if (c !== '{' && c !== '[') {
        if (c < '0' || c > '9') return undefined;
        const m = SIO_PREFIX.exec(t);
        if (!m) return undefined;
        t = t.slice(m[0].length);
      }
      return JSON.parse(t);
    } catch {
      return undefined;
    }
  };

  const decodeBinary = (data) => {
    try {
      const isBuf = data instanceof ArrayBuffer;
      if (!isBuf && !(ArrayBuffer.isView && ArrayBuffer.isView(data))) return undefined;
      if (!data.byteLength || data.byteLength > MAX_BODY_BYTES) return undefined;
      if (typeof TextDecoder !== 'function') return undefined;
      return new TextDecoder('utf-8', { fatal: false }).decode(data);
    } catch {
      return undefined;
    }
  };

  // Parse-and-post for any transport payload: JSON text (socket.io prefixes
  // included), ArrayBuffer/TypedArray frames, and Blobs (read async).
  const capture = (kind, url, direction, data) => {
    try {
      if (typeof data === 'string') {
        const body = parseMaybeJson(data);
        if (body !== undefined) post(kind, url, direction, body);
        return;
      }
      if (!data || typeof data !== 'object') return;
      if (typeof Blob === 'function' && data instanceof Blob) {
        if (data.size && data.size <= MAX_BODY_BYTES && typeof data.text === 'function') {
          data
            .text()
            .then((t) => {
              const body = parseMaybeJson(t);
              if (body !== undefined) post(kind, url, direction, body);
            })
            .catch(() => {});
        }
        return;
      }
      const text = decodeBinary(data);
      if (text === undefined) return;
      const body = parseMaybeJson(text);
      if (body !== undefined) post(kind, url, direction, body);
    } catch {
      /* never break the page */
    }
  };

  // --- fetch ---------------------------------------------------------------

  // Read a CLONED Request/Response body as text with a hard byte cap. When
  // content-length is absent (chunked/streaming bodies), .text() would buffer
  // the whole thing — stream instead and cancel the moment the cap is
  // exceeded, so a multi-MB upload or SSE-ish response costs at most 64KB in
  // the tee branch. Resolves undefined for oversized/unreadable bodies.
  const readTextCapped = (cloned) => {
    try {
      const stream = cloned.body;
      if (stream && typeof stream.getReader === 'function' && typeof TextDecoder === 'function') {
        const reader = stream.getReader();
        const decoder = new TextDecoder('utf-8', { fatal: false });
        let text = '';
        const pump = () =>
          reader.read().then(({ done, value }) => {
            if (done) return text + decoder.decode();
            text += decoder.decode(value, { stream: true });
            if (text.length > MAX_BODY_BYTES) {
              try {
                const p = reader.cancel();
                if (p && typeof p.catch === 'function') p.catch(() => {});
              } catch {
                /* ignore */
              }
              return undefined;
            }
            return pump();
          });
        return pump().catch(() => undefined);
      }
    } catch {
      /* fall through to .text() */
    }
    try {
      return cloned
        .text()
        .then((t) => (typeof t === 'string' && t.length <= MAX_BODY_BYTES ? t : undefined))
        .catch(() => undefined);
    } catch {
      return Promise.resolve(undefined);
    }
  };

  const tapResponse = (res, reqUrl) => {
    try {
      if (!res || typeof res.clone !== 'function') return;
      let ct = '';
      let len = 0;
      try {
        if (res.headers && typeof res.headers.get === 'function') {
          ct = String(res.headers.get('content-type') || '').toLowerCase();
          len = Number(res.headers.get('content-length')) || 0;
        }
      } catch {
        /* hostile headers — sniff instead */
      }
      if (len > MAX_BODY_BYTES) return;
      // JSON APIs sometimes ship as text/plain or with no content-type at
      // all; sniff those. Declared non-JSON types (html, images, streams)
      // are skipped without touching the body.
      if (ct && !ct.includes('json') && !ct.includes('text/plain')) return;
      let clone;
      try {
        clone = res.clone(); // throws if the body is locked/disturbed
      } catch {
        return; // never touch the original body
      }
      const read = readTextCapped(clone);
      if (read && typeof read.then === 'function') {
        read
          .then((text) => {
            if (text !== undefined) capture('fetch', (res && res.url) || reqUrl, 'in', text);
          })
          .catch(() => {});
      }
    } catch {
      /* never break the page's own fetch */
    }
  };

  try {
    const origFetch = window.fetch;
    if (typeof origFetch === 'function') {
      window.fetch = function (...args) {
        try {
          const req = args[0];
          const init = args[1];
          const url =
            typeof req === 'string' ? req : req && typeof req.url === 'string' ? req.url : String(req || '');

          const initBody = init && init.body;
          if (typeof initBody === 'string') {
            capture('fetch', url, 'out', initBody);
          } else if (
            initBody === undefined &&
            typeof Request === 'function' &&
            req instanceof Request &&
            req.body &&
            typeof req.clone === 'function'
          ) {
            try {
              const read = readTextCapped(req.clone());
              if (read && typeof read.then === 'function') {
                read
                  .then((t) => {
                    if (t !== undefined) capture('fetch', url, 'out', t);
                  })
                  .catch(() => {});
              }
            } catch {
              /* body already used — skip */
            }
          }

          const promise = origFetch.apply(this, args);
          if (promise && typeof promise.then === 'function') {
            // The page gets its own promise back untouched. Observing it does
            // attach a no-op rejection handler, so a fire-and-forget fetch
            // failure no longer surfaces as an `unhandledrejection` event —
            // inherent to observing; awaited/`.catch`ed fetches see no change.
            promise.then((res) => tapResponse(res, url), () => {});
          }
          return promise;
        } catch {
          return origFetch.apply(this, args);
        }
      };
    }
  } catch {
    /* fetch not hookable here — XHR/WS hooks still apply */
  }

  // --- XMLHttpRequest ------------------------------------------------------

  try {
    const XHR = window.XMLHttpRequest;
    if (XHR && XHR.prototype) {
      const origOpen = XHR.prototype.open;
      const origSend = XHR.prototype.send;

      XHR.prototype.open = function (method, url, ...rest) {
        try {
          this.__sqxUrl = String(url || '');
        } catch {
          /* ignore */
        }
        return origOpen.call(this, method, url, ...rest);
      };

      XHR.prototype.send = function (body) {
        try {
          if (typeof body === 'string') capture('xhr', this.__sqxUrl || '', 'out', body);

          // Long-polling pages recycle ONE XHR object across many send()
          // calls — tap it once (own-property flag) or the load listeners
          // pile up unboundedly and every response is captured N times.
          if (this.__sqxTapped) return origSend.call(this, body);
          this.__sqxTapped = true;
          this.addEventListener('load', () => {
            try {
              const url = this.__sqxUrl || ''; // re-read: open() may have re-run
              const rt = this.responseType;
              if (rt === '' || rt === 'text') {
                let text;
                try {
                  text = this.responseText; // hostile getters can throw
                } catch {
                  text = undefined;
                }
                if (typeof text === 'string') capture('xhr', url, 'in', text);
              } else if (rt === 'json') {
                // Pre-gate on content-length when the server declares it, so
                // a 50MB JSON response is skipped WITHOUT paying a 50MB
                // stringify on the page's main thread first.
                try {
                  if (typeof this.getResponseHeader === 'function') {
                    const len = Number(this.getResponseHeader('content-length'));
                    if (Number.isFinite(len) && len > MAX_BODY_BYTES) return;
                  }
                } catch {
                  /* hostile headers — fall through to the stringify gate */
                }
                const res = this.response;
                if (res !== null && typeof res === 'object') {
                  // Same size gate as every other path: a multi-MB JSON
                  // response must not be structured-cloned across the bridge
                  // and hashed in the content script. Measuring costs one
                  // stringify (chunked/undeclared lengths only reach here),
                  // but only up to here — oversized bodies stop.
                  let raw;
                  try {
                    raw = JSON.stringify(res);
                  } catch {
                    raw = undefined; // circular/hostile — not postable anyway
                  }
                  if (typeof raw === 'string' && raw.length <= MAX_BODY_BYTES) {
                    post('xhr', url, 'in', res);
                  }
                }
              } else if (rt === 'arraybuffer' || rt === 'blob') {
                capture('xhr', url, 'in', this.response);
              }
              // 'document' and exotic responseTypes: ignored on purpose.
            } catch {
              /* ignore */
            }
          });
        } catch {
          /* capture failed — the request itself must still go out */
        }
        return origSend.call(this, body);
      };
    }
  } catch {
    /* XHR not hookable */
  }

  // --- WebSocket -----------------------------------------------------------

  try {
    const OrigWebSocket = window.WebSocket;
    if (typeof OrigWebSocket === 'function') {
      const tapSocket = (ws, url) => {
        try {
          ws.addEventListener('message', (evt) => {
            try {
              capture('ws', url, 'in', evt && evt.data);
            } catch {
              /* ignore */
            }
          });
          const origWsSend = ws.send;
          ws.send = function (data) {
            try {
              capture('ws', url, 'out', data);
            } catch {
              /* ignore */
            }
            return origWsSend.call(this, data);
          };
        } catch {
          /* socket still works uncaptured */
        }
      };
      // A Proxy keeps everything a constructor replacement tends to break:
      // statics (CONNECTING, OPEN, ...), instanceof, and — via new.target
      // forwarding — `class MyWS extends WebSocket` subclasses, whose
      // instances must get MyWS.prototype, not the base one.
      const HookedWebSocket = new Proxy(OrigWebSocket, {
        construct(target, args, newTarget) {
          // `new WebSocket(url, undefined)` must behave like the 1-arg form.
          if (args.length > 1 && args[args.length - 1] === undefined) {
            args = args.slice(0, -1);
          }
          const nt = newTarget === HookedWebSocket ? target : newTarget;
          const ws = Reflect.construct(target, args, nt);
          try {
            tapSocket(ws, args[0]);
          } catch {
            /* uncaptured, never broken */
          }
          return ws;
        },
      });
      window.WebSocket = HookedWebSocket;
    }
  } catch {
    /* WebSocket not hookable */
  }
})();
