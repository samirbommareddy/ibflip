# Endgame bug hunt (14 November 2026)

Failing tests only, no fixes: `tests/test_bughunt_endgame.py`. Each test is
`xfail(strict=True)`; remove the marker when the item is fixed (or delete
the test if the owner rules the current behaviour correct).

## Findings

| # | Severity | What happens | Minimal repro | Test | Likely code |
| --- | --- | --- | --- | --- | --- |
| 1 | Edge case | A refused rematch (host alone after the other human left) purges left seats, then raises "Need at least two players". Status stays "over" with the old engine, but seat indices have shifted: the survivor's view is paired with the leaver's engine seat (wrong place, wrong cards on the results screen). | 2 humans, seat 0 leaves, game ends, seat 1 sends `rematch`. | `test_refused_rematch_does_not_desync_seats_from_the_finished_game` | `rooms.py` `Room.start` (purge before the size check) |
| 2 | Edge case (client) | Last player left after everyone else finished illegally (place 1, no finish status): results say "You finished first, legally." At 3 to 5 players `youWin` is false (losing sound, no confetti) under a "You win" title. PDF: "A player wins the game if ... they are the last player remaining after all other players have finished illegally." | 3 players, seats 1 and 2 finish illegally, seat 0 views the results. | `test_results_for_last_player_left_after_illegal_finishers` | `static/app.js` `showResult` |
| 3 | Copy | How to play: "If your last play would give you another turn (a 2, a 10, a flip, or an 8 with two players left), you lose." PDF: "or if they finish by flipping a non-4-or-9 set. If they finish by flipping the 4s they remain in the game ... the player finishes illegally unless that card is an 8". | Read `static/index.html`. | `test_how_to_play_finish_copy_exempts_fours_and_nines_flips` | `static/index.html` |
| 4 | Ambiguity | Two 8s as the last cards with two players remaining is a legal win (skip opponent, skip self, opponent plays). Odd counts are illegal. PDF lists "an 8 with two players remaining" as illegal, as an instance of "a way that would make it their own turn". | Heads-up, last cards a face-up stack of two 8s on a 6. Fuzz hits it at n=2 seed=13. | `test_two_eights_heads_up_from_a_face_up_stack_is_an_illegal_finish`, `test_two_eights_with_two_players_left_in_a_four_player_game_is_illegal` | `engine.py` `_resolve_committed_cards` (`Rank.EIGHT` branch), `_finish_or_continue` |
| 5 | Ambiguity (training only) | `IBFlipAECEnv` truncation gives no placement reward: a seat already placed 1st gets 0, unplaced seats 0. `arena.score` keeps earned places and gives unplaced seats -1. | 3-player AEC env, cut off after the first finish. | `test_aec_truncation_keeps_earned_places_and_penalises_only_unplaced` | `env.py` `_apply_terminal_rewards` |

## Areas checked and found correct

- Face-down play: one blind card per turn, legal play resolves at once, illegal
  play picks up the live pile plus the shown card and passes the turn; no
  face-down play while the hand is non-empty; 4-loop applies to face-down.
- Bots, autopilot and hint choose face-down slots blind (swapping a playable
  and an unplayable card leaves the choice distribution unchanged).
- Finishing on 2, 10, a non-4-or-9 set (incl. 3s, after dealing), a 9 whose
  drawn card is a 2/10/heads-up 8, a 9s flip without a discard, a 9s flip
  promoting a 10: illegal. 9s flip promoting an 8, 4s flip with no 3: legal.
  4s flip with a 3: stays in the game, next player's turn.
- 8s flip: flipper is last; earlier illegal finishers move up one; game ends
  when one player remains, who gets the remaining place.
- 3s flip deals only to players still in the game.
- Oracle fuzz (scratch, not committed because it passes): 1,200 random full
  games at 2 to 5 players checked finish legality against the PDF, finished
  players never act or gain/lose cards, card conservation, places form a
  permutation, legal finishers 1st.. in order, first illegal finisher lowest
  of the illegal block, 8s flippers below everyone. Zero problems once
  several 8s heads-up (finding 4) is excluded.
- Per-viewer serialization: hidden hands and face-down cards stay hidden
  until GAME_OVER; events carry only public cards.
- Rematch with two or more seats left: new engine, places reset, wins kept,
  stats hook ends the old game once.

## Questions for the owner

1. Several 8s as the last cards (finding 4). Heads-up two 8s is legal in the
   engine; with three players, two 8s are illegal (skips wrap to the
   finisher) and three 8s are legal. Is the finisher counted while skipping,
   and does "an 8 with two players remaining" mean any number of 8s?
2. Finishing by flipping 4s when the discard has no 3. PDF: "If they finish
   by flipping the 4s they remain in the game, picking up a 3 from the
   discard-pile" and "If there are no 3s in the discard-pile, then that player
   does not have to pick up a 3". Engine: legal finish.
3. Which 3 does a 4s flip take? The engine adds the flipped live pile to the
   discard first, so a 3 lying under the four 4s can be taken. PDF: "takes a
   3 from the discard-pile".
4. 9s flip promoting a pile whose top is a 4, 7, 2 or 9, or whose top four
   cards are a set: the PDF only describes 5, 8 and 10 on top. Engine applies
   no extra effect.
5. Cutoff convention for the AEC env (finding 5): should it match
   `arena.score`?
