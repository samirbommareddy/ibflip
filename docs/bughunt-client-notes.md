# Bug hunt: client vs engine, auto-actions, hidden information

Branch `local/bughunt-client`. Tests only; no fixes.

## How to run

```bash
uv run --locked python -m pytest -q tests/test_bughunt_client_parity.py tests/test_bughunt_server_robustness.py
node --test tests/test_bughunt_client_logic.mjs
BUGHUNT_UNSKIP=1 node --test tests/test_bughunt_client_logic.mjs   # show the documented bugs failing
uv run --locked python -m pytest -q --runxfail tests/test_bughunt_client_parity.py   # same for Python
```

`tests/client_harness.cjs` loads the real `static/app.js` in a Node vm with an
inert DOM stub and late-bound timers (so `node:test` mock timers work).
`tests/client_views_check.cjs` runs app.js `isLegalNow`, `soleLegalAction`
and `autoActFor` on views dumped by pytest.

## Findings

| # | Severity | Finding | Test |
| --- | --- | --- | --- |
| 1 | wrong legal moves | The required start card is under a same-rank face-up stack (the starter's hand is empty after deck-exhausted fixing). The server's only legal move is that card. The client offers only slot tops, so nothing is clickable. Keys 1-9 and Space do nothing. The player waits for the 90 s idle autopilot. Confirmed in a browser. | `test_start_card_under_a_face_up_stack_is_clickable` |
| 2 | wrong legal moves (hint) | The hint names the bottom card of a face-up stack (`hint_action` returns `mapping[compact][0]`, and `compact_legal` lists slot cards bottom first). The glow lands on a covered card that cannot be clicked. In state 1, "Shark would play 3h" points at the unclickable card. | `test_hint_always_names_a_clickable_card`, `test_hint_for_buried_start_card_is_clickable` |
| 3 | auto-action misfire | The double-click chain ("play every card of this rank") only advances inside `animateEvents`. `pump()` skips that when `S.fast` is set (hidden tab, catch-up, or 4 or more queued messages). The chain stops after the first card. `S.autoGroup` stays set, so `scheduleAutoAct` also bails and auto-Done never fires. | `double-click 'play every card of this rank' still finishes in a hidden tab` |
| 4 | auto-action misfire | Slow server: auto-Done is sent and no reply arrives for 8 s. The `pendingTimer` then clears `pendingAction`. The next same-state broadcast (for example a presence change) re-arms auto-act and Done is sent a second time. The server answers "Not your turn" or "Illegal move" with an error toast. | `slow server: after the 8 s pending timeout ...` |
| 5 | cosmetic | `showHint` does not check the current state. A hint reply that arrives after the turn moved on still shows "Shark would play X". | `a hint that arrives after the state moved on is not shown` |
| 6 | robustness (latent) | `room_socket` resolves the seat index before `handle_message` waits for the room lock. If a seat purge (rematch, back to lobby, or lobby removal) runs in between, the queued message acts for whoever now holds that index. Today no long lock holder exists while seats can shift, so this is not reachable in normal play. | `test_message_queued_behind_the_lock_acts_for_the_sender_after_seats_shift` |
| info | info | During a nine draw the client gets no legal moves, but the server accepts action 53 from the current player and resolves the draw early. The draw is random either way. | `test_human_can_trigger_the_forced_nine_draw_early` |

Not covered by a test (read from the code, low): after Ready is pressed, any
re-render before the reply re-enables the Ready button
(`renderMe` resets `disabled`). Another player's fix broadcast is one such
re-render. A second press sends `done` again and shows an "Already ready"
toast.

## Checked and found correct

- Legal-move parity over 48 seeded random games (2 to 5 seats, random legal
  fixing ops including stacks). These games include 7,097 states where the
  mover holds a face-up stack, 723 face-up groups, 350 face-down choices,
  8,341 4-loop states, 458 nine draws and 225 reveal-or-pick-up choices. The
  client never offers an engine-illegal move, every engine move has a
  control, auto-act only fires when its action is the single engine
  choice, and every accepted move changes `gameSig`, except Done on 9s, which
  is expected to wait for the draw.
  Random games never exhausted the deck during fixing, so finding 1 needed a
  rigged but legal deal.
- The real app.js `isLegalNow`, `soleLegalAction` and `autoActFor` match the
  engine on more than 2,000 dumped views.
- Auto-act timing: Done after 500 ms and Pick up after 750 ms, sent once. No
  auto-act when Done comes with another card, Pick up comes with Flip deck
  top or a card, a face-down choice exists, or only Flip deck top is legal.
  Nothing fires on another seat's turn, during a nine draw, or after game
  over. Auto-act is cancelled by a new state, disconnect or leave, and
  re-fires once after reconnect. Same-state presence broadcasts keep one
  timer, and an error reply cancels without a resend.
- Hidden information: an independent oracle rebuilt "seen" cards from public
  events and face-up diffs and matched `known` on every view. No view or
  event exposes other hands, any face-down identity (own included), or the
  deck. View keys stay on an allowlist, and hands and face-down cards appear
  only at game over. REST room info carries no tokens or cards. Error
  messages are generic. The live pile order after a 9s flip is public
  ("turns it face up" in the rules). The stats module and its Pages Function
  allow-list were read; the existing `tests/test_stats.py` and
  `test_stats_functions.mjs` cover them.
- Robustness: out-of-turn, foreign-card, duplicate and fix-during-play
  messages are rejected with state unchanged. Joining a full or started room
  returns 409. The host leaving mid-game hands the host role on and the game
  continues. `tests/fuzz_multiplayer.py` ran with seeds 1 and 2 and all
  scenarios. Seed 2 had one "leave" room time out under the full load; it did
  not reproduce when run alone (12 games, 0 problems).
