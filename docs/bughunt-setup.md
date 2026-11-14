# Bug hunt: deal and hand fixing (14 November 2026)

Scope: the deal and the fixing (setup) phase for 2 to 5 players, across the
engine (`fix_*`, the sequential step/mask API), `heuristic_fix`, the rooms
server (ready, autopilot, disconnect, timeouts), `serialize_view` and the
fixing UI in `static/app.js`. Tests: `tests/test_bughunt_setup.py`. No source
was changed.

## Finding

| Severity | Finding | Test |
| --- | --- | --- |
| Edge case (server lifecycle) | The fixing idle deadline is `turn_started + IDLE_TURN_TIMEOUT_SECONDS` (90 s from the deal). `Room.fix` never resets it, so a connected human who is still making fixing moves is autopiloted at 90 s. The rooms.py comment says only a human "who simply doesn't move" is autopiloted. The PDF is silent on timeouts. (Whether autopilot should then run the bot heuristic over their arrangement, which it rewrote in 49 of 50 unseeded sample deals, is question 1; rules-audit.md documents that it does.) | `test_a_human_who_is_actively_fixing_is_not_autopiloted_for_idleness` (strict xfail) |

## Checked and found correct

- Deal: 3 face-down, 3 face-up, 3 in hand for each player; draw-pile of
  52 - 9n; all 52 cards present once; 6+ players refused.
- Fixing fuzz, both the simultaneous API (with interleaved `heuristic_fix`)
  and the sequential step/mask API: cards are conserved, face-down cards never
  move, stacks hold one rank, the hand never exceeds three and is short only
  when the draw-pile is empty, `known_hand` is exactly the hand cards that were
  once face up, a ready player is frozen, and a refused call changes nothing.
- The sequential mask and the simultaneous API accept the same moves
  (exploratory check, 0 differences).
- Foreign cards (own face-down, opponents' cards, the draw-pile) and
  out-of-range slots are refused without changes.
- Four of a kind, two matching hand cards, special ranks face up, and the
  empty-draw-pile choice (take back from a stack, or keep a short hand).
- Hidden information: no seat token or hidden card reaches another seat's socket during fixing, and fixing events carry no card ids; fixing views are unchanged when the cards a viewer
  cannot see are shuffled, for every seat and for spectators.
- `heuristic_fix` produces only changes a human can send as room ops.
- Ready is final; double ready after the start is refused; two humans
  readying over sockets start the game once, with the starter set by the
  PDF's rank-then-suit order. Seats cannot change during fixing.

## Read but not exercised

- `static/app.js` fixing UI (read only, no browser run). With a short hand
  and an empty draw-pile, tapping a stack sends `unstack` instead of
  selecting the card, so moving a stacked card directly is not possible
  there; the same arrangements stay reachable through unstack then place.
- PIMC `search_fix` / `apply_arrangement` (not used by the server).

## Questions for the owner

1. Should fixing moves restart the idle clock, and should autopilot keep a
   human's arrangement (only fill empty slots) instead of running the bot
   heuristic? See the finding above.
2. Bots fix and draw at `Room.start()`, before any human can act. With 5
   seats and 4 bots the human sees on average 4.4 of the 7 cards left in the
   draw-pile, and an empty pile in 12 of 300 unseeded sample games. The PDF has everyone fix
   at the same time and names no order.
3. The starter is chosen from hand cards only, or from face-up cards if the
   hand is empty. PDF: "the player with the lowest card must play first. All
   players announce what their lowest card is."
4. There is no un-ready. `Room.fix` mentions an `undo_done` op, but it is not
   in `FIX_OPS` and has no handler.
