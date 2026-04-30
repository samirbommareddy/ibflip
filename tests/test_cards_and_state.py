from copy import deepcopy

from ibflip import IBFlipEngine
from ibflip.cards import Rank, Suit, card_id, full_deck
from ibflip.state import GameState, Phase, Player


def test_deck_has_stable_integer_identity():
    deck = full_deck()

    assert len(deck) == 52
    assert [card.card_id for card in deck] == list(range(52))
    assert deck[card_id(Rank.THREE, Suit.HEARTS)].rank is Rank.THREE
    assert deck[card_id(Rank.ACE, Suit.SPADES)].suit is Suit.SPADES


def test_game_state_is_deepcopy_isolated():
    engine = IBFlipEngine(num_players=2, seed=7)
    engine.reset()
    clone = deepcopy(engine.state)

    clone.players[0].hand.append(card_id(Rank.FIVE, Suit.HEARTS))
    clone.live_cards.append(card_id(Rank.SIX, Suit.CLUBS))

    assert clone.players[0].hand != engine.state.players[0].hand
    assert clone.live_cards != engine.state.live_cards


def test_engine_clone_restores_independent_rng_and_state():
    engine = IBFlipEngine(num_players=2, seed=11)
    engine.set_state(
        GameState(
            players=[
                Player(hand=[card_id(Rank.NINE, Suit.HEARTS)]),
                Player(hand=[card_id(Rank.JACK, Suit.CLUBS)]),
            ],
            draw_pile=[],
            live_cards=[card_id(Rank.SIX, Suit.DIAMONDS)],
            discard_pile=[
                card_id(Rank.TWO, Suit.HEARTS),
                card_id(Rank.KING, Suit.SPADES),
            ],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    clone = engine.clone()
    engine.step(card_id(Rank.NINE, Suit.HEARTS))
    engine.step(55)
    engine.step(53)

    assert clone.state.players[0].hand == [card_id(Rank.NINE, Suit.HEARTS)]
    assert clone.state.live_cards == [card_id(Rank.SIX, Suit.DIAMONDS)]
