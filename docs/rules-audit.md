# Rules and lifecycle audit — 7 November 2026

Follow-up: [Shark v3 training preparation](shark-training-v3.md) addresses the
slot representation, scoring and provenance limitations recorded below. This
audit remains a record of the implementation before that follow-up.

The engine and room protocol have regression coverage for the rules below, and
verified defects found during this audit are repaired. This is evidence for a
working implementation, not a proof that no possible defect remains. The shipped
Shark is an old-rules model and is not certified by this audit.

## Authority and scope

Rule authority is `IB-Flip__The_Complete_Rules.pdf`, with the existing owner
rulings captured in `tests/test_placements_and_rulings.py` and these explicit
owner decisions from this audit:

- Confirmed plays are final; the PDF's take-back rule does not apply.
- Matching face-up cards may be combined across slots while fixing. Moving a
  visible card between slots does not draw a hand card. Corrected 14 November
  2026 (owner ruling: "All 3 must be filled"): combining may empty a slot only
  temporarily. A player cannot be ready, by hand or automatically, until every
  face-up slot holds at least one card. An empty slot is refilled by placing a
  hand card there (the hand then draws back to three, as after stacking; with
  an empty draw-pile the hand stays short) or by moving a card from a face-up
  stack of two or more into it. Automatic readiness (timeouts, disconnects,
  bots) splits a card back off the largest stack. See "Face-up slot
  correction" below.
- Existing rulings remain: blocked early-game players may pick up or reveal;
  pickup is forbidden when a legal card is available, including a 4 chain;
  several 9s in one group draw one random discard card; multiplayer games run
  to full placements rather than ending on the first finish.

Reviewed: card identities, deal and starter selection, both fixing APIs, legal
actions and effects, phase/source transitions, flips, placement and active-seat
traversal, per-viewer serialization, room/socket lifecycle, policy observations,
compact actions, arena scoring, and PPO rollout/terminal scoring. No cloud
compute, training, publication, or deployment was performed.

## Defects repaired

| Finding | Repair and evidence |
| --- | --- |
| Finishing the hand could let a same-rank face-up card join that hand's group. | Groups stay in their original source; face-up groups stay in one slot. Regression exercises the boundary. |
| Simultaneous fixing swapped an entire stack into the hand; sequential fixing swapped just its top and could create mixed-rank stacks. | Shared implementation enforces one-for-one swaps and homogeneous stacks. A different-rank swap onto an existing stack is rejected before mutation. |
| Face-up cards could not be combined across slots. | Both fixing APIs accept visible source cards. Client selects a face-up card, then a matching destination. Source can become empty, but must be refilled before ready (corrected 14 November 2026, see below). |
| Newly selectable fixing cards could have no valid destination. | Selection masks only offer cards with a valid swap/stack destination. Random fixing exercises transitions. |
| Engine fixing API allowed a ready player to alter cards. | Ready-player and player-index validation happens before mutation. |
| Six or more players crashed while dealing the 52-card deck. | Engine rejects unsupported sizes; supported range is 2–5. |
| Empty hands after exhausted-deck fixing could leave an impossible required starting card (`-1`). | Starter candidates use visible slots when a hand is empty, consistent with the normal source transition. This edge-case interpretation is explicit here. |
| AEC cached masks were computed before selecting the next actor. | Select the new actor before refreshing masks; test compares cached masks against observations. |
| AEC illegal actions could bypass pickup obligations by advancing the turn. | Illegal actions raise without changing the game. |
| AEC opponent face-down totals were clipped to 3 even at five-player tables. | Preserve the actual total and declare the correct observation-space bound. API tests now cover 2–5 players. |
| Bot/autopilot activity refreshed abandoned-room expiry indefinitely. | Expiry follows the last human activity/disconnect, independent of bot turns. Closed connections no longer count as connected. |
| Rate-limit test depended on deployment proxy settings. | Test explicitly sets its intended trusted-proxy count, allowing local `.env` settings. |
| Socket fuzzing could blame a deliberately malformed request's error on an advertised legal action. | Action-rejection attribution is restricted to appropriate errors and scenarios; garbage/simultaneous tests still check progress, state agreement, and completion. Without protocol request IDs those errors cannot be reliably correlated. |

## Verified behavior

`tests/test_audit_invariants.py` independently transcribes every cell of the
PDF's 13×13 playability matrix. Other suites cover the lowest-rank/suit starter,
draw-to-three and same-rank drawn extensions, ace-as-one (including replay),
transparent consecutive 5s, 4/5/6 chains, odd/even 3s, skips, forced 9 draws and
chains, all special flips, failed deck/face-down reveals, and legal/illegal
finishes. The 9-flip tests include promoted 5/8/10 cases and stale ace status.

Placement tests establish continued play after a legal or illegal finish,
skipping eliminated seats, two-player skip behavior after eliminations, eights
loss below an earlier illegal finisher, and final unique placements. Direction
and skip traversal are additionally checked against an independent traversal
for active and inactive starting seats in both directions.

Random full-deck invariants check all 52 cards occur exactly once at every
step, public known-hand cards remain unique and in the correct hand, face-up
stacks remain homogeneous, the actor remains active, legal actions exist, and
final places are unique and complete. A hidden-card permutation test verifies
that changing hidden assignments does not change the policy observation.

Socket tests cover mid-game leaving with autopilot through game completion,
host transfer, reconnecting with the same seat and hand, spectating after
finishing, rematch cleanup/renumbering, slow clients, idle autopilot and timer
races. Leaving a room is distinct from finishing: a leaving human's seat stays
in the game under autopilot, preserving their cards and seat indices. A
finished player is removed from active turn traversal. Disconnection offers a
reconnect grace period; it does not eliminate a player.

## Validation evidence

- `./scripts/with-env uv run --locked python -m pytest -vv`: **131 passed**.
  PettingZoo emits advisory Dict-observation and terminal empty-mask warnings.
- `node --test tests/test_review_store.mjs`: **4 passed**.
- New random invariants: 30 seeds for each supported table size, **120 games**.
- Five-player stress: **1,000 games**, 20,000-action cap, **zero timeouts or
  missing-action deadlocks**; longest observed game was 11,001 actions.
  A separate 5,000-action-cap run timed out 11 times. Random legal play can
  revisit positions, so a step cap is a truncation, not proof of a rule error.
- Socket fuzz: **12 completed games across six scenarios, zero problems**;
  4,342 actions, 15 reconnects, 181 simultaneous-message bursts and 69 garbage
  injections. Intentional malformed/stale requests produce expected errors.
  Runner tasks remain during the configured abandonment grace period; sockets
  were all released, and the separate expiry regression covers cleanup.
- Local `agent-browser` on port 8013: actual quick game reached playing after
  readying; an isolated deterministic client fixture selected a face-up card
  then a matching destination and emitted the expected stack request, cleared
  selection, and produced no toast or browser errors. A separate WebSocket
  regression verifies that request actually combines the server's visible slots
  without changing the hand. Chrome required installation and `--no-sandbox`
  on this machine.

Use `python -m pytest` from the repository root. Bare `pytest` currently fails
collection of the design-review module in this environment because the root
is absent from its import path.

## Before training or claiming model strength

The shipped model predates draw/group/ace/5/9 corrections and continued
multiplayer placements. It can still choose engine-masked legal actions, but
its strategy and historical evaluation figures do not establish current-rule
strength. README now makes this distinction explicit. Do not relabel the old
weights as trained on the audited rules.

The PPO script uses the engine directly; AEC fixes do not retroactively repair
old PPO training. Current PPO waits for full placements and uses linear
placement rewards. The current compact policy still pools face-up slots and
chooses among same-rank concrete actions randomly: it cannot learn which of two
same-rank stacks to start. Observations include opponents' active flags but do
not expose their place or stack partition. These are representation limitations,
not permission to play an illegal card; action masks still enforce the engine.
Fixing is heuristic and does not learn the newly allowed face-up combinations.

## Face-up slot correction (14 November 2026)

Bug: the combine added by this audit left the source slot empty with no
mandatory refill, and a swap could not target an empty slot, so humans and
`heuristic_fix` bots (Regular, Shark) could start a game with only a bare
face-down card in a slot. The PDF's Fixing Hand section describes trading
"one-for-one" and stacking onto "one of the three face-up slots" followed by
drawing back to three; it never describes an empty slot, and the owner ruled
that all three face-up slots must be filled.

- Engine: `fix_done`, `ACTION_FIX_DONE` and its legal mask refuse readiness
  while a slot is empty. `fix_swap_card` onto an empty slot places the hand
  card and draws to three. `fix_stack_card` onto an empty slot accepts only a
  card from a face-up stack of two or more. `fix_fill_empty_slots` repairs an
  arrangement without drawing; `auto_fix_hands_randomly` uses it.
- Server: bot readiness, idle/disconnect autopilot and the crash fallback all
  repair before readying, so a room can never stall on a refused ready.
- Bots: `heuristic_fix` refills a slot emptied by combining with its best
  hand card and finishes with the engine repair.
- Client: an empty slot's face-down card is outlined and clickable, Ready is
  disabled and the prompt asks for the slot to be filled.
- Final arrangements reachable are unchanged in kind: combine, place, draw is
  the same result as swap plus stacking from hand. No other rule changed.
- `scripts/stress_test.py` now drives random real fixing actions (it
  previously skipped fixing) and fails if any seat starts with an empty slot.
  Regression tests: `tests/test_face_up_slots_filled.py`.

Training/evaluation cutoffs also need care: PPO assigns its configured timeout
penalty to every learner trajectory, including players already placed; arena
scoring retains placed scores and gives unplaced seats zero. This is an existing
intentional anti-stall convention, not a rulebook outcome. Report truncation
rates separately and settle a common cutoff policy before comparing trainers.

Before a new training run: freeze these rulings; implement/test slot-aware
observations/actions if the model should choose stacks; record source revision,
rule decisions, observation/action schemas and seed/config with checkpoints;
then evaluate fresh paired games at every table size with placements,
truncations, illegal finishes, and eights losses tracked separately. Do not
reuse the README's old-rules strength numbers as a current baseline.

One earlier full-suite attempt stopped making progress in the randomized
crashing-bot socket test and was interrupted after 86 seconds (111 tests had
passed). The final verbose full-suite run passed all 131 tests in 20 seconds.
That test's blocking receive and randomized game remain a test-harness
limitation; one passing rerun does not prove that intermittent waits are gone.

Rooms are in-memory. A server restart loses rooms; reconnect cannot recover
those games. Finite fuzzing does not guarantee delivery/order under every
possible network or process failure. The engine assumes legal, coherent states
for `set_state()` and callers using `validate=False`; those internal APIs are
not untrusted-input validators. The web protocol validates external actions.
