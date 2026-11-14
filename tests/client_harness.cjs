// Loads the real static/app.js in a Node vm with an inert DOM stub so its
// state/timer logic (act, apply, pump, scheduleAutoAct, socket handlers...)
// can be tested without a browser. Not a test file itself (no .mjs suffix).
//
//   const { loadClient } = require("./client_harness.cjs");
//   const c = loadClient();          // c.T exposes S and the functions
//   c.sent                           // JSON messages sent on the fake socket
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const APP_JS = path.join(__dirname, "..", "static", "app.js");

// A do-nothing object: any property is another stub, calling it returns a
// stub, it stringifies to "" and is not a thenable (so `await stub` resolves).
function makeStub(name = "stub") {
  const target = function () {};
  const handler = {
    get(_t, prop) {
      if (prop === Symbol.toPrimitive) return () => "";
      if (prop === Symbol.iterator) return function* () {};
      if (prop === "then") return undefined;
      if (prop === "length") return 0;
      if (prop === "matches") return false;
      if (prop === "hidden") return false;
      if (prop === "offsetWidth" || prop === "clientWidth" || prop === "offsetLeft") return 0;
      if (prop === "dataset") return {};
      if (prop === "classList") return { add() {}, remove() {}, toggle() {}, contains: (c) => c === "active" };
      if (prop === "children") return [];
      return proxy;
    },
    set() { return true; },
    apply() { return proxy; },
    construct() { return proxy; },
  };
  const proxy = new Proxy(target, handler);
  return proxy;
}

function loadClient({ hidden = false } = {}) {
  const sent = [];
  const sockets = [];
  class FakeWebSocket {
    constructor(url) { this.url = url; this.readyState = 1; sockets.push(this); }
    send(text) { sent.push(JSON.parse(text)); }
    close() { this.readyState = 3; }
  }
  const stub = makeStub();
  const documentStub = new Proxy({}, {
    get(_t, prop) {
      if (prop === "hidden") return ctx.__hidden;
      if (prop === "querySelector") return () => stub;
      if (prop === "querySelectorAll") return () => [];
      if (prop === "getAnimations") return () => [];
      return stub;
    },
  });
  const ctx = {
    __hidden: hidden,
    console,
    // Late-bound so node:test mock.timers (which patches globalThis) applies.
    setTimeout: (...a) => globalThis.setTimeout(...a),
    clearTimeout: (...a) => globalThis.clearTimeout(...a),
    setInterval: (...a) => globalThis.setInterval(...a),
    clearInterval: (...a) => globalThis.clearInterval(...a),
    Date: { now: () => globalThis.Date.now() },
    AudioContext: function () { return stub; },
    DOMRect: function (x = 0, y = 0, width = 0, height = 0) { return { x, y, width, height, left: x, top: y, right: x + width, bottom: y + height }; },
    Math, JSON, Promise, Number, String, Array, Object, Set, Map, RegExp, Error, Symbol,
    encodeURIComponent, URLSearchParams,
    WebSocket: FakeWebSocket,
    localStorage: { getItem: (k) => (k === "ibflip:sound" ? "off" : null), setItem() {}, removeItem() {} },
    history: { replaceState() {} },
    location: { hostname: "example.test", port: "", origin: "http://example.test", protocol: "http:", search: "", pathname: "/" },
    matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => 0,
    cancelAnimationFrame() {},
    fetch: () => Promise.resolve(stub),
    navigator: stub,
  };
  ctx.window = ctx;
  ctx.globalThis = ctx;
  ctx.document = documentStub;
  ctx.IBFLIP_API_BASE = "http://api.test";
  let source = fs.readFileSync(APP_JS, "utf8");
  if (!/\nboot\(\);\s*$/.test(source)) throw new Error("app.js no longer ends with boot();");
  source = source.replace(/\nboot\(\);\s*$/, "\n");
  source += `
globalThis.__T = { S, act, send, isLegalNow, soleLegalAction, autoActFor, scheduleAutoAct, cancelAutoAct,
  gameSig, apply, pump, connect, leaveRoom, showHint, AUTO_ACT_DELAY,
  sendReady, continueAutoGroup, resultOutcome,
  setAnimateEvents(fn) { animateEvents = fn; },
  setRender(fn) { renderGame = fn; },
  setToast(fn) { toast = fn; } };
`;
  // animateEvents / renderGame are function declarations: reassignable.
  vm.createContext(ctx);
  vm.runInContext(source, ctx, { filename: "app.js" });
  const T = ctx.__T;
  return { T, sent, sockets, ctx, setHidden: (v) => { ctx.__hidden = v; } };
}

// A minimal "state" message as the server sends it.
function stateMsg(game, { seat = 0, gameNo = 1, events = [] } = {}) {
  return {
    type: "state",
    you: seat,
    events,
    room: { code: "ABCDEF", status: game.status, host: 0, seats: [{ name: "Me" }, { name: "Bot" }], game_no: gameNo, hard_available: true },
    game,
  };
}

function game(over = {}) {
  const base = {
    status: "playing", phase: "MIDDLE_GAME", current: 0, direction: 1, four_loop: false, nine_draw: false,
    winner: null, loser: null, live: [20], ace_one: [], target: 5, discard_count: 0, discard_top: null,
    draw_count: 0, start_card: null, group_rank: null, group_count: 0, hand: [44, 45],
    players: [
      { hand_count: 2, known: [], face_up: [[30], [31], [32]], face_down: [true, true, true], active: true, finish: null, place: null, ready: true },
      { hand_count: 3, known: [], face_up: [[1], [2], [3]], face_down: [true, true, true], active: true, finish: null, place: null, ready: true },
    ],
    legal: { cards: [], pick_up: false, reveal: false, end_group: false, face_down: [] },
    source: "hand",
  };
  return { ...base, ...over, legal: { ...base.legal, ...(over.legal || {}) } };
}

module.exports = { loadClient, stateMsg, game, makeStub };
