from ibflip import IBFlipEngine
from ibflip.actions import (
    ACTION_END_PLAY_GROUP,
    ACTION_PICK_UP_LIVE_PILE,
    ACTION_RESOLVE_NINE_DRAW,
    ACTION_REVEAL_DRAW_PILE_TOP,
)
from ibflip.cards import Rank, Suit, card_id
from ibflip.state import GameState, PendingKind, Phase, Player


def make_engine(state: GameState) -> IBFlipEngine:
    engine = IBFlipEngine(num_players=len(state.players), seed=3)
    engine.set_state(state)
    return engine


def test_normal_play_locks_group_rank_until_commit():
    three_h = card_id(Rank.THREE, Suit.HEARTS)
    three_d = card_id(Rank.THREE, Suit.DIAMONDS)
    six = card_id(Rank.SIX, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[three_h, three_d, six]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            live_cards=[card_id(Rank.TWO, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(three_h)
    mask = engine.get_legal_actions()

    assert mask[three_d]
    assert not mask[six]
    assert mask[ACTION_END_PLAY_GROUP]
    assert len(mask) == engine.action_space_size


def test_two_sets_play_again_without_nested_loop():
    two = card_id(Rank.TWO, Suit.HEARTS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[two, card_id(Rank.KING, Suit.CLUBS)]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            live_cards=[card_id(Rank.ACE, Suit.HEARTS)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(two)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.current_player == 0
    assert engine.state.pending is None


def test_three_reverses_direction_on_odd_count():
    three = card_id(Rank.THREE, Suit.HEARTS)
    engine = make_engine(
        GameState(
            players=[
                Player(hand=[three, card_id(Rank.KING, Suit.HEARTS)]),
                Player(hand=[card_id(Rank.JACK, Suit.CLUBS)]),
                Player(hand=[card_id(Rank.QUEEN, Suit.CLUBS)]),
            ],
            live_cards=[card_id(Rank.TWO, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(three)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.direction == -1
    assert engine.state.current_player == 2


def test_eight_skips_matching_number_of_turns():
    eight = card_id(Rank.EIGHT, Suit.HEARTS)
    engine = make_engine(
        GameState(
            players=[
                Player(hand=[eight, card_id(Rank.KING, Suit.HEARTS)]),
                Player(hand=[card_id(Rank.JACK, Suit.CLUBS)]),
                Player(hand=[card_id(Rank.QUEEN, Suit.CLUBS)]),
                Player(hand=[card_id(Rank.KING, Suit.CLUBS)]),
            ],
            live_cards=[card_id(Rank.SIX, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(eight)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.current_player == 2


def test_five_makes_next_player_play_on_card_beneath_it():
    five = card_id(Rank.FIVE, Suit.HEARTS)
    jack = card_id(Rank.JACK, Suit.CLUBS)
    queen = card_id(Rank.QUEEN, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[five, card_id(Rank.KING, Suit.HEARTS)]), Player(hand=[jack, queen])],
            live_cards=[card_id(Rank.QUEEN, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(five)
    engine.step(ACTION_END_PLAY_GROUP)
    mask = engine.get_legal_actions()

    assert mask[queen]
    assert not mask[jack]


def test_four_loop_allows_only_four_five_six_or_pickup():
    four = card_id(Rank.FOUR, Suit.HEARTS)
    six = card_id(Rank.SIX, Suit.CLUBS)
    jack = card_id(Rank.JACK, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[four, card_id(Rank.KING, Suit.HEARTS)]), Player(hand=[six, jack])],
            live_cards=[card_id(Rank.KING, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(four)
    engine.step(ACTION_END_PLAY_GROUP)
    mask = engine.get_legal_actions()

    assert engine.state.pending.kind is PendingKind.FOUR_LOOP
    assert mask[six]
    assert not mask[jack]
    assert mask[ACTION_PICK_UP_LIVE_PILE]


def test_nine_uses_forced_rng_draw_action_and_resolves_drawn_card():
    nine = card_id(Rank.NINE, Suit.HEARTS)
    two = card_id(Rank.TWO, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[nine, card_id(Rank.KING, Suit.CLUBS)]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            live_cards=[card_id(Rank.SIX, Suit.SPADES)],
            discard_pile=[two],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(nine)
    engine.step(ACTION_END_PLAY_GROUP)
    mask = engine.get_legal_actions()

    assert engine.state.pending.kind is PendingKind.NINE_DRAW
    assert mask == [i == ACTION_RESOLVE_NINE_DRAW for i in range(engine.action_space_size)]

    engine.step(ACTION_RESOLVE_NINE_DRAW)

    assert two in engine.state.live_cards
    assert engine.state.current_player == 0


def test_revealed_nine_uses_same_forced_draw_state():
    nine = card_id(Rank.NINE, Suit.HEARTS)
    drawn = card_id(Rank.TWO, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[card_id(Rank.THREE, Suit.HEARTS)]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            draw_pile=[nine],
            live_cards=[card_id(Rank.SIX, Suit.SPADES)],
            discard_pile=[drawn],
            phase=Phase.EARLY_GAME,
            current_player=0,
        )
    )

    engine.step(ACTION_REVEAL_DRAW_PILE_TOP)

    assert engine.state.pending.kind is PendingKind.NINE_DRAW
    assert engine.get_legal_actions()[ACTION_RESOLVE_NINE_DRAW]


def test_early_game_draws_player_back_to_three_after_commit():
    jack = card_id(Rank.JACK, Suit.HEARTS)
    draw_one = card_id(Rank.KING, Suit.CLUBS)
    draw_two = card_id(Rank.ACE, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[jack]), Player(hand=[card_id(Rank.QUEEN, Suit.CLUBS)])],
            draw_pile=[draw_one, draw_two],
            live_cards=[card_id(Rank.NINE, Suit.SPADES)],
            phase=Phase.EARLY_GAME,
            current_player=0,
        )
    )

    engine.step(jack)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.players[0].hand == [draw_one, draw_two]
    assert engine.state.phase is Phase.MIDDLE_GAME


def test_ace_played_on_seven_becomes_one_and_resets_target_to_zero():
    ace = card_id(Rank.ACE, Suit.HEARTS)
    three = card_id(Rank.THREE, Suit.CLUBS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[ace, card_id(Rank.KING, Suit.HEARTS)]), Player(hand=[three])],
            live_cards=[card_id(Rank.SEVEN, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    engine.step(ace)
    engine.step(ACTION_END_PLAY_GROUP)

    assert ace in engine.state.ace_as_one_card_ids
    assert engine.get_legal_actions()[three]


def test_reveal_draw_pile_top_plays_legal_card_or_picks_up_illegal_card():
    legal = card_id(Rank.JACK, Suit.HEARTS)
    illegal = card_id(Rank.EIGHT, Suit.HEARTS)

    engine = make_engine(
        GameState(
            players=[Player(hand=[card_id(Rank.THREE, Suit.HEARTS)]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            draw_pile=[legal],
            live_cards=[card_id(Rank.NINE, Suit.SPADES)],
            phase=Phase.EARLY_GAME,
            current_player=0,
        )
    )
    engine.step(ACTION_REVEAL_DRAW_PILE_TOP)
    assert legal in engine.state.live_cards

    engine = make_engine(
        GameState(
            players=[Player(hand=[card_id(Rank.THREE, Suit.HEARTS)]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            draw_pile=[illegal],
            live_cards=[card_id(Rank.JACK, Suit.SPADES)],
            phase=Phase.EARLY_GAME,
            current_player=0,
        )
    )
    engine.step(ACTION_REVEAL_DRAW_PILE_TOP)
    assert illegal in engine.state.players[0].hand
    assert engine.state.live_cards == []


def test_middle_game_uses_face_up_cards_only_after_hand_empty():
    face_up = card_id(Rank.JACK, Suit.HEARTS)
    hand = card_id(Rank.KING, Suit.HEARTS)
    engine = make_engine(
        GameState(
            players=[Player(hand=[hand], face_up_slots=[[face_up]]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            live_cards=[card_id(Rank.NINE, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )

    assert not engine.get_legal_actions()[face_up]
    assert engine.get_legal_actions()[hand]

    engine.state.players[0].hand.clear()
    mask = engine.get_legal_actions()
    assert mask[face_up]


def test_face_down_illegal_attempt_is_revealed_then_added_to_hand_with_pickup():
    hidden = card_id(Rank.EIGHT, Suit.HEARTS)
    engine = make_engine(
        GameState(
            players=[Player(face_down_slots=[hidden]), Player(hand=[card_id(Rank.JACK, Suit.CLUBS)])],
            live_cards=[card_id(Rank.JACK, Suit.SPADES)],
            phase=Phase.END_GAME,
            current_player=0,
        )
    )

    engine.step(67)

    assert hidden in engine.state.players[0].hand
    assert engine.state.live_cards == []
    assert engine.state.current_player == 1
