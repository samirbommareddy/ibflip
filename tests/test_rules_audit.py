"""Regression tests for rules discrepancies found auditing the engine against
IB-Flip__The_Complete_Rules.pdf."""

import random

from fastapi.testclient import TestClient

from ibflip import IBFlipEngine
from ibflip.actions import (
    ACTION_END_PLAY_GROUP,
    ACTION_FACE_DOWN_SLOT_0,
    ACTION_PICK_UP_LIVE_PILE,
    ACTION_REVEAL_DRAW_PILE_TOP,
)
from ibflip.cards import Rank, Suit, card_id
from ibflip.state import GameState, PendingEffect, PendingKind, Phase, Player
from ibflip_web.main import app, registry
from ibflip_web.serialize import serialize_view


def make_engine(state: GameState) -> IBFlipEngine:
    engine = IBFlipEngine(num_players=len(state.players), seed=3)
    engine.set_state(state)
    return engine


QH = card_id(Rank.QUEEN, Suit.HEARTS)
QD = card_id(Rank.QUEEN, Suit.DIAMONDS)


def _queen_then_draw_queen_state() -> GameState:
    # Early game: one queen in hand, the next card of the draw pile is a queen.
    return GameState(
        players=[
            Player(hand=[QH, card_id(Rank.SEVEN, Suit.CLUBS), card_id(Rank.FOUR, Suit.CLUBS)]),
            Player(hand=[card_id(Rank.KING, Suit.CLUBS)]),
        ],
        draw_pile=[QD, card_id(Rank.KING, Suit.HEARTS), card_id(Rank.ACE, Suit.HEARTS)],
        live_cards=[card_id(Rank.JACK, Suit.SPADES)],
        phase=Phase.EARLY_GAME,
        current_player=0,
    )


# --------------------------------------------------------------- the Q bug
def test_card_drawn_after_playing_can_be_added_to_the_same_play():
    """PDF, Early-Game: "If a player draws a card that they just played, they
    may play that card as well, as long as they manage to play it before the
    next player plays." """
    engine = make_engine(_queen_then_draw_queen_state())

    engine.step(QH)

    player = engine.state.players[0]
    assert QD in player.hand, "player must draw back to three right after playing"
    legal = engine.get_legal_action_indices()
    assert QD in legal
    engine.step(QD)
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.live_cards[-2:] == [QH, QD]
    assert len(player.hand) == 3
    assert engine.state.current_player == 1


def test_two_queens_in_a_row_over_websocket():
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["easy"], "autostart": True}).json()
        room = registry.get(created["code"])
        room.bot_delay = 0.0
        room.engine.fix_done(0)
        room._after_fixing_check()
        room.engine.set_state(_queen_then_draw_queen_state())
        room.engine.events = []
        with client.websocket_connect(f"/ws/{created['code']}?token={created['token']}") as ws:
            first = ws.receive_json()
            assert QH in first["game"]["legal"]["cards"]
            ws.send_json({"type": "action", "action": QH})
            msg = ws.receive_json()
            assert msg["type"] == "state", msg
            assert QD in msg["game"]["hand"]
            assert QD in msg["game"]["legal"]["cards"]
            ws.send_json({"type": "action", "action": QD})
            msg = ws.receive_json()
            assert msg["type"] == "state", msg
            assert msg["game"]["live"][-2:] == [QH, QD]
            assert msg["game"]["legal"]["end_group"]


# ------------------------------------------------------------------- aces
def test_every_ace_of_a_group_played_on_a_seven_becomes_one():
    """"When an ace is played on a 7, that ace becomes a one, and anything can
    be played on it." Playing two aces together on a 7 must not leave an
    ordinary ace on top."""
    ace_h, ace_d = card_id(Rank.ACE, Suit.HEARTS), card_id(Rank.ACE, Suit.DIAMONDS)
    queen = card_id(Rank.QUEEN, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[ace_h, ace_d, card_id(Rank.KING, Suit.HEARTS)]), Player(hand=[queen])],
            live_cards=[card_id(Rank.SEVEN, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.step(ace_h)
    engine.step(ace_d)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.current_player == 1
    assert engine._target_rank_index() is None
    assert queen in engine.get_legal_action_indices()


def test_revealed_ace_on_a_seven_becomes_one():
    ace = card_id(Rank.ACE, Suit.HEARTS)
    queen = card_id(Rank.QUEEN, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[
                Player(hand=[card_id(Rank.KING, Suit.HEARTS), card_id(Rank.JACK, Suit.HEARTS), card_id(Rank.EIGHT, Suit.HEARTS)]),
                Player(hand=[queen]),
            ],
            draw_pile=[ace, card_id(Rank.KING, Suit.CLUBS)],
            live_cards=[card_id(Rank.SEVEN, Suit.SPADES)],
            phase=Phase.EARLY_GAME,
            current_player=0,
        )
    )
    engine.step(ACTION_REVEAL_DRAW_PILE_TOP)

    assert engine.state.live_cards[-1] == ace
    assert engine.state.current_player == 1
    assert engine._target_rank_index() is None
    assert queen in engine.get_legal_action_indices()


def test_face_down_ace_on_a_seven_becomes_one():
    ace = card_id(Rank.ACE, Suit.HEARTS)
    queen = card_id(Rank.QUEEN, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[Player(face_down_slots=[ace, card_id(Rank.KING, Suit.HEARTS)]), Player(hand=[queen])],
            live_cards=[card_id(Rank.SEVEN, Suit.SPADES)],
            phase=Phase.END_GAME,
            current_player=0,
        )
    )
    engine.step(ACTION_FACE_DOWN_SLOT_0)

    assert engine.state.current_player == 1
    assert engine._target_rank_index() is None
    assert queen in engine.get_legal_action_indices()


def test_ace_that_was_a_one_is_an_ordinary_ace_when_replayed():
    ace = card_id(Rank.ACE, Suit.HEARTS)
    three = card_id(Rank.THREE, Suit.CLUBS)
    engine = make_engine(
        GameState(
            # The ace was a "one" earlier, then got picked up with the pile.
            players=[Player(hand=[ace, card_id(Rank.KING, Suit.HEARTS)]), Player(hand=[three, card_id(Rank.KING, Suit.CLUBS)])],
            live_cards=[card_id(Rank.KING, Suit.SPADES)],
            ace_as_one_card_ids=[ace],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.step(ace)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine._target_rank_index() == int(Rank.ACE)
    assert three not in engine.get_legal_action_indices()  # a 3 goes on 2, 3, 7 only


# ------------------------------------------------------------------- fives
def test_several_fives_are_all_see_through():
    """"When a 5 is played, the next player must play on the card beneath the
    5." With two 5s on a Q, the next player plays on the Q (nothing at all can
    be played on a 5 per the table)."""
    five_h, five_d = card_id(Rank.FIVE, Suit.HEARTS), card_id(Rank.FIVE, Suit.DIAMONDS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[five_h, five_d, card_id(Rank.KING, Suit.HEARTS)]), Player(hand=[QD])],
            live_cards=[QH],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.step(five_h)
    engine.step(five_d)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine._target_rank_index() == int(Rank.QUEEN)
    assert QD in engine.get_legal_action_indices()


def test_five_on_top_after_nine_flip_means_play_on_zero():
    """Special Flip Rules, 9: "...they play on the top card of the live cards
    (note: if the top card is a 5, they play on zero...)"."""
    king = card_id(Rank.KING, Suit.HEARTS)
    five = card_id(Rank.FIVE, Suit.CLUBS)
    three = card_id(Rank.THREE, Suit.HEARTS)
    nines = [card_id(Rank.NINE, s) for s in Suit]
    engine = make_engine(
        GameState(
            players=[Player(hand=[nines[3], three]), Player(hand=[card_id(Rank.QUEEN, Suit.CLUBS)])],
            live_cards=nines[:3],
            discard_pile=[king, five],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.rng.shuffle = lambda cards: None  # keep the promoted pile as [K, 5]
    engine.step(nines[3])
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.live_cards == [king, five]
    assert engine.state.current_player == 0
    assert engine._target_rank_index() is None
    assert three in engine.get_legal_action_indices()  # a 3 could not go on the K


def test_promoted_pile_after_nine_flip_has_no_stale_ace_one():
    ace = card_id(Rank.ACE, Suit.HEARTS)
    three = card_id(Rank.THREE, Suit.HEARTS)
    nines = [card_id(Rank.NINE, s) for s in Suit]
    engine = make_engine(
        GameState(
            players=[Player(hand=[nines[3], three]), Player(hand=[card_id(Rank.QUEEN, Suit.CLUBS)])],
            live_cards=nines[:3],
            discard_pile=[card_id(Rank.KING, Suit.HEARTS), ace],
            ace_as_one_card_ids=[ace],  # it was a one before being flipped away
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.rng.shuffle = lambda cards: None
    engine.step(nines[3])
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.live_cards[-1] == ace
    assert engine._target_rank_index() == int(Rank.ACE)


# --------------------------------------------------------------- four loop
def test_revealed_card_during_four_loop_must_be_four_five_or_six():
    """4: "the next player must pick up the live cards unless they can play a
    4, 5 or 6". A revealed 7 on a 6-on-4 is not a 4, 5 or 6."""
    four = card_id(Rank.FOUR, Suit.HEARTS)
    six = card_id(Rank.SIX, Suit.HEARTS)
    seven = card_id(Rank.SEVEN, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[
                Player(hand=[card_id(Rank.KING, Suit.HEARTS), card_id(Rank.JACK, Suit.HEARTS), card_id(Rank.EIGHT, Suit.HEARTS)]),
                Player(hand=[card_id(Rank.QUEEN, Suit.CLUBS)]),
            ],
            draw_pile=[seven, card_id(Rank.KING, Suit.CLUBS)],
            live_cards=[four, six],
            pending=PendingEffect(PendingKind.FOUR_LOOP, 1),
            phase=Phase.EARLY_GAME,
            current_player=0,
        )
    )
    legal = engine.get_legal_action_indices()
    assert ACTION_REVEAL_DRAW_PILE_TOP in legal and ACTION_PICK_UP_LIVE_PILE in legal
    engine.step(ACTION_REVEAL_DRAW_PILE_TOP)

    assert seven in engine.state.players[0].hand
    assert engine.state.live_cards == []
    assert engine.state.current_player == 1


# ------------------------------------------------------ serialized legal set
def test_serialized_legal_actions_match_engine_exactly():
    for seed in range(60):
        rng = random.Random(seed)
        engine = IBFlipEngine(rng.randint(2, 5), seed=seed)
        engine.reset()
        engine.auto_fix_hands_randomly()
        for _ in range(1500):
            state = engine.state
            if state.phase is Phase.GAME_OVER:
                break
            legal = engine.get_legal_action_indices()
            if not (state.pending and state.pending.kind is PendingKind.NINE_DRAW):
                view = serialize_view(engine, state.current_player, "playing")
                L = view["legal"]
                offered = set(L["cards"]) | {67 + s for s in L["face_down"]}
                offered |= {52} if L["pick_up"] else set()
                offered |= {54} if L["reveal"] else set()
                offered |= {55} if L["end_group"] else set()
                assert offered == set(legal)
                me = state.players[state.current_player]
                pool = me.hand if view["source"] == "hand" else [c for slot in me.face_up_slots for c in slot]
                assert all(card in pool for card in L["cards"])
            engine.step(rng.choice(legal))
