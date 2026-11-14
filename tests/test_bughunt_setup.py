"""Bug hunt: deal and hand fixing (setup phase), 2 to 5 players.

Authority: IB-Flip__The_Complete_Rules.pdf ("Dealing Cards", "Fixing Hand",
"Deciding Who Starts") plus the owner rulings in docs/rules-audit.md
(combining face-up cards is allowed; every face-up slot must be filled before
Ready; stacks stay homogeneous; swaps are one-for-one).

Every state here is reached with real fixing calls from a seeded ``reset()``
(or from a hand-dealt table only where noted), so nothing depends on the
unvalidated ``set_state`` path. Tests that pass are kept as evidence for the
"areas checked and found correct" part of the bug-hunt report.
"""
from __future__ import annotations

import copy
import random

import pytest

from ibflip import IBFlipEngine, IllegalActionError
from ibflip.ai.agents import heuristic_fix
from ibflip.cards import Rank, Suit, card_id
from ibflip.state import Phase
from ibflip_web.serialize import serialize_view

PLAYERS = [2, 3, 4, 5]

# Transcribed from the PDF independently of ibflip.cards:
# "lowest first: 3, 6, 8, 9, J, Q, K, A, 7, 2, 10, 4, 5" and
# "lowest first: hearts, diamonds, clubs, spades".
PDF_LOWEST = ["3", "6", "8", "9", "J", "Q", "K", "A", "7", "2", "10", "4", "5"]
RANK_LABEL = ["3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A", "2"]  # id // 4
PDF_SUIT = ["hearts", "diamonds", "clubs", "spades"]  # id % 4


def pdf_lowest_key(card: int) -> tuple[int, int]:
    return PDF_LOWEST.index(RANK_LABEL[card // 4]), card % 4


def all_cards(engine: IBFlipEngine) -> list[int]:
    state = engine.state
    cards = list(state.draw_pile) + list(state.live_cards) + list(state.discard_pile)
    for player in state.players:
        cards += player.hand
        cards += [card for slot in player.face_up_slots for card in slot]
        cards += [card for card in player.face_down_slots if card is not None]
    return cards


def zones(player):
    return copy.deepcopy((player.hand, player.face_up_slots, player.face_down_slots, player.known_hand))


class SeenTracker:
    """Records every card that was ever face up for each player.

    Wraps the engine's fixing methods on the instance so intermediate states
    inside ``heuristic_fix`` (which calls these same methods) are observed too.
    """

    def __init__(self, engine: IBFlipEngine) -> None:
        self.engine = engine
        self.seen = [set() for _ in engine.state.players]
        self.update()
        for name in ("fix_swap_card", "fix_stack_card", "fix_unstack_card", "fix_fill_empty_slots"):
            original = getattr(engine, name)

            def wrapped(*args, _original=original):
                try:
                    return _original(*args)
                finally:
                    self.update()

            setattr(engine, name, wrapped)

    def update(self) -> None:
        for index, player in enumerate(self.engine.state.players):
            for slot in player.face_up_slots:
                self.seen[index].update(slot)


def assert_setup_invariants(engine, dealt_face_down, tracker, frozen, where):
    state = engine.state
    assert sorted(all_cards(engine)) == list(range(52)), (where, "52 cards, each exactly once")
    for index, player in enumerate(state.players):
        assert player.face_down_slots == dealt_face_down[index], (where, "face-down cards never move")
        assert len(player.face_up_slots) == 3, where
        for slot in player.face_up_slots:
            assert len({card // 4 for card in slot}) <= 1, (where, "stacks hold one rank")
        assert len(player.hand) <= 3, (where, "never more than three in hand")
        if len(player.hand) < 3:
            # "Unless this situation arises [empty draw-pile], ... all players
            # should have exactly three cards in their hand."
            assert not state.draw_pile, (where, "short hand while the draw-pile still has cards")
        public = sorted(card for card in player.hand if card in tracker.seen[index])
        assert sorted(player.known_hand) == public, (where, "known hand = hand cards that were face up")
        if player.fixing_done and state.phase is Phase.FIXING_HANDS:
            assert zones(player) == frozen[index], (where, "a ready player's cards changed")


# ------------------------------------------------------------------- dealing
@pytest.mark.parametrize("players", PLAYERS)
def test_deal_gives_three_down_three_up_three_in_hand_and_the_rest_to_the_draw_pile(players):
    for seed in range(200):
        engine = IBFlipEngine(players, seed=seed)
        engine.reset()
        state = engine.state
        assert state.phase is Phase.FIXING_HANDS
        assert len(state.draw_pile) == 52 - 9 * players
        assert sorted(all_cards(engine)) == list(range(52))
        assert not state.live_cards and not state.discard_pile
        for player in state.players:
            assert len(player.face_down_slots) == 3 and None not in player.face_down_slots
            assert [len(slot) for slot in player.face_up_slots] == [1, 1, 1]
            assert len(player.hand) == 3
            assert player.known_hand == [] and not player.fixing_done


def test_unsupported_table_sizes_are_refused():
    for players in (0, 1, 6, 7):
        with pytest.raises(ValueError):
            IBFlipEngine(players)


# ------------------------------------------------------------ fixing fuzz
def _random_op(engine, rng, frozen):
    """One random simultaneous-API fixing call, legal or not (like a client)."""
    state = engine.state
    index = rng.randrange(len(state.players))
    player = state.players[index]
    visible = [card for slot in player.face_up_slots for card in slot]
    foreign = rng.randrange(52)
    op = rng.randrange(8)
    if op <= 1:
        return index, lambda: engine.fix_swap_card(index, rng.choice(player.hand + [foreign]), rng.randrange(3))
    if op <= 3:
        return index, lambda: engine.fix_stack_card(index, rng.choice(player.hand + visible + visible + [foreign]), rng.randrange(3))
    if op == 4:
        return index, lambda: engine.fix_unstack_card(index, rng.randrange(3))
    if op == 5:
        return index, lambda: heuristic_fix(engine, index) if not player.fixing_done else engine.fix_done(index)
    if op == 6 and rng.random() < 0.3:
        return index, lambda: engine.fix_done(index)
    # Out-of-range slot (a face-down "slot 3", negative index).
    return index, lambda: engine.fix_stack_card(index, rng.choice(player.hand + visible), rng.choice([-1, 3, 4]))


@pytest.mark.parametrize("players", PLAYERS)
def test_random_fixing_keeps_every_setup_invariant(players):
    """Interleaved, partly illegal fixing by every seat, bots included.

    Checks conservation, fixed face-down cards, homogeneous stacks, hand size,
    exact public-knowledge tracking, frozen ready players, and that a refused
    call changes nothing. Ends by readying everyone and checking the starter.
    """
    for seed in range(60):
        rng = random.Random(seed * 7 + players)
        engine = IBFlipEngine(players, seed=seed)
        engine.reset()
        tracker = SeenTracker(engine)
        dealt_face_down = [list(p.face_down_slots) for p in engine.state.players]
        frozen: dict[int, tuple] = {}
        for step in range(250):
            if engine.state.phase is not Phase.FIXING_HANDS:
                break
            index, call = _random_op(engine, rng, frozen)
            before = copy.deepcopy(engine.state)
            try:
                call()
            except IllegalActionError:
                assert engine.state == before, (seed, step, "a refused fixing call changed the game")
            for i, player in enumerate(engine.state.players):
                if player.fixing_done and i not in frozen:
                    frozen[i] = zones(player)
            assert_setup_invariants(engine, dealt_face_down, tracker, frozen, (players, seed, step))
        for index, player in enumerate(engine.state.players):
            if not player.fixing_done:
                if not all(player.face_up_slots):
                    engine.fix_fill_empty_slots(index)
                engine.fix_done(index)
        _assert_pdf_starter(engine)


def _assert_pdf_starter(engine):
    state = engine.state
    assert state.phase in (Phase.EARLY_GAME, Phase.MIDDLE_GAME)
    assert (state.phase is Phase.EARLY_GAME) == bool(state.draw_pile)
    for player in state.players:
        assert all(player.face_up_slots), "a face-up slot is empty at the start"
    # Documented interpretation: hand cards count; a player whose hand was
    # left empty by an exhausted deck uses their face-up cards.
    candidates = [
        (pdf_lowest_key(card), index, card)
        for index, player in enumerate(state.players)
        for card in (player.hand or [c for slot in player.face_up_slots for c in slot])
    ]
    _, starter, card = min(candidates)
    assert state.current_player == starter
    assert state.required_start_card_id == card
    assert engine.get_legal_action_indices() == [card], "the lowest card must be played first"


# -------------------------------------------------------------- foreign cards
def _fresh(players=4, seed=11):
    engine = IBFlipEngine(players, seed=seed)
    engine.reset()
    return engine


def test_fixing_refuses_cards_the_player_does_not_hold_and_slots_that_do_not_exist():
    engine = _fresh()
    me, other = engine.state.players[0], engine.state.players[1]
    foreign = {
        "own face-down": me.face_down_slots[0],
        "opponent hand": other.hand[0],
        "opponent face-up": other.face_up_slots[0][0],
        "draw-pile": engine.state.draw_pile[0],
    }
    for label, card in foreign.items():
        for slot in range(3):
            for call in (engine.fix_swap_card, engine.fix_stack_card):
                before = copy.deepcopy(engine.state)
                with pytest.raises(IllegalActionError):
                    call(0, card, slot)
                assert engine.state == before, label
    for slot in (-1, 3, 4):
        before = copy.deepcopy(engine.state)
        with pytest.raises(IllegalActionError):
            engine.fix_swap_card(0, me.hand[0], slot)
        with pytest.raises(IllegalActionError):
            engine.fix_unstack_card(0, slot)
        assert engine.state == before
    for player_index in (-1, 4, 9):
        with pytest.raises(IllegalActionError):
            engine.fix_done(player_index)


def test_engine_has_no_way_to_touch_face_down_cards_while_fixing():
    engine = _fresh()
    me = engine.state.players[0]
    dealt = list(me.face_down_slots)
    # Combining empties a slot, exposing the face-down card as its base; the
    # only ways to fill it put a hand or stacked card on top of it.
    for _ in range(200):
        heuristic_fix(engine, 0)
        assert me.face_down_slots == dealt
    public = [name for name in dir(engine) if name.startswith("fix_")]
    assert sorted(public) == ["fix_done", "fix_fill_empty_slots", "fix_stack_card", "fix_swap_card", "fix_unstack_card"]


# ------------------------------------------------- stacking edge cases (PDF)
def _table(engine, hand, face_up, draw=None):
    """Hand-deal seat 0 (seat 1+ get leftovers); returns seat 0."""
    me = engine.state.players[0]
    used = set(hand) | {c for slot in face_up for c in slot}
    rest = [c for c in range(52) if c not in used]
    me.hand, me.face_up_slots, me.face_down_slots = list(hand), [list(s) for s in face_up], rest[:3]
    rest = rest[3:]
    for other in engine.state.players[1:]:
        other.hand, other.face_up_slots, other.face_down_slots = rest[:3], [[rest[3]], [rest[4]], [rest[5]]], rest[6:9]
        rest = rest[9:]
    engine.state.draw_pile = rest if draw is None else [c for c in rest if c in draw]
    return me


C = card_id
H, D, CL, S = Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS, Suit.SPADES


def test_four_of_a_kind_can_all_go_on_one_slot_and_the_hand_draws_back_to_three():
    engine = IBFlipEngine(2, seed=0)
    engine.reset()
    sevens = [C(Rank.SEVEN, s) for s in (H, D, CL, S)]
    me = _table(engine, [sevens[3], C(Rank.KING, H), C(Rank.QUEEN, H)], [[sevens[0]], [sevens[1]], [sevens[2]]])
    pile_before = len(engine.state.draw_pile)
    engine.fix_stack_card(0, sevens[1], 0)
    engine.fix_stack_card(0, sevens[2], 0)
    engine.fix_stack_card(0, sevens[3], 0)  # from hand: draws one
    engine.fix_swap_card(0, C(Rank.KING, H), 1)  # into an emptied slot: draws one
    engine.fix_swap_card(0, C(Rank.QUEEN, H), 2)
    assert me.face_up_slots[0] == sevens and len(me.hand) == 3
    assert len(engine.state.draw_pile) == pile_before - 3
    engine.fix_done(0)


def test_two_matching_hand_cards_can_be_stacked_together_on_a_slot():
    """'two or more of the same card ... in their hand and face-up cards'."""
    engine = IBFlipEngine(3, seed=0)
    engine.reset()
    nine_h, nine_d, three_c = C(Rank.NINE, H), C(Rank.NINE, D), C(Rank.THREE, CL)
    me = _table(engine, [nine_h, nine_d, C(Rank.ACE, H)], [[three_c], [C(Rank.SIX, H)], [C(Rank.JACK, H)]])
    engine.fix_swap_card(0, nine_h, 0)  # the 3 comes up into the hand
    engine.fix_stack_card(0, nine_d, 0)  # and the second 9 joins: draw one
    assert me.face_up_slots[0] == [nine_h, nine_d]
    assert three_c in me.hand and three_c in me.known_hand and len(me.hand) == 3


@pytest.mark.parametrize("special", [Rank.TWO, Rank.TEN, Rank.FOUR, Rank.THREE, Rank.EIGHT, Rank.NINE])
def test_special_cards_fix_like_any_other_card(special):
    engine = IBFlipEngine(2, seed=0)
    engine.reset()
    a, b, c = C(special, H), C(special, D), C(special, CL)
    me = _table(engine, [b, c, C(Rank.KING, S)], [[a], [C(Rank.QUEEN, S)], [C(Rank.JACK, S)]])
    engine.fix_stack_card(0, b, 0)
    engine.fix_stack_card(0, c, 0)
    engine.fix_swap_card(0, me.hand[0], 1)
    assert me.face_up_slots[0] == [a, b, c] and len(me.hand) == 3
    engine.fix_done(0)
    engine.fix_done(1)
    _assert_pdf_starter(engine)


def test_exhausted_draw_pile_offers_take_back_or_keep_short_hand():
    """'that player may choose to take up one of their cards from any of their
    stacked face-up slots or to keep their under-sized hand'."""
    engine = IBFlipEngine(2, seed=0)
    engine.reset()
    q = [C(Rank.QUEEN, s) for s in (H, D, CL)]
    me = _table(engine, [q[1], q[2], C(Rank.KING, H)], [[q[0]], [C(Rank.SIX, H)], [C(Rank.JACK, H)]], draw=[])
    engine.fix_stack_card(0, q[1], 0)
    engine.fix_stack_card(0, q[2], 0)
    assert len(me.hand) == 1 and not engine.state.draw_pile
    snapshot = copy.deepcopy(engine.state)
    engine.fix_unstack_card(0, 0)  # take one back
    assert len(me.hand) == 2 and me.hand[-1] in me.known_hand
    engine.fix_unstack_card(0, 0)
    assert len(me.hand) == 3
    with pytest.raises(IllegalActionError):
        engine.fix_unstack_card(0, 0)  # hand is full again
    # ...or keep the short hand and be ready.
    engine.set_state(snapshot)
    engine.fix_done(0)
    assert engine.state.players[0].fixing_done and len(engine.state.players[0].hand) == 1


def test_take_back_is_not_offered_while_the_draw_pile_has_cards():
    from ibflip.actions import FIX_TAKE_FROM_STACK_ACTIONS, ACTION_FIX_KEEP_UNDERSIZED_HAND

    engine = IBFlipEngine(2, seed=0)
    engine.reset()
    q = [C(Rank.QUEEN, s) for s in (H, D)]
    me = _table(engine, [q[1], C(Rank.KING, H), C(Rank.ACE, H)], [[q[0]], [C(Rank.SIX, H)], [C(Rank.JACK, H)]])
    engine.fix_stack_card(0, q[1], 0)
    assert engine.state.draw_pile and len(me.hand) == 3
    with pytest.raises(IllegalActionError):
        engine.fix_unstack_card(0, 0)
    legal = engine.get_legal_action_indices()
    assert not set(legal) & (set(FIX_TAKE_FROM_STACK_ACTIONS) | {ACTION_FIX_KEEP_UNDERSIZED_HAND})


@pytest.mark.parametrize("players", PLAYERS)
def test_random_sequential_fixing_keeps_every_setup_invariant(players):
    """The step()/action-mask path (stress test, AEC) over many seeds."""
    from ibflip.actions import ACTION_FIX_DONE

    for seed in range(60):
        rng = random.Random(1000 + seed)
        engine = IBFlipEngine(players, seed=seed)
        engine.reset()
        tracker = SeenTracker(engine)
        dealt_face_down = [list(p.face_down_slots) for p in engine.state.players]
        frozen: dict[int, tuple] = {}
        for step in range(3000):
            if engine.state.phase is not Phase.FIXING_HANDS:
                break
            legal = engine.get_legal_action_indices()
            assert legal, "no legal fixing action"
            mover = engine.state.current_player
            assert not engine.state.players[mover].fixing_done, "a ready player is asked to fix"
            others = [a for a in legal if a != ACTION_FIX_DONE]
            action = ACTION_FIX_DONE if ACTION_FIX_DONE in legal and (not others or rng.random() < 0.05) else rng.choice(others)
            engine.step(action)
            for i, player in enumerate(engine.state.players):
                if player.fixing_done and i not in frozen:
                    frozen[i] = zones(player)
            assert_setup_invariants(engine, dealt_face_down, tracker, frozen, (players, seed, step))
        else:
            pytest.fail("sequential fixing did not finish")
        _assert_pdf_starter(engine)


# --------------------------------------------------------------- info leaks
def _hidden_positions(engine, viewer):
    """(container, index) of every card the viewer cannot know."""
    state = engine.state
    positions = [(state.draw_pile, i) for i in range(len(state.draw_pile))]
    for index, player in enumerate(state.players):
        positions += [(player.face_down_slots, i) for i in range(len(player.face_down_slots))]
        if index != viewer:
            positions += [(player.hand, i) for i, c in enumerate(player.hand) if c not in player.known_hand]
    return positions


@pytest.mark.parametrize("players", PLAYERS)
def test_fixing_views_do_not_depend_on_cards_the_viewer_cannot_see(players):
    for seed in range(40):
        rng = random.Random(seed)
        engine = IBFlipEngine(players, seed=seed)
        engine.reset()
        for index in range(players):
            if rng.random() < 0.7:
                heuristic_fix(engine, index)
            if rng.random() < 0.5:
                engine.fix_done(index)
        if engine.state.phase is not Phase.FIXING_HANDS:
            continue
        for viewer in [None, *range(players)]:
            twin = engine.clone()
            positions = _hidden_positions(twin, -1 if viewer is None else viewer)
            values = [container[i] for container, i in positions]
            rng.shuffle(values)
            for (container, i), value in zip(positions, values):
                container[i] = value
            for player in twin.state.players:
                player.known_hand = [c for c in player.known_hand if c in player.hand]
            assert sorted(all_cards(twin)) == list(range(52))
            assert serialize_view(engine, viewer, "fixing") == serialize_view(twin, viewer, "fixing")


def test_fixing_view_shows_own_hand_but_only_counts_and_public_cards_of_others():
    engine = _fresh(4)
    heuristic_fix(engine, 1)
    view = serialize_view(engine, 0, "fixing")
    assert view["hand"] == engine.state.players[0].hand
    assert view["current"] is None and view["legal"]["cards"] == []
    for index, entry in enumerate(view["players"]):
        assert "hand" not in entry and "face_down_cards" not in entry
        assert entry["face_down"] == [True, True, True]
        assert set(entry["known"]) <= set(engine.state.players[index].hand)
    spectator = serialize_view(engine, None, "fixing")
    assert "hand" not in spectator


# ------------------------------------------------ bot path within human path
def test_heuristic_fix_only_makes_moves_a_human_could_send():
    """Replay every bot fixing change as room 'swap'/'stack'/'unstack' ops."""
    from ibflip_web.rooms import Room

    for players in PLAYERS:
        for seed in range(80):
            engine = IBFlipEngine(players, seed=seed)
            engine.reset()
            human = engine.clone()
            ops: list[tuple[str, int | None, int]] = []
            target = engine.state.players[0]
            for name in ("fix_swap_card", "fix_stack_card", "fix_unstack_card"):
                original = getattr(engine, name)

                def spy(index, *args, _original=original, _name=name):
                    op = {"fix_swap_card": "swap", "fix_stack_card": "stack", "fix_unstack_card": "unstack"}[_name]
                    if index == 0:
                        ops.append((op, args[0], args[1]) if op != "unstack" else (op, None, args[0]))
                    return _original(index, *args)

                setattr(engine, name, spy)
            original_fill = engine.fix_fill_empty_slots

            def fill_spy(index):
                before = copy.deepcopy(engine.state.players[index].face_up_slots)
                count = len(ops)
                original_fill(index)
                if len(ops) == count:  # split off a stack without a hand card
                    after = engine.state.players[index].face_up_slots
                    for slot_index, slot in enumerate(after):
                        for card in slot:
                            if card not in before[slot_index]:
                                ops.append(("stack", card, slot_index))

            engine.fix_fill_empty_slots = fill_spy
            heuristic_fix(engine, 0)

            room = Room(code="REPLAY")
            room.engine, room.status = human, "fixing"
            for op, card, slot in ops:
                room.fix(0, op, card, slot)
            assert human.state.players[0] == target, (players, seed, ops)
            assert human.state.draw_pile == engine.state.draw_pile
            room.fix(0, "done", None, None)


# ----------------------------------------------------------- room / socket
def _two_human_room():
    from fastapi.testclient import TestClient
    from ibflip_web.main import app, registry

    client = TestClient(app)
    created = client.post("/api/rooms", json={"name": "A", "bots": []}).json()
    joined = client.post(f"/api/rooms/{created['code']}/join", json={"name": "B"}).json()
    return client, registry.get(created["code"]), created, joined


def _drain_until(ws, predicate, limit=20):
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message not received")


def test_two_humans_ready_over_sockets_start_once_with_the_pdf_starter_and_ready_is_final():
    client, room, a, b = _two_human_room()
    with client:
        with client.websocket_connect(f"/ws/{room.code}?token={a['token']}") as wa, \
                client.websocket_connect(f"/ws/{room.code}?token={b['token']}") as wb:
            received_a: list[dict] = []
            original_receive = wa.receive_json

            def receive_a():
                message = original_receive()
                received_a.append(message)
                return message

            wa.receive_json = receive_a
            wa.receive_json()
            wb.receive_json()
            wa.send_json({"type": "start"})
            _drain_until(wa, lambda m: m.get("game", {}).get("status") == "fixing")
            _drain_until(wb, lambda m: m.get("game", {}).get("status") == "fixing")
            # B stacks or swaps a card so a fixing event (draw) is broadcast to A.
            other = room.engine.state.players[1]
            wb.send_json({"type": "fix", "op": "swap", "card": other.hand[0], "slot": 0})
            _drain_until(wa, lambda m: m.get("game", {}).get("players", [{}, {}])[1].get("known"))
            wa.send_json({"type": "fix", "op": "done"})
            _drain_until(wa, lambda m: m.get("game", {}).get("players", [{}])[0].get("ready"))
            for message in received_a:
                assert b["token"] not in repr(message), "another seat's token reached this socket"
                for event in message.get("events", []):
                    assert "card" not in event or event.get("kind") == "start", event
                hidden = set(other.hand) - set(other.known_hand)
                game = message.get("game", {})
                assert not hidden & set(game.get("hand", [])), "opponent's hidden hand card in my hand view"
            me = room.engine.state.players[0]
            frozen = zones(me)
            wa.send_json({"type": "fix", "op": "swap", "card": me.hand[0], "slot": 0})
            error = _drain_until(wa, lambda m: m.get("type") == "error")
            assert "Already ready" in error["message"]
            wa.send_json({"type": "fix", "op": "undo_done"})
            error = _drain_until(wa, lambda m: m.get("type") == "error")
            assert zones(me) == frozen
            wb.send_json({"type": "fix", "op": "done"})
            started = _drain_until(wb, lambda m: m.get("game", {}).get("status") == "playing")
            _assert_pdf_starter(room.engine)
            assert started["game"]["current"] == room.engine.state.current_player
            assert started["game"]["start_card"] == room.engine.state.required_start_card_id
            wb.send_json({"type": "fix", "op": "done"})
            error = _drain_until(wb, lambda m: m.get("type") == "error")
            assert "Not fixing now" in error["message"]


def test_seats_cannot_change_while_fixing():
    from ibflip_web.rooms import Room, RoomError

    room = Room(code="SEATSX")
    room.add_human("a")
    room.add_bot("medium")
    room.start()
    assert room.status == "fixing"
    for call in (lambda: room.add_bot("medium"), lambda: room.add_human("late"),
                 lambda: room.remove_seat(1), lambda: room.set_bot(1, "hard")):
        with pytest.raises(RoomError):
            call()
    room.leave(0)  # leaving keeps the seat (autopiloted), indices stay aligned
    assert len(room.seats) == len(room.engine.state.players) == 2


# ---------------------------------------------------- fixing idle timeout
def _connected_human_room():
    import types

    from ibflip_web.rooms import Room

    room = Room(code="IDLEXX")
    room.add_human("me")
    room.add_bot("medium")
    room.start()
    room.seats[0].sockets.append(types.SimpleNamespace(closed=False, send=lambda message: None))
    return room


@pytest.mark.xfail(strict=True, reason=(
    "BUG: the fixing idle deadline runs from the deal (Room.turn_started) and Room.fix never "
    "refreshes it, so a connected human who is actively fixing is autopiloted at 90 s, contrary "
    "to rooms.py 'A connected human who simply doesn't move gets autopiloted after this long'"))
def test_a_human_who_is_actively_fixing_is_not_autopiloted_for_idleness():
    import time

    from ibflip_web.rooms import IDLE_TURN_TIMEOUT_SECONDS

    room = _connected_human_room()
    me = room.engine.state.players[0]
    room.turn_started = time.time() - IDLE_TURN_TIMEOUT_SECONDS - 1  # dealt 91 s ago
    room.fix(0, "swap", me.hand[0], 0)  # ...but the human is moving right now
    room.seats[0].last_seen = time.time()
    chosen = zones(me)
    assert room._next_auto_deadline() > time.time(), "a fresh fixing move should restart the idle clock"
    room._auto_step()
    assert not me.fixing_done and zones(me) == chosen
