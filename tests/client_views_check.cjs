// Helper for tests/test_bughunt_client_parity.py (not a test itself):
// reads [{seat, game}, ...] JSON on stdin, runs the real app.js isLegalNow /
// soleLegalAction / autoActFor on each view and prints the results as JSON.
"use strict";
const { loadClient } = require("./client_harness.cjs");
const input = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
const { T } = loadClient();
const out = input.map(({ seat, game }) => {
  T.S.seat = seat;
  T.S.game = game;
  const legalNow = [];
  for (let a = 0; a < 70; a++) if (T.isLegalNow(a)) legalNow.push(a);
  return { legalNow, sole: T.soleLegalAction(game), auto: T.autoActFor(game) };
});
process.stdout.write(JSON.stringify(out));
