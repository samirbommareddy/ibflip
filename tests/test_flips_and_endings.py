from ibflip import IBFlipEngine
from ibflip.actions import ACTION_END_PLAY_GROUP
from ibflip.cards import Rank, Suit, card_id
from ibflip.state import FinishStatus, GameState, Phase, Player


def make_engine(state: GameState) -> IBFlipEngine:
    engine = IBFlipEngine(num_players=len(state.players), seed=5)
    engine.set_state(state)
    return engine


def test_ten_flips_live_cards_to_discard_and_player_plays_again():
    ten = card_id(Rank.TEN, Suit.HEARTS)
    previous = card_id(Rank.NINE, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[ten, card_id(Rank.KING, Suit.HEARTS)]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            live_cards=[previous],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(ten)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.live_cards == []
    assert previous in engine.state.discard_pile
    assert ten in engine.state.discard_pile
    assert engine.state.current_player == 0


def test_four_consecutive_cards_flip_live_pile():
    fourth = card_id(Rank.KING, Suit.SPADES)
    engine = make_engine(
        GameState(
            players=[Player(hand=[fourth, card_id(Rank.ACE, Suit.HEARTS)]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            live_cards=[
                card_id(Rank.KING, Suit.HEARTS),
                card_id(Rank.KING, Suit.DIAMONDS),
                card_id(Rank.KING, Suit.CLUBS),
            ],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(fourth)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.live_cards == []
    assert fourth in engine.state.discard_pile
    assert engine.state.current_player == 0


def test_flipping_threes_deals_one_three_to_each_other_player():
    fourth = card_id(Rank.THREE, Suit.SPADES)
    engine = make_engine(
        GameState(
            players=[
                Player(hand=[fourth, card_id(Rank.KING, Suit.CLUBS)]),
                Player(hand=[]),
                Player(hand=[]),
            ],
            live_cards=[
                card_id(Rank.THREE, Suit.HEARTS),
                card_id(Rank.THREE, Suit.DIAMONDS),
                card_id(Rank.THREE, Suit.CLUBS),
            ],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(fourth)
    engine.step(ACTION_END_PLAY_GROUP)

    assert len(engine.state.players[1].hand) == 1
    assert len(engine.state.players[2].hand) == 1
    assert all(engine.card(card).rank is Rank.THREE for card in engine.state.players[1].hand + engine.state.players[2].hand)


def test_flipping_fours_gives_flipper_a_three_from_discard_and_advances_turn():
    fourth = card_id(Rank.FOUR, Suit.SPADES)
    three = card_id(Rank.THREE, Suit.HEARTS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[fourth]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            live_cards=[
                card_id(Rank.FOUR, Suit.HEARTS),
                card_id(Rank.FOUR, Suit.DIAMONDS),
                card_id(Rank.FOUR, Suit.CLUBS),
            ],
            discard_pile=[three],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(fourth)
    engine.step(ACTION_END_PLAY_GROUP)

    assert three in engine.state.players[0].hand
    assert engine.state.current_player == 1


def test_flipping_eights_makes_flipper_lose():
    fourth = card_id(Rank.EIGHT, Suit.SPADES)
    engine = make_engine(
        GameState(
            players=[Player(hand=[fourth]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            live_cards=[
                card_id(Rank.EIGHT, Suit.HEARTS),
                card_id(Rank.EIGHT, Suit.DIAMONDS),
                card_id(Rank.EIGHT, Suit.CLUBS),
            ],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(fourth)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.players[0].finish_status is FinishStatus.ILLEGAL_LOSS
    assert engine.state.loser == 0
    assert engine.state.phase is Phase.GAME_OVER


def test_flipping_nines_promotes_existing_discard_pile_to_live_cards():
    fourth = card_id(Rank.NINE, Suit.SPADES)
    old_discard = [card_id(Rank.KING, Suit.HEARTS), card_id(Rank.JACK, Suit.CLUBS)]
    old_live = [
        card_id(Rank.NINE, Suit.HEARTS),
        card_id(Rank.NINE, Suit.DIAMONDS),
        card_id(Rank.NINE, Suit.CLUBS),
    ]
    engine = make_engine(
        GameState(
            players=[Player(hand=[fourth, card_id(Rank.ACE, Suit.CLUBS)]), Player(hand=[card_id(Rank.QUEEN, Suit.CLUBS)])],
            live_cards=old_live.copy(),
            discard_pile=old_discard.copy(),
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(fourth)
    engine.step(ACTION_END_PLAY_GROUP)

    assert sorted(engine.state.live_cards) == sorted(old_discard)
    assert sorted(engine.state.discard_pile) == sorted(old_live + [fourth])
    assert engine.state.current_player == 0


def test_finishing_on_two_is_illegal_because_player_would_play_again():
    two = card_id(Rank.TWO, Suit.HEARTS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[two]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            live_cards=[card_id(Rank.ACE, Suit.CLUBS)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(two)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.players[0].finish_status is FinishStatus.ILLEGAL_LOSS
    assert engine.state.loser == 0
