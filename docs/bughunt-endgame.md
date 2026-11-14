# Endgame bug hunt (14 November 2026)

Failing tests only, no fixes: `tests/test_bughunt_endgame.py`. Each test is
`xfail(strict=True)`; remove the marker when the bug is fixed.

## Findings

| # | Severity | Finding | Test |
| --- | --- | --- | --- |
| 1 | Breaks rules in normal play | An even number of 8s as the last cards with two players remaining is scored as a legal finish. PDF: "This occurs if they finish on a 2, an 8 with two players remaining, or a 10". The engine computes the next seat as `count + 1` steps from the finisher while still counting the finisher as active (`engine.py` `_resolve_committed_cards`, `effect_rank is Rank.EIGHT`), then `_finish_or_continue` calls it legal when that seat is not the finisher. Odd counts land on the finisher (illegal), even counts on the opponent (legal). | `test_two_eights_heads_up_from_a_face_up_stack_is_an_illegal_finish`, `test_two_eights_with_two_players_left_in_a_four_player_game_is_illegal`, `test_random_full_games_follow_the_pdf_finishing_rules` (n=2 seed=13) |
| 2 | Edge case (training only) | `IBFlipAECEnv` truncation gives no placement reward: an already placed 1st seat gets 0, unplaced seats 0. `arena.score` keeps earned places and gives unplaced seats -1. `env.py` `_apply_terminal_rewards` only runs at GAME_OVER. | `test_aec_truncation_keeps_earned_places_and_penalises_only_unplaced` |
| 3 | Edge case (client) | Results screen for the last player left after all others finished illegally (place 1, no finish status): text "You finished first, legally." and at 3 to 5 players `youWin` is false (losing sound, no confetti) under a "You win" title. `static/app.js` `showResult`. | `test_results_for_last_player_left_after_illegal_finishers` |
| 4 | Copy | How to play: "If your last play would give you another turn (a 2, a 10, a flip, or an 8 with two players left), you lose." PDF exempts flipping the 4s and (with an 8 promoted) the 9s. `static/index.html`. | `test_how_to_play_finish_copy_exempts_fours_and_nines_flips` |

## Questions for the owner

1. Several 8s with three or more players. Engine: two 8s with three players
   is illegal (the skips wrap back to the finisher); three 8s with three
   players is legal. PDF lists only "an 8 with two players remaining", but
   also "If a player finishes a game in a way that would make it their own
   turn, they finish illegally." Which applies, and is the finisher counted
   when skipping?
2. Finishing by flipping 4s when the discard has no 3. PDF: "If they finish
   by flipping the 4s they remain in the game, picking up a 3 from the
   discard-pile" and "If there are no 3s in the discard-pile, then that player
   does not have to pick up a 3". Engine: legal finish (1st free place).
3. Which 3 does a 4s flip take? The engine adds the flipped live pile to the
   discard first, so a 3 lying under the four 4s in the live pile can be
   taken. PDF: "takes a 3 from the discard-pile".
4. 9s flip promoting a pile whose top card is a 4, 7, 2 or 9, or whose top
   four cards are a set: the PDF only describes 5, 8 and 10 on top. Engine
   applies no extra effect.
