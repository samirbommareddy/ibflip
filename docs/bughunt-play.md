# Turn-play bug hunt, 14 November 2026

Scope: turn play from the first move until a player's hand and face-up cards
are gone, plus face-down play where it meets special cards. Authority is
`IB-Flip__The_Complete_Rules.pdf` and the owner rulings in
`docs/rules-audit.md`. No engine code was changed. Tests are in
`tests/test_bughunt_play.py`. Each bug is an `xfail(strict=True)` test whose
reason starts with `BUG:`. The other tests in that file pass and record what
was checked.

## Findings

| Severity | Finding | Test |
| --- | --- | --- |
| Edge case | A 6 played on a 4 that a 9s flip promoted to the top of the live cards does not start the 4 rule. The next player may play anything that goes on a regular 6. The same happens for a 6 played on a 5 on that 4. | `test_six_on_a_four_promoted_by_a_nine_flip_makes_the_next_player_play_on_a_four`, `test_six_on_five_on_a_promoted_four_keeps_the_four_rule` |

PDF, 6: "If a 6 is played on a 4, the next player must play on a 4, as
outlined above." PDF, 4: "the next player must pick up the live cards ...
unless they can play a 4, 5 or 6."

Reproduction: 2 players. Live cards are three 9s, and the discard pile is a
single 4. Player 0 plays the fourth 9, so the 9s flip and the live cards become
`[4]`. Player 0 then plays a 6. Player 1 holds 7 and J and should have to pick
up. The engine offers 7 and J instead.

Likely cause: the 4 rule is carried only by `PendingEffect(FOUR_LOOP)`. That is
set in `_resolve_committed_cards` (`src/ibflip/engine.py`, the `Rank.FOUR`
branch) when a 4 is played. A promoted 4 was never played, so no pending loop
exists. `_target_rank_index` then treats the 6 as a regular 6. A promoted 4 on
its own is harmless, because the matrix for a 4 (4, 5, 6) equals the loop
mask. Only a 6 on it differs.

## Checked and found correct

- Playability matrix: `rules.py` matches every cell of the PDF table. This is
  already tested in `test_complete_pdf_playability_matrix`. The 7 note (7 or
  lower), the 4 note (4, 5, 6 only) and the 10 row (not on 4, 5, 7, 10) agree
  with the matrix.
- Starter: lowest hand card in the order 3, 6, 8, 9, J, Q, K, A, 7, 2, 10, 4, 5,
  with suit ties broken hearts, diamonds, clubs, spades. Face-up cards do not
  count while the hand holds cards. The starter must play that exact card and
  may add more of the same rank. An odd number of opening 3s reverses.
- Groups: an open group offers exactly the same-rank cards of the zone it
  started from (one face-up slot for face-up groups) plus End. The fuzz checks
  this independently.
- Drawing to three after every card in the early game, so a drawn card of the
  same rank can join the group. While the draw-pile lasts, every active player
  holds at least three cards at every turn boundary (fuzz).
- Zone order: face-up cards are played only from an empty hand, face-down only
  when hand and face-up are empty. No other player loses cards on a step
  (fuzz).
- Four in a row across players and within one turn flips on the fourth card.
  Special flips for 3, 4, 8 and 9 behave as written.
- 9s flip with a one-card discard, for each of the 12 other ranks: the
  flipper plays on the promoted card. A 5 means zero, an 8 passes the turn to
  the next player, and a 10 flips again with the flipper to play.
- 9 draw, for each of the 13 ranks drawn, with and without the 9 as the last
  card. The next seat, the direction, the 4 loop, chained 9 draws and the
  10 flip all match. Finishing on a 9 that draws a 2 or a 10 is illegal.
- Reverse with two players passes the turn to the opponent. With two players,
  1, 2 and 3 eights give the turn to the player, the opponent and the player.
- A failed reveal keeps the revealed card, picks up the pile and passes the
  turn. Pickup and reveal are only offered when nothing is playable (fuzz).
- A face-down 2 lets the player attempt another face-down card. For every
  rank, a card played from the hand, by a successful reveal or face-down has
  the same effect (next seat, direction, 4 loop, flip), and finishing on the
  last face-down card is legal or illegal exactly as from the hand.
- Deadlocks: across 100 seeded games (25 for each table size), forced-only
  play never revisited a position, and none of these games reached the
  20,000 step cap (the test asserts zero truncations).
- Legal card sets: the committed fuzz compares every non-group decision with
  an oracle built from the PDF matrix, with the 4 rule derived from the pile
  rather than the engine's pending flag. It encodes the engine's reading of
  question 1 and reads the ace-as-one, five-on-zero and start-card fields from
  the state. The promoted-4 bug state is excluded there. It agreed at every
  decision. A one-off run over 240 further games also agreed.
- The policy's compact action mapping covers exactly the legal decisions.

## Questions for the owner

1. **A 6 on a 6 inside a 4 chain.** 4 says "Play continues in this manner
   until a player cannot play a 4, 5 or 6", so the chain continues (what the
   engine does). 6 says "When a 6 is played on a non-4 card, the next player
   places any card that can be placed on a regular 6", and a 6 played on a 6
   is played on a non-4 card. This happens often: in 240 random games the two
   readings gave different legal moves at 2,229 decision points.
2. **A 5 drawn by a 9.** 9 says "Play continues as if the player that played
   the 9 had played this card instead." The engine puts the drawn 5 on top of
   the 9, so the next player plays on the 9. "Instead" could mean the next
   player plays on the card beneath the 9.
3. **Legality of the card drawn by a 9.** The drawn card is played even if it
   could not legally be played on the card beneath the 9 (for example an 8
   drawn after a 9 played on a 9). Is that intended?
4. **Four 3s completed by one 3, or three 3s on one 3.** The flip takes
   priority and the direction does not change. 3 says "When an odd number of
   3s are played, the direction of play switches", and the flipper plays
   again, so the direction matters afterwards.
5. **Promoted cards and four in a row.** If a 9s flip promotes a pile whose
   top three cards share a rank, does the flipper's matching card flip it?
   Flipping requires "four consecutive cards of the same value played by one
   or more players", and promoted cards were not played. The engine counts
   them.
