// node --test tests/test_bughunt_client_logic.mjs
// Bug hunt: the real static/app.js auto-act / pending / chain / hint logic,
// run in a vm with an inert DOM (tests/client_harness.cjs) and fake timers.
// Tests that document a bug are skipped with a "BUG:" reason (run with
// BUGHUNT_UNSKIP=1 to see them fail).
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test, mock, beforeEach, afterEach } from "node:test";

const require = createRequire(import.meta.url);
const { loadClient, stateMsg, game } = require("./client_harness.cjs");
const A_PICKUP = 52, A_REVEAL = 54, A_END = 55, A_FACEDOWN = 67;
const bug = (reason) => (process.env.BUGHUNT_UNSKIP ? false : `BUG: ${reason}`);

let c, ws;
const actions = () => c.sent.filter((m) => m.type === "action").map((m) => m.action);
async function deliver(g, opts) {
  ws.onmessage({ data: JSON.stringify(stateMsg(g, opts)) });
  await flush();
}
async function flush() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}
async function advance(ms) {
  // Step in small increments so chained timers and microtasks interleave.
  for (let t = 0; t < ms; t += 10) { mock.timers.tick(10); await flush(); }
}

beforeEach(async () => {
  mock.timers.enable({ apis: ["setTimeout", "setInterval", "Date"], now: 1_000_000 });
  c = loadClient();
  c.T.S.code = "ABCDEF"; c.T.S.token = "tok"; c.T.S.lastGameNo = 1;
  c.T.connect();
  ws = c.sockets.at(-1);
  ws.onopen();
  c.sent.length = 0;
});
afterEach(() => mock.timers.reset());

const doneOnly = (over = {}) => game({ group_rank: 10, group_count: 1, live: [40], target: 10, legal: { end_group: true }, ...over });
const pickupOnly = (over = {}) => game({ legal: { pick_up: true }, ...over });

test("auto Done: sent once, about 500 ms after the state where it is the only move", async () => {
  await deliver(doneOnly());
  await advance(450);
  assert.deepEqual(actions(), []);
  await advance(100);
  assert.deepEqual(actions(), [A_END]);
  await advance(3000);
  assert.deepEqual(actions(), [A_END]);
});

test("auto Pick up: sent once, about 750 ms later", async () => {
  await deliver(pickupOnly());
  await advance(700);
  assert.deepEqual(actions(), []);
  await advance(100);
  assert.deepEqual(actions(), [A_PICKUP]);
});

for (const [label, legal] of [
  ["Done + another card of the group", { end_group: true, cards: [41] }],
  ["Pick up + Flip deck top", { pick_up: true, reveal: true }],
  ["Pick up + a playable card", { pick_up: false, cards: [44] }],
  ["face-down choice only", { face_down: [0] }],
  ["two face-down choices", { face_down: [0, 2] }],
  ["Flip deck top only", { reveal: true }],
]) {
  test(`no auto-act when the choice is: ${label}`, async () => {
    await deliver(game({ group_rank: legal.end_group ? 10 : null, group_count: legal.end_group ? 1 : 0, hand: [41, 44], legal }));
    await advance(2000);
    assert.deepEqual(actions(), []);
  });
}

test("no auto-act on someone else's turn, during a nine draw, or when the game is over", async () => {
  await deliver(doneOnly({ current: 1 }));
  await deliver(doneOnly({ nine_draw: true, live: [41] }));
  await deliver(doneOnly({ status: "over", current: null, live: [42] }));
  await advance(2000);
  assert.deepEqual(actions(), []);
});

test("a new state (turn passes) cancels a pending auto-act", async () => {
  await deliver(doneOnly());
  await advance(300);
  await deliver(doneOnly({ current: 1, live: [40, 41] }));
  await advance(2000);
  assert.deepEqual(actions(), []);
});

test("a presence broadcast with the same state keeps one timer and sends once", async () => {
  await deliver(doneOnly());
  await advance(200);
  await deliver(doneOnly());
  await advance(200);
  await deliver(doneOnly());
  await advance(2000);
  assert.deepEqual(actions(), [A_END]);
});

test("disconnect cancels; after reconnect the same state auto-acts once", async () => {
  await deliver(doneOnly());
  await advance(300);
  ws.onclose();
  await advance(600);
  assert.deepEqual(actions(), []);
  // reconnect timer fires and opens a new socket
  await advance(1500);
  ws = c.sockets.at(-1);
  assert.notEqual(ws, c.sockets[0]);
  ws.onopen();
  await deliver(doneOnly());
  await advance(600);
  assert.deepEqual(actions(), [A_END]);
});

test("leaving the room cancels a pending auto-act", async () => {
  await deliver(doneOnly());
  await advance(300);
  c.T.leaveRoom();
  await advance(2000);
  assert.deepEqual(actions(), []);
});

test("an error reply cancels and nothing is re-sent", async () => {
  await deliver(doneOnly());
  await advance(600);
  assert.deepEqual(actions(), [A_END]);
  ws.onmessage({ data: JSON.stringify({ type: "error", message: "Illegal move" }) });
  await advance(3000);
  assert.deepEqual(actions(), [A_END]);
});

test("the click handler path never sends an action that is not in the server's legal list", async () => {
  await deliver(game({ hand: [44, 45], legal: { cards: [44], pick_up: false } }));
  for (const a of [45, 30, A_PICKUP, A_REVEAL, A_END, A_FACEDOWN, A_FACEDOWN + 2, 53]) c.T.act(a);
  c.T.act(44);
  assert.deepEqual(actions(), [44]);
});

test(
  "slow server: after the 8 s pending timeout, a same-state broadcast must not send Done a second time",
  async () => {
    await deliver(doneOnly());
    await advance(600);
    assert.deepEqual(actions(), [A_END]);
    await advance(8100); // no reply yet: pendingAction released
    await deliver(doneOnly()); // e.g. someone reconnects: presence broadcast, same game state
    await advance(1000);
    assert.deepEqual(actions(), [A_END], "Done sent twice for one state");
  },
);

test(
  "double-click 'play every card of this rank' still finishes in a hidden tab",
  async () => {
    // Hand: two Js (32, 33). Double-click 32: client sends 32 and sets autoGroup.
    await deliver(game({ hand: [32, 33], live: [20], target: 5, legal: { cards: [32, 33] } }));
    c.T.S.autoGroup = { rank: 8, queue: [33] };
    c.T.act(32);
    assert.deepEqual(actions(), [32]);
    c.setHidden(true);
    // Reply: 32 on the pile, group open, 33 still playable, Done legal.
    await deliver(game({ hand: [33], live: [20, 32], target: 8, group_rank: 8, group_count: 1, legal: { cards: [33], end_group: true } }), { events: [{ kind: "play", player: 0, card: 32, source: "hand" }] });
    await advance(200);
    assert.deepEqual(actions(), [32, 33], "chain did not continue");
    await deliver(game({ hand: [], live: [20, 32, 33], target: 8, group_rank: 8, group_count: 2, legal: { end_group: true } }), { events: [{ kind: "play", player: 0, card: 33, source: "hand" }] });
    await advance(1000);
    assert.deepEqual(actions(), [32, 33, A_END], "group never closed");
  },
);

test("double-click chain in a visible tab plays the rest of the rank and then Done (control)", async () => {
  await deliver(game({ hand: [32, 33], live: [20], target: 5, legal: { cards: [32, 33] } }));
  c.T.S.autoGroup = { rank: 8, queue: [33] };
  c.T.act(32);
  await deliver(game({ hand: [33], live: [20, 32], target: 8, group_rank: 8, group_count: 1, legal: { cards: [33], end_group: true } }), { events: [{ kind: "play", player: 0, card: 32, source: "hand" }] });
  await advance(3000);
  await deliver(game({ hand: [], live: [20, 32, 33], target: 8, group_rank: 8, group_count: 2, legal: { end_group: true } }), { events: [{ kind: "play", player: 0, card: 33, source: "hand" }] });
  await advance(3000);
  assert.deepEqual(actions(), [32, 33, A_END]);
});

test(
  "a hint that arrives after the state moved on is not shown",
  async () => {
    const toasts = [];
    c.T.setToast((html, cls) => toasts.push([html, cls]));
    await deliver(game({ hand: [44, 45], legal: { cards: [44, 45] } }));
    c.T.send({ type: "hint" });
    await deliver(game({ current: 1, hand: [45], live: [20, 44] })); // turn moved on
    ws.onmessage({ data: JSON.stringify({ type: "hint", action: 44 }) });
    assert.deepEqual(toasts.filter(([, cls]) => cls === "hint"), []);
  },
);

// ---------------------------------------------------------------- fixes
// Follow-ups for the fixed bugs above: the same failure modes on paths the
// original tests did not reach.

const chainStart = () => game({ hand: [32, 33], live: [20], target: 5, legal: { cards: [32, 33] } });
const chainMid = () => game({ hand: [33], live: [20, 32], target: 8, group_rank: 8, group_count: 1, legal: { cards: [33], end_group: true } });
const chainEnd = () => game({ hand: [], live: [20, 32, 33], target: 8, group_rank: 8, group_count: 2, legal: { end_group: true } });

test("double-click chain finishes when 4 or more messages arrive at once (backlog)", async () => {
  await deliver(chainStart());
  c.T.S.autoGroup = { rank: 8, queue: [33] };
  c.T.act(32);
  // The reply (with its play event) arrives with four presence broadcasts of
  // the same state behind it, so pump() handles it in fast mode (no animation).
  const ev = { events: [{ kind: "play", player: 0, card: 32, source: "hand" }] };
  c.T.S.queue.push(stateMsg(chainMid(), ev), ...[1, 2, 3, 4].map(() => stateMsg(chainMid())));
  let animated = 0;
  c.T.setAnimateEvents(async () => { animated++; });
  c.T.pump();
  await advance(3000);
  assert.equal(animated, 0, "expected the backlog to skip animation");
  assert.deepEqual(actions(), [32, 33]);
  await deliver(chainEnd());
  await advance(3000);
  assert.deepEqual(actions(), [32, 33, A_END]);
});

test("a chain card is not sent twice after the 8 s pending timeout and a same-state broadcast", async () => {
  await deliver(chainStart());
  c.T.S.autoGroup = { rank: 8, queue: [33] };
  c.T.act(32);
  await deliver(chainMid());
  await advance(200);
  assert.deepEqual(actions(), [32, 33]);
  await advance(8100); // no reply: pendingAction released
  await deliver(chainMid());
  await advance(2000);
  assert.deepEqual(actions(), [32, 33]);
});

test("a manual Done, then the 8 s timeout and a same-state broadcast: no second, automatic Done", async () => {
  await deliver(doneOnly());
  await advance(200);
  c.T.act(A_END); // the player taps Done before auto-Done fires
  await advance(8200);
  await deliver(doneOnly());
  await advance(1500);
  assert.deepEqual(actions(), [A_END]);
});

test("left-over chain state for another rank never blocks auto-Done", async () => {
  c.T.S.autoGroup = { rank: 3, queue: [12] }; // stale: a Q chain from earlier
  await deliver(doneOnly());
  await advance(600);
  assert.deepEqual(actions(), [A_END]);
  assert.equal(c.T.S.autoGroup, null);
});

test("an error reply drops the chain, so auto-Done is not blocked afterwards", async () => {
  await deliver(chainStart());
  c.T.S.autoGroup = { rank: 8, queue: [33] };
  c.T.act(32);
  ws.onmessage({ data: JSON.stringify({ type: "error", message: "Illegal move" }) });
  assert.equal(c.T.S.autoGroup, null);
});

test("after a reconnect the same state may auto-act once more (the first send may be lost)", async () => {
  await deliver(doneOnly());
  await advance(600);
  assert.deepEqual(actions(), [A_END]);
  ws.onclose();
  await advance(1500);
  ws = c.sockets.at(-1);
  ws.onopen();
  await deliver(doneOnly());
  await advance(600);
  await deliver(doneOnly());
  await advance(1000);
  assert.deepEqual(actions(), [A_END, A_END]);
});

test("a hint is shown when it matches the current state (control)", async () => {
  const toasts = [];
  c.T.setToast((html, cls) => toasts.push([html, cls]));
  await deliver(game({ hand: [44, 45], legal: { cards: [44, 45] } }));
  c.T.send({ type: "hint" });
  ws.onmessage({ data: JSON.stringify({ type: "hint", action: 44 }) });
  assert.equal(toasts.filter(([, cls]) => cls === "hint").length, 1);
});

test("a hint is not shown while a newer state is still animating, or when it names an illegal move", async () => {
  const toasts = [];
  c.T.setToast((html, cls) => toasts.push([html, cls]));
  await deliver(game({ hand: [44, 45], legal: { cards: [44, 45] } }));
  c.T.send({ type: "hint" });
  ws.onmessage({ data: JSON.stringify({ type: "hint", action: 30 }) }); // not legal here
  c.T.setAnimateEvents(() => new Promise((r) => setTimeout(r, 500)));
  // Visible tab: the gate is the #game screen being active, which the stub
  // reports, so this message animates and keeps the pump busy.
  ws.onmessage({ data: JSON.stringify(stateMsg(game({ current: 1, hand: [45], live: [20, 44] }), { events: [{ kind: "play", player: 0, card: 44, source: "hand" }] })) });
  await flush();
  ws.onmessage({ data: JSON.stringify({ type: "hint", action: 44 }) });
  await advance(1000);
  assert.deepEqual(toasts.filter(([, cls]) => cls === "hint"), []);
});

const fixing = (meOver = {}, otherOver = {}) => {
  const g = game({ status: "fixing", phase: "FIXING", current: null, legal: {} });
  g.players[0] = { ...g.players[0], ready: false, ...meOver };
  g.players[1] = { ...g.players[1], ready: false, ...otherOver };
  return g;
};
const readies = () => c.sent.filter((m) => m.type === "fix" && m.op === "done").length;

test("Ready is sent once even if another player's fix re-renders the table before the reply", async () => {
  await deliver(fixing());
  assert.equal(c.T.sendReady(), true);
  await deliver(fixing({}, { face_up: [[2], [1], [3]] })); // the other player swaps
  assert.equal(c.T.sendReady(), false);
  assert.equal(readies(), 1);
  await deliver(fixing({ ready: true }));
  assert.equal(c.T.sendReady(), false);
  assert.equal(readies(), 1);
});

test("Ready: an error reply or a reconnect releases it; an empty face-up slot blocks it", async () => {
  await deliver(fixing({ face_up: [[30, 34], [], [32]] }));
  assert.equal(c.T.sendReady(), false);
  await deliver(fixing());
  assert.equal(c.T.sendReady(), true);
  ws.onmessage({ data: JSON.stringify({ type: "error", message: "Fill every face-up slot" }) });
  assert.equal(c.T.sendReady(), true);
  ws.onclose();
  await advance(1500);
  ws = c.sockets.at(-1);
  ws.onopen();
  await deliver(fixing());
  assert.equal(c.T.sendReady(), true);
  assert.equal(readies(), 3);
});
