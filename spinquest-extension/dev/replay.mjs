#!/usr/bin/env node
// Adversarial payload corpus runner. Feeds every dev/payloads/*.json through
// the REAL capture pipeline — src/page-hook.js for transport-level steps and
// src/lib + src/adapters/* + src/content.js for normalization — loaded
// unmodified into vm sandboxes, then asserts the normalized events emitted
// toward the background. No framework:
//   node dev/replay.mjs            # run the whole corpus
//   node dev/replay.mjs crash      # only files whose name contains "crash"
//
// Payload file shape:
//   {
//     "game": "crash",              // the game page the tab is on (null = lobby)
//     "steps": [                    // delivered in order; "repeat": N replays a step
//       { "transport": "direct", "kind": "fetch", "url": "...", "direction": "in",
//         "body": {...}, "ts": 1000 },
//       { "transport": "ws",    "url": "...", "frame": "42[...]",
//         "binary": "arraybuffer" | "blob" (optional),
//         "subclass": true (optional — construct via `class X extends WebSocket`) },
//       { "transport": "xhr",   "url": "...", "responseType": "json"|"text"|"arraybuffer"|"blob",
//         "response": {...} | "responseText": "..." | "text": "...",
//         "responseTextThrows": true (optional) },
//       { "transport": "fetch", "url": "...", "contentType": "application/json"|null,
//         "text": "...", "cloneThrows": true (optional),
//         "stream": true (optional — serve text as a chunked body stream with
//         NO content-length, exercising the hook's capped streaming reader) },
//       any step: "fill": N replaces every "@FILL@" in its text/frame/
//         responseText/response with N repeated 'a's (oversize tests without
//         megabyte fixture files),
//       { "transport": "spoof", "data": <raw window message, hostile page sim> }
//     ],
//     "expected": [                 // SQX_GAME_EVENT messages, in order
//       { "game": "crash", "event": { "type": "round", "round": { ... } } }
//     ]
//   }
// Matching is subset-based: only keys present in an expected object are
// asserted; "*" matches any defined value; "__absent__" asserts a key is NOT
// set. Event COUNT must match exactly — extra or missing events fail.
'use strict';

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const devDir = dirname(fileURLToPath(import.meta.url));
const srcDir = join(devDir, '..', 'src');
const payloadDir = join(devDir, 'payloads');

const PIPELINE_FILES = [
  'lib/util.js',
  'lib/normalize.js',
  'adapters/plinko.js',
  'adapters/mines.js',
  'adapters/crash.js',
  'adapters/blackjack.js',
  'adapters/roulette.js',
  'adapters/generic.js',
  'content.js',
];

const sources = new Map();
const src = (f) => {
  if (!sources.has(f)) sources.set(f, readFileSync(join(srcDir, f), 'utf8'));
  return sources.get(f);
};

const tick = () => new Promise((r) => setTimeout(r, 0));

function baseSandbox() {
  const sb = {
    Math, JSON, Date, Number, Array, Object, String, Boolean, RegExp, Set, Map,
    Promise, Error, TypeError, isFinite, isNaN, parseFloat, parseInt, console,
    TextDecoder, ArrayBuffer, Uint8Array, Blob, setTimeout, clearTimeout,
    structuredClone, Proxy, Reflect,
  };
  sb.window = sb;
  sb.globalThis = sb;
  return sb;
}

// --- content-script pipeline (util + normalize + adapters + content.js) ------

function makePipeline(game) {
  const sb = baseSandbox();
  const sent = [];
  const listeners = { message: [] };
  sb.location = {
    pathname: game ? '/games/' + game : '/',
    search: '',
    href: 'https://spinquest.com' + (game ? '/games/' + game : '/'),
    origin: 'https://spinquest.com',
  };
  sb.document = { referrer: '' };
  sb.addEventListener = (type, fn) => {
    (listeners[type] || (listeners[type] = [])).push(fn);
  };
  sb.setInterval = () => 0;
  sb.chrome = {
    runtime: {
      sendMessage: (msg) => {
        sent.push(structuredClone(msg));
        return Promise.resolve();
      },
    },
  };
  vm.createContext(sb);
  // Inside the context, `window` resolves to the contextified global (a
  // different identity from `sb`) — messages must carry THAT as their source
  // or content.js's `msg.source !== window` guard rejects them.
  const innerWindow = vm.runInContext('window', sb);
  for (const f of PIPELINE_FILES) vm.runInContext(src(f), sb, { filename: f });
  return {
    window: sb,
    deliver(data) {
      for (const fn of listeners.message) fn({ source: innerWindow, data });
    },
    events: () => sent.filter((m) => m && m.type === 'SQX_GAME_EVENT'),
  };
}

// --- MAIN-world hook (page-hook.js over stubbed fetch/XHR/WebSocket) ---------

function makeHook(onPost) {
  const sb = baseSandbox();
  sb.location = { origin: 'https://spinquest.com' };
  sb.postMessage = (msg) => onPost(msg);

  let pendingResponse = null; // page-hook captures window.fetch at load time
  sb.fetch = () => Promise.resolve(pendingResponse);

  function FakeXHR() {
    this._ls = {};
  }
  FakeXHR.prototype.open = function () {};
  FakeXHR.prototype.send = function () {};
  FakeXHR.prototype.addEventListener = function (t, fn) {
    (this._ls[t] || (this._ls[t] = [])).push(fn);
  };
  sb.XMLHttpRequest = FakeXHR;

  function FakeWS(url) {
    this.url = url;
    this._ls = {};
  }
  FakeWS.prototype.addEventListener = function (t, fn) {
    (this._ls[t] || (this._ls[t] = [])).push(fn);
  };
  FakeWS.prototype.send = function () {};
  sb.WebSocket = FakeWS;

  vm.createContext(sb);
  vm.runInContext(src('page-hook.js'), sb, { filename: 'page-hook.js' });

  return {
    async fetchIn(url, step) {
      const res = {
        url,
        headers: {
          get: (k) => {
            const key = String(k).toLowerCase();
            if (key === 'content-type') return step.contentType ?? null;
            return null;
          },
        },
        clone() {
          if (step.cloneThrows) throw new TypeError('Response body is already used');
          return this;
        },
        text: async () => step.text,
      };
      if (step.stream) {
        // Chunked body, no content-length: the hook must stream with a cap
        // instead of buffering via .text().
        const enc = new TextEncoder();
        const CHUNK = 16 * 1024;
        let off = 0;
        let cancelled = false;
        res.body = {
          getReader: () => ({
            read: async () => {
              if (cancelled || off >= (step.text || '').length) return { done: true, value: undefined };
              const piece = step.text.slice(off, off + CHUNK);
              off += CHUNK;
              return { done: false, value: enc.encode(piece) };
            },
            cancel: async () => {
              cancelled = true;
            },
          }),
        };
        res.text = async () => {
          throw new Error('streamed fixture: .text() must not be used');
        };
      }
      pendingResponse = res;
      await sb.window.fetch(url);
      await tick();
    },
    async xhrIn(url, step) {
      const x = new sb.XMLHttpRequest();
      x.open('GET', url);
      x.send();
      x.responseType = step.responseType || '';
      if (step.responseTextThrows) {
        Object.defineProperty(x, 'responseText', {
          get() {
            throw new DOMException('responseText not accessible');
          },
        });
      } else if (step.responseText !== undefined) {
        x.responseText = step.responseText;
      }
      if (step.responseType === 'arraybuffer') {
        x.response = new TextEncoder().encode(step.text ?? '').buffer;
      } else if (step.responseType === 'blob') {
        x.response = new Blob([step.text ?? '']);
      } else if (step.response !== undefined) {
        x.response = step.response;
      }
      for (const fn of x._ls.load || []) fn.call(x);
      await tick();
    },
    async wsIn(url, step) {
      let data = step.frame;
      if (step.binary === 'arraybuffer') data = new TextEncoder().encode(step.frame).buffer;
      else if (step.binary === 'blob') data = new Blob([step.frame]);
      let ws;
      if (step.subclass) {
        // Games wrap the socket: `class GameWS extends WebSocket`. The hook
        // must preserve new.target so subclass prototypes survive.
        const Sub = vm.runInContext(
          '(class SQXReplayWS extends window.WebSocket { sqxTag() { return "sub"; } })',
          sb
        );
        ws = new Sub(url);
        if (typeof ws.sqxTag !== 'function' || ws.sqxTag() !== 'sub') {
          throw new Error('WebSocket subclass prototype lost through the hook');
        }
      } else {
        ws = new sb.WebSocket(url);
      }
      for (const fn of ws._ls.message || []) fn({ data });
      await tick();
    },
  };
}

// --- subset matching ---------------------------------------------------------

function subsetMatch(actual, expected, path) {
  if (expected === '*') {
    return actual === undefined ? `${path}: expected any value, got undefined` : null;
  }
  if (expected === '__absent__') {
    return actual === undefined ? null : `${path}: expected absent, got ${JSON.stringify(actual)}`;
  }
  if (expected === null || typeof expected !== 'object') {
    return Object.is(actual, expected)
      ? null
      : `${path}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual)) return `${path}: expected array, got ${JSON.stringify(actual)}`;
    if (actual.length !== expected.length) {
      return `${path}: expected ${expected.length} items, got ${actual.length}`;
    }
    for (let i = 0; i < expected.length; i++) {
      const err = subsetMatch(actual[i], expected[i], `${path}[${i}]`);
      if (err) return err;
    }
    return null;
  }
  if (actual === null || typeof actual !== 'object') {
    return `${path}: expected object, got ${JSON.stringify(actual)}`;
  }
  for (const k of Object.keys(expected)) {
    const err = subsetMatch(actual[k], expected[k], path ? path + '.' + k : k);
    if (err) return err;
  }
  return null;
}

// --- runner ------------------------------------------------------------------

/** Expand "@FILL@" markers to `step.fill` repeated 'a's — oversize-payload
 *  tests without committing megabytes of literal fixture. */
function expandFill(step) {
  if (typeof step.fill !== 'number' || step.fill <= 0) return step;
  const pad = 'a'.repeat(step.fill);
  const out = { ...step };
  for (const k of ['text', 'frame', 'responseText']) {
    if (typeof out[k] === 'string') out[k] = out[k].split('@FILL@').join(pad);
  }
  for (const k of ['response', 'data']) {
    if (out[k] !== undefined) {
      out[k] = JSON.parse(JSON.stringify(out[k]).split('@FILL@').join(pad));
    }
  }
  return out;
}

async function runStep(pipeline, hook, rawStep) {
  const step = expandFill(rawStep);
  const transport = step.transport || 'direct';
  if (transport === 'direct') {
    pipeline.deliver({
      channel: 'sqx-capture',
      kind: step.kind || 'fetch',
      url: step.url || '',
      direction: step.direction || 'in',
      body: step.body,
      ts: step.ts ?? Date.now(),
    });
  } else if (transport === 'ws') {
    await hook.wsIn(step.url || 'wss://spinquest.com/ws', step);
  } else if (transport === 'xhr') {
    await hook.xhrIn(step.url || 'https://spinquest.com/api', step);
  } else if (transport === 'fetch') {
    await hook.fetchIn(step.url || 'https://spinquest.com/api', step);
  } else if (transport === 'spoof') {
    pipeline.deliver(step.data);
  } else {
    throw new Error('unknown transport: ' + transport);
  }
  await tick();
}

async function runFile(file) {
  const spec = JSON.parse(readFileSync(join(payloadDir, file), 'utf8'));
  const pipeline = makePipeline(spec.game ?? null);
  const hook = makeHook((msg) => {
    let cloned;
    try {
      cloned = structuredClone(msg); // postMessage clones; enforce the same
    } catch {
      return;
    }
    pipeline.deliver(cloned);
  });

  for (const step of spec.steps || []) {
    const times = step.repeat || 1;
    for (let i = 0; i < times; i++) await runStep(pipeline, hook, step);
  }
  await tick();

  const actual = pipeline.events();
  const expected = spec.expected || [];
  if (actual.length !== expected.length) {
    throw new Error(
      `expected ${expected.length} events, got ${actual.length}:\n` +
        JSON.stringify(actual, null, 2)
    );
  }
  for (let i = 0; i < expected.length; i++) {
    const err = subsetMatch(actual[i], expected[i], `event[${i}]`);
    if (err) {
      throw new Error(err + '\nactual event: ' + JSON.stringify(actual[i], null, 2));
    }
  }
}

const filter = process.argv[2] || '';
const files = readdirSync(payloadDir)
  .filter((f) => f.endsWith('.json') && f.includes(filter))
  .sort();
if (!files.length) {
  console.error('no payload files match ' + JSON.stringify(filter));
  process.exit(1);
}

let passed = 0;
let failed = 0;
for (const file of files) {
  try {
    await runFile(file);
    passed++;
    console.log('  ok  ' + file);
  } catch (err) {
    failed++;
    console.error('FAIL  ' + file);
    console.error(String(err.message || err).replace(/^/gm, '      '));
  }
}
console.log(`\n${passed} passed, ${failed} failed (${files.length} payloads)`);
process.exit(failed ? 1 : 0);
