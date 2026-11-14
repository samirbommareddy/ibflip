// node --test tests/test_result_outcome.mjs
// Results screen (static/app.js resultOutcome / showResult): the title, the
// line under it, the sound and confetti must agree, for 2 to 5 players and
// every way a game can end. Finished games are placed the way the engine
// does it (engine.py _finish_player): legal finishers take the top free
// place, illegal finishers the bottom free place, an 8s flipper takes last
// place and earlier illegal/8s finishers move up one; once one player is
// left, they get the remaining place.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const { loadClient } = require("./client_harness.cjs");

// Every finishing order, each finisher "legal", "illegal" or "eights".
function* endings(n) {
  const seats = [...Array(n).keys()];
  function* orders(left) {
    if (left.length === 1) { yield []; return; }
    for (const i of left) for (const rest of orders(left.filter((x) => x !== i))) yield [i, ...rest];
  }
  for (const order of orders(seats)) {
    const finishers = order.slice(0, n - 1);
    for (let mask = 0; mask < 3 ** finishers.length; mask++) {
      const kinds = finishers.map((_, k) => ["legal", "illegal", "eights"][Math.floor(mask / 3 ** k) % 3]);
      yield place(n, finishers, kinds);
    }
  }
}
function place(n, finishers, kinds) {
  const players = Array.from({ length: n }, () => ({ place: null, finish: null, face_up: [[], [], []], hand: [] }));
  const free = () => { const taken = new Set(players.map((p) => p.place)); return [...Array(n).keys()].map((k) => k + 1).filter((k) => !taken.has(k)); };
  finishers.forEach((i, k) => {
    const f = kinds[k];
    players[i].finish = f;
    if (f === "legal") players[i].place = free()[0];
    else if (f === "illegal") players[i].place = free().at(-1);
    else {
      for (const p of players) if (p.place !== null && (p.finish === "illegal" || p.finish === "eights")) p.place -= 1;
      players[i].place = n;
    }
  });
  const left = players.findIndex((p) => p.place === null);
  players[left].place = free()[0];
  assert.deepEqual(players.map((p) => p.place).sort((x, y) => x - y), [...Array(n).keys()].map((k) => k + 1));
  const winner = players.findIndex((p) => p.place === 1), loser = players.findIndex((p) => p.place === n);
  return { status: "over", winner, loser, players };
}

test("results: title, text, sound and confetti agree for every finish at 2 to 5 players", () => {
  const c = loadClient();
  let cases = 0;
  for (let n = 2; n <= 5; n++) {
    c.T.S.room = { host: 0, seats: Array.from({ length: n }, (_, i) => ({ name: `P${i}`, wins: 0 })) };
    const seen = new Set();
    for (const g of endings(n)) {
      for (let seat = 0; seat < n; seat++) {
        const key = JSON.stringify([g.players.map((p) => [p.place, p.finish]), seat]);
        if (seen.has(key)) continue;
        seen.add(key); cases++;
        c.T.S.seat = seat; c.T.S.game = g;
        const { title, text, mood } = c.T.resultOutcome(g);
        const me = g.players[seat], f = me.finish;
        const ctx = `${n}p seat ${seat}: ${key} -> ${title} / ${text} / ${mood}`;
        // Win treatment (win sound + confetti) exactly for 1st place, under "You win".
        assert.equal(mood === "win", me.place === 1, ctx);
        assert.equal(title === "You win", me.place === 1, ctx);
        // Losing sound for last place or a bad finish; otherwise no sound.
        assert.equal(mood === "lose", me.place === n || f === "illegal" || f === "eights", ctx);
        if (me.place === n) assert.equal(title, "Last place", ctx);
        else if (me.place !== 1) assert.equal(title, `You finished ${me.place}${["", "st", "nd", "rd"][me.place] || "th"}`, ctx);
        // The line under the title tells the same story.
        assert.equal(/finished first, legally/.test(text), me.place === 1 && f === "legal", ctx);
        if (f === "illegal") assert.equal(text, "You finished illegally.", ctx);
        if (f === "eights") assert.equal(text, "You flipped the 8s.", ctx);
        if (me.place === 1 && f === null) assert.match(text, /finished illegally|flipped the 8s/, ctx);
        if (me.place !== 1 && f !== "illegal" && f !== "eights") assert.doesNotMatch(text, /You (finished illegally|flipped)/, ctx);
        // Plain copy.
        assert.doesNotMatch(title + text, /[—–·!]/, ctx);
        assert.ok(text.length > 0, ctx);
      }
    }
  }
  assert.ok(cases > 1000, `only ${cases} cases`);
});

test("results: the last player left after illegal finishers gets a plain, correct line", () => {
  const c = loadClient();
  const mk = (finishes, places) => ({ status: "over", winner: 0, loser: null, players: finishes.map((f, i) => ({ finish: f, place: places[i], face_up: [[], [], []], hand: [] })) });
  const cases = [
    [mk([null, "illegal"], [1, 2]), "P1 finished illegally."],
    [mk([null, "eights"], [1, 2]), "P1 flipped the 8s."],
    [mk([null, "illegal", "illegal"], [1, 3, 2]), "Everyone else finished illegally."],
    [mk([null, "illegal", "eights"], [1, 2, 3]), "Everyone else finished illegally or flipped the 8s."],
  ];
  for (const [g, text] of cases) {
    c.T.S.room = { host: 0, seats: g.players.map((_, i) => ({ name: `P${i}`, wins: 0 })) };
    c.T.S.seat = 0; c.T.S.game = g;
    assert.deepEqual({ ...c.T.resultOutcome(g) }, { title: "You win", text, mood: "win" });
  }
});

test("results text uses plain names (it is set as text, so no HTML escaping)", () => {
  const c = loadClient();
  const g = { status: "over", winner: 1, loser: 2, players: [{ place: 2, finish: null }, { place: 1, finish: "legal" }, { place: 3, finish: "illegal" }].map((p) => ({ ...p, face_up: [[], [], []], hand: [] })) };
  c.T.S.room = { host: 0, seats: [{ name: "Me" }, { name: "Tom & Jo" }, { name: "Bot" }] };
  c.T.S.seat = 0; c.T.S.game = g;
  assert.deepEqual({ ...c.T.resultOutcome(g) }, { title: "You finished 2nd", text: "Tom & Jo finished 1st.", mood: "even" });
});
