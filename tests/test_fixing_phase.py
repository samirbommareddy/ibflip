from ibflip import IBFlipEngine
from ibflip.actions import (
    ACTION_FIX_DONE,
    ACTION_FIX_STACK_SLOT_0,
    ACTION_FIX_SWAP_SLOT_0,
    ACTION_FIX_TAKE_FROM_STACK_SLOT_0,
)
from ibflip.cards import Rank, Suit, card_id
from ibflip.state import GameState, Phase, Player


def test_fixing_phase_can_select_hand_card_and_swap_with_face_up_slot():
    engine = IBFlipEngine(num_players=2, seed=1)
    hand_card = card_id(Rank.FIVE, Suit.HEARTS)
    slot_card = card_id(Rank.THREE, Suit.CLUBS)
    engine.set_state(
        GameState(
            players=[
                Player(hand=[hand_card], face_up_slots=[[slot_card]]),
                Player(hand=[card_id(Rank.SIX, Suit.HEARTS)]),
            ],
            draw_pile=[],
            phase=Phase.FIXING_HANDS,
            current_player=0,
        )
    )

    assert engine.get_legal_actions()[hand_card]
    engine.step(hand_card)
    assert engine.get_legal_actions()[ACTION_FIX_SWAP_SLOT_0]
    engine.step(ACTION_FIX_SWAP_SLOT_0)

    assert engine.state.players[0].hand == [slot_card]
    assert engine.state.players[0].face_up_slots[0] == [hand_card]


def test_fixing_phase_can_stack_matching_cards_and_draw_back_to_three():
    engine = IBFlipEngine(num_players=2, seed=1)
    stacked = card_id(Rank.SEVEN, Suit.HEARTS)
    slot = card_id(Rank.SEVEN, Suit.CLUBS)
    draw = card_id(Rank.KING, Suit.SPADES)
    engine.set_state(
        GameState(
            players=[
                Player(hand=[stacked, card_id(Rank.FIVE, Suit.CLUBS)], face_up_slots=[[slot]]),
                Player(hand=[card_id(Rank.SIX, Suit.HEARTS)]),
            ],
            draw_pile=[draw],
            phase=Phase.FIXING_HANDS,
            current_player=0,
        )
    )

    engine.step(stacked)
    engine.step(ACTION_FIX_STACK_SLOT_0)

    assert stacked in engine.state.players[0].face_up_slots[0]
    assert draw in engine.state.players[0].hand
    assert len(engine.state.players[0].hand) == 2


def test_fixing_phase_can_take_back_from_stack_when_draw_pile_empty():
    engine = IBFlipEngine(num_players=2, seed=1)
    first = card_id(Rank.SEVEN, Suit.HEARTS)
    second = card_id(Rank.SEVEN, Suit.CLUBS)
    engine.set_state(
        GameState(
            players=[
                Player(hand=[], face_up_slots=[[first, second]]),
                Player(hand=[card_id(Rank.SIX, Suit.HEARTS)]),
            ],
            draw_pile=[],
            phase=Phase.FIXING_HANDS,
            current_player=0,
        )
    )

    assert engine.get_legal_actions()[ACTION_FIX_TAKE_FROM_STACK_SLOT_0]
    engine.step(ACTION_FIX_TAKE_FROM_STACK_SLOT_0)

    assert len(engine.state.players[0].face_up_slots[0]) == 1
    assert engine.state.players[0].hand == [second]


def test_auto_fix_hands_randomly_starts_with_lowest_card_holder():
    engine = IBFlipEngine(num_players=2, seed=1)
    low = card_id(Rank.THREE, Suit.HEARTS)
    engine.set_state(
        GameState(
            players=[
                Player(hand=[card_id(Rank.SIX, Suit.HEARTS)]),
                Player(hand=[low]),
            ],
            draw_pile=[],
            phase=Phase.FIXING_HANDS,
            current_player=0,
        )
    )

    engine.auto_fix_hands_randomly()

    assert engine.state.phase is Phase.MIDDLE_GAME
    assert engine.state.current_player == 1
    assert engine.get_legal_actions()[low]
