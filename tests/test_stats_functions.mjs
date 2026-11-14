// node --test tests/test_stats_functions.mjs — the ingest allow-list (privacy backstop).
import assert from "node:assert/strict";
import { test } from "node:test";
import { validateBatch } from "../functions/_shared/stats.js";

const today = "2026-11-14";
const ok = (counters, peaks = []) => validateBatch({ v: 1, counters, peaks }, today);
const bad = (body) => assert.throws(() => validateBatch(body, today));

test("accepts the counters the game server sends", () => {
  ok(
    [
      [today, "rooms_created", "solo", 2],
      [today, "games_started", "4p-1h", 1],
      [today, "bot_mix", "easy+hard", 1],
      [today, "bot_seats", "hard", 3],
      [today, "game_seconds", "2p-1h", 1800],
      [today, "game_duration", "40m+", 1],
      [today, "new_players", "", 5],
      ["2026-11-13", "games_abandoned", "3p-2h", 1],
    ],
    [[today, "peak_players", 7]],
  );
});

test("rejects anything that could carry personal data", () => {
  bad({ v: 1, counters: [], names: ["Ann"] });
  bad({ v: 2, counters: [] });
  bad({ v: 1, counters: [[today, "room_code", "ABCDEF", 1]] });
  bad({ v: 1, counters: [[today, "games_started", "Ann", 1]] });
  bad({ v: 1, counters: [[today, "rooms_created", "203.0.113.9", 1]] });
  bad({ v: 1, counters: [[today, "new_players", "a1b2c3", 1]] });
  bad({ v: 1, counters: [[today, "bot_mix", "easy+Ann", 1]] });
  bad({ v: 1, counters: [[today, "__proto__", "", 1]] });
  bad({ v: 1, counters: [[today, "games_started", "2p-1h", 1, "extra"]] });
  bad({ v: 1, counters: [[today, "games_started", "2p-1h", -1]] });
  bad({ v: 1, counters: [[today, "games_started", "2p-1h", 1.5]] });
  bad({ v: 1, counters: [["2020-01-01", "games_started", "2p-1h", 1]] });
  bad({ v: 1, peaks: [[today, "peak_players", "7"]] });
  bad({ v: 1, peaks: [[today, "who", 7]] });
  bad({ v: 1, counters: Array.from({ length: 2001 }, () => [today, "new_players", "", 1]) });
  bad([]);
  bad(null);
});
