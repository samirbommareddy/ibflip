"""Fixing must end with every face-up slot holding at least one card.

Combining matching face-up cards may empty a slot mid-fixing; the slot must be
refilled (a hand card placed there, or a card split back off a stack) before
the player can be ready, and every automatic path repairs it instead.
"""
from __future__ import annotations

import random
import time

import pytest

from ibflip import IBFlipEngine, IllegalActionError
from ibflip.actions import (
    ACTION_FIX_DONE,
    ACTION_FIX_STACK_SLOT_0,
    ACTION_FIX_STACK_SLOT_1,
    ACTION_FIX_SWAP_SLOT_0,
    ACTION_FIX_SWAP_SLOT_1,
    FIX_STACK_ACTIONS,
    FIX_SWAP_ACTIONS,
)
from ibflip.ai.agents import HeuristicAgent, RandomAgent, heuristic_fix
from ibflip.cards import Rank, Suit, card_id
from ibflip.state import GameState, Phase, Player

Q = [card_id(Rank.QUEEN, s) for s in Suit]
SEVEN = [card_id(Rank.SEVEN, s) for s in Suit]
JACK_H, KING_H, THREE_H = card_id(Rank.JACK, Suit.HEARTS), card_id(Rank.KING, Suit.HEARTS), card_id(Rank.THREE, Suit.HEARTS)
FIVE_H, NINE_H, TEN_H = card_id(Rank.FIVE, Suit.HEARTS), card_id(Rank.NINE, Suit.HEARTS), card_id(Rank.TEN, Suit.HEARTS)


def _fixing_engine(draw_pile=None, hand=None):
    """Seat 0 shows Q Q K with J 3 5 in hand; seat 1 is a plain filler."""
    engine = IBFlipEngine(2, seed=3)
    engine.set_state(GameState(
        players=[
            Player(hand=list(hand if hand is not None else [JACK_H, THREE_H, FIVE_H]),
                   face_up_slots=[[Q[0]], [Q[1]], [KING_H]], face_down_slots=[1, 2, 6]),
            Player(hand=[9, 10, 11], face_up_slots=[[13], [14], [15]], face_down_slots=[17, 18, 19]),
        ],
        draw_pile=list(draw_pile if draw_pile is not None else [NINE_H, TEN_H]),
        phase=Phase.FIXING_HANDS,
    ))
    return engine


def _slots_full(engine):
    return all(all(player.face_up_slots) for player in engine.state.players)


# --------------------------------------------------------------- (a) engine
def test_combining_empties_a_slot_and_blocks_ready_until_refilled_from_hand():
    engine = _fixing_engine()
    me = engine.state.players[0]
    engine.fix_stack_card(0, Q[1], 0)  # combine the two queens
    assert me.face_up_slots == [[Q[0], Q[1]], [], [KING_H]]
    assert me.hand == [JACK_H, THREE_H, FIVE_H]  # nothing drawn by a combine
    with pytest.raises(IllegalActionError, match="Fill every face-up slot"):
        engine.fix_done(0)
    assert not me.fixing_done and engine.state.phase is Phase.FIXING_HANDS

    # Placing a hand card into the empty slot refills the hand from the deck.
    engine.fix_swap_card(0, JACK_H, 1)
    assert me.face_up_slots == [[Q[0], Q[1]], [JACK_H], [KING_H]]
    assert me.hand == [THREE_H, FIVE_H, NINE_H]
    engine.fix_done(0)
    assert me.fixing_done


def test_empty_slot_can_be_refilled_by_splitting_a_stack_but_not_by_emptying_another():
    engine = _fixing_engine()
    engine.fix_stack_card(0, Q[1], 0)
    with pytest.raises(IllegalActionError):
        engine.fix_stack_card(0, KING_H, 1)  # would just empty slot 2 instead
    engine.fix_stack_card(0, Q[1], 1)  # split back off the queen stack
    assert engine.state.players[0].face_up_slots == [[Q[0]], [Q[1]], [KING_H]]
    engine.fix_done(0)


def test_sequential_fixing_offers_no_ready_while_a_slot_is_empty():
    engine = _fixing_engine()
    engine.step(Q[1])
    engine.step(ACTION_FIX_STACK_SLOT_0)
    legal = engine.get_legal_action_indices()
    assert ACTION_FIX_DONE not in legal
    with pytest.raises(IllegalActionError):
        engine.step(ACTION_FIX_DONE)
    with pytest.raises(IllegalActionError):
        engine.step(ACTION_FIX_DONE, validate=False)
    # Every hand card can fill the gap; the stacked queen can be split back.
    assert {JACK_H, THREE_H, FIVE_H, Q[1]} <= set(legal)
    engine.step(THREE_H)
    assert ACTION_FIX_SWAP_SLOT_1 in engine.get_legal_action_indices()
    engine.step(ACTION_FIX_SWAP_SLOT_1)
    assert engine.state.players[0].face_up_slots[1] == [THREE_H]
    assert ACTION_FIX_DONE in engine.get_legal_action_indices()


def test_sequential_split_into_empty_slot():
    engine = _fixing_engine()
    engine.step(Q[0])
    engine.step(ACTION_FIX_STACK_SLOT_1)  # slot 0 now empty, queens in slot 1
    engine.step(Q[0])
    assert ACTION_FIX_STACK_SLOT_0 in engine.get_legal_action_indices()
    engine.step(ACTION_FIX_STACK_SLOT_0)
    assert engine.state.players[0].face_up_slots == [[Q[0]], [Q[1]], [KING_H]]


def test_placing_into_empty_slot_with_exhausted_deck_keeps_a_short_hand():
    engine = _fixing_engine(draw_pile=[])
    engine.fix_stack_card(0, Q[1], 0)
    engine.fix_swap_card(0, FIVE_H, 1)
    me = engine.state.players[0]
    assert me.hand == [JACK_H, THREE_H] and all(me.face_up_slots)
    engine.fix_done(0)


def test_fill_empty_slots_repairs_without_drawing_and_with_an_empty_hand():
    engine = _fixing_engine(hand=[])
    me = engine.state.players[0]
    engine.fix_stack_card(0, Q[1], 0)
    engine.fix_fill_empty_slots(0)
    assert all(me.face_up_slots) and me.hand == []
    assert engine.state.draw_pile == [NINE_H, TEN_H]
    engine.fix_done(0)


def test_auto_fix_hands_randomly_repairs_a_half_fixed_player():
    engine = _fixing_engine()
    engine.fix_stack_card(0, Q[1], 0)
    engine.auto_fix_hands_randomly()
    assert engine.state.phase is not Phase.FIXING_HANDS
    assert all(engine.state.players[0].face_up_slots)


# ------------------------------------------------------------ (b) fuzzing
def _random_sequential_fixing(engine, rng):
    for _ in range(3000):
        if engine.state.phase is not Phase.FIXING_HANDS:
            return
        legal = engine.get_legal_action_indices()
        assert legal, "fixing has no legal action"
        me = engine.state.players[engine.state.current_player]
        if ACTION_FIX_DONE in legal:
            assert all(me.face_up_slots)
        else:
            assert engine.state.fix_selected_card_id is not None or not all(me.face_up_slots)
        if engine.state.fix_selected_card_id is not None:
            assert any(a in FIX_SWAP_ACTIONS or a in FIX_STACK_ACTIONS for a in legal), "selection is a dead end"
        others = [a for a in legal if a != ACTION_FIX_DONE]
        if ACTION_FIX_DONE in legal and (not others or rng.random() < 0.1):
            action = ACTION_FIX_DONE
        else:
            action = rng.choice(others)
        engine.step(action)
    pytest.fail("fixing did not finish")


@pytest.mark.parametrize("players", [2, 3, 4, 5])
def test_every_random_sequential_fixing_ends_with_three_filled_slots(players):
    for seed in range(150):
        engine = IBFlipEngine(players, seed=seed)
        engine.reset()
        _random_sequential_fixing(engine, random.Random(seed))
        assert engine.state.phase is not Phase.FIXING_HANDS
        for player in engine.state.players:
            assert len(player.face_up_slots) == 3 and all(player.face_up_slots)


def _random_simultaneous_op(engine, index, rng):
    """Try one random simultaneous-API fixing operation; illegal ones are ignored."""
    player = engine.state.players[index]
    visible = [card for slot in player.face_up_slots for card in slot]
    op = rng.randrange(4)
    try:
        if op == 0 and player.hand:
            engine.fix_swap_card(index, rng.choice(player.hand), rng.randrange(3))
        elif op == 1 and (player.hand or visible):
            engine.fix_stack_card(index, rng.choice(player.hand + visible + visible), rng.randrange(3))
        elif op == 2:
            engine.fix_unstack_card(index, rng.randrange(3))
        else:
            complete = all(player.face_up_slots)
            try:
                engine.fix_done(index)
            except IllegalActionError:
                assert not complete
                return False
            assert complete
            return True
    except IllegalActionError:
        pass
    return False


@pytest.mark.parametrize("players", [2, 3, 4, 5])
def test_simultaneous_fixing_never_readies_with_an_empty_slot(players):
    for seed in range(200):
        rng = random.Random(seed)
        engine = IBFlipEngine(players, seed=seed)
        engine.reset()
        for index in range(players):
            for _ in range(rng.randrange(40)):
                if _random_simultaneous_op(engine, index, rng):
                    break
        for index, player in enumerate(engine.state.players):
            if not player.fixing_done:
                if rng.random() < 0.5:
                    heuristic_fix(engine, index)
                engine.fix_fill_empty_slots(index)
                engine.fix_done(index)
        assert engine.state.phase is not Phase.FIXING_HANDS
        assert _slots_full(engine)


# ------------------------------------------------------- (c) heuristic_fix
@pytest.mark.parametrize("players", [2, 3, 4, 5])
def test_heuristic_fix_never_leaves_an_empty_slot(players):
    combined = 0
    for seed in range(1000):
        engine = IBFlipEngine(players, seed=seed)
        engine.reset()
        for index in range(players):
            heuristic_fix(engine, index)
            assert all(engine.state.players[index].face_up_slots), (seed, index)
            combined += any(len(slot) > 1 for slot in engine.state.players[index].face_up_slots)
            engine.fix_done(index)
    assert combined  # stacking/combining was actually exercised


def test_heuristic_fix_repairs_a_slot_a_human_emptied():
    for seed in range(300):
        engine = IBFlipEngine(4, seed=seed)
        engine.reset()
        me = engine.state.players[0]
        # Fake a human combine that left slot 1 empty.
        me.face_up_slots[0].append(me.face_up_slots[1].pop())
        heuristic_fix(engine, 0)
        assert all(me.face_up_slots)
        engine.fix_done(0)


@pytest.mark.parametrize("players", [2, 4])
def test_heuristic_agents_still_finish_games_after_fixing(players):
    from ibflip.ai.arena import play_game
    for seed in range(20):
        result = play_game([HeuristicAgent(seed=seed + i) if i % 2 else RandomAgent(seed=seed + i)
                            for i in range(players)], seed=seed)
        assert result["steps"] > 0


# ------------------------------------------------------ (d) room / server
def _deal_known_table(engine):
    """Seat 0 gets Q Q K face up and J 3 5 in hand; everyone else plain cards."""
    me = engine.state.players[0]
    me.face_up_slots, me.hand, me.face_down_slots = [[Q[0]], [Q[1]], [KING_H]], [JACK_H, THREE_H, FIVE_H], [1, 2, 6]
    used = {Q[0], Q[1], KING_H, JACK_H, THREE_H, FIVE_H, 1, 2, 6}
    rest = [v for v in range(52) if v not in used]
    for other in engine.state.players[1:]:
        other.hand, other.face_up_slots, other.face_down_slots = rest[:3], [[rest[3]], [rest[4]], [rest[5]]], rest[6:9]
        rest = rest[9:]
    engine.state.draw_pile = rest


def _room_with_combined_human(bots=1):
    from ibflip_web.rooms import Room
    room = Room(code="SLOTAA")
    room.add_human("me")
    for _ in range(bots):
        room.add_bot("medium")
    room.start()
    for player in room.engine.state.players[1:]:
        # Bots fix only after every human is ready (owner ruling, 14 Nov 2026).
        assert not player.fixing_done and all(player.face_up_slots)
    _deal_known_table(room.engine)
    room.fix(0, "stack", Q[1], 0)
    assert room.engine.state.players[0].face_up_slots == [[Q[0], Q[1]], [], [KING_H]]
    return room


def test_room_ready_is_refused_while_a_slot_is_empty_then_accepted():
    room = _room_with_combined_human()
    with pytest.raises(IllegalActionError):
        room.fix(0, "done", None, None)
    assert room.status == "fixing"
    room.fix(0, "swap", room.engine.state.players[0].hand[0], 1)
    room.fix(0, "done", None, None)
    assert room.status == "playing" and _slots_full(room.engine)


@pytest.mark.parametrize("path", ["_auto_step", "_fallback_step"])
def test_room_auto_ready_repairs_an_empty_slot(path):
    room = _room_with_combined_human(bots=3)
    seat = room.seats[0]
    seat.last_seen = time.time() - 3600  # disconnected long ago
    room.turn_started = time.time() - 3600
    room.fix_activity[0] = time.time() - 3600  # and their last fixing move too
    getattr(room, path)()
    assert room.status == "playing"
    assert _slots_full(room.engine)


def test_disconnected_human_is_auto_readied_with_full_slots_over_the_socket(monkeypatch):
    from fastapi.testclient import TestClient
    import ibflip_web.rooms as rooms
    from ibflip_web.main import app, registry

    monkeypatch.setattr(rooms, "AUTOPILOT_AFTER_SECONDS", 0.2)
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["medium"], "autostart": True}).json()
        room = registry.get(created["code"])
        _deal_known_table(room.engine)
        with client.websocket_connect(f"/ws/{room.code}?token={created['token']}") as ws:
            ws.receive_json()
            ws.send_json({"type": "fix", "op": "stack", "card": Q[1], "slot": 0})
            message = ws.receive_json()
            assert message["game"]["players"][0]["face_up"] == [[Q[0], Q[1]], [], [KING_H]]
            ws.send_json({"type": "fix", "op": "done"})
            error = ws.receive_json()
            assert error["type"] == "error" and "Fill every face-up slot" in error["message"]
        # Socket closed: the autopilot must ready the seat with a full table.
        deadline = time.time() + 10
        while room.status == "fixing" and time.time() < deadline:
            time.sleep(0.05)
        assert room.status == "playing"
        assert all(room.engine.state.players[0].face_up_slots)
