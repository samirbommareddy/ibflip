"""User rulings: pickup choice/obligation, one draw for several 9s, and
games that run until every player is placed."""

import random

import numpy as np

from ibflip import IBFlipEngine
from ibflip.actions import (
    ACTION_END_PLAY_GROUP,
    ACTION_PICK_UP_LIVE_PILE,
    ACTION_RESOLVE_NINE_DRAW,
    ACTION_REVEAL_DRAW_PILE_TOP,
)
from ibflip.ai.agents import HeuristicAgent, NeuralAgent, RandomAgent, model_available
from ibflip.ai.arena import play_game, score
from ibflip.ai.observation import OBS_SIZE, compact_legal, encode
from ibflip.cards import Rank, Suit, card_id
from ibflip.state import FinishStatus, GameState, PendingEffect, PendingKind, Phase, Player
from ibflip_web.serialize import serialize_view


def make_engine(state: GameState) -> IBFlipEngine:
    engine = IBFlipEngine(num_players=len(state.players), seed=3)
    engine.set_state(state)
    return engine


def c(rank: Rank, suit: Suit = Suit.HEARTS) -> int:
    return card_id(rank, suit)


def filler(n: int = 1) -> list[int]:
    # Cards that keep a player in the game without mattering.
    return [c(Rank.KING, s) for s in list(Suit)[:n]]


def out(place: int, status: FinishStatus) -> Player:
    return Player(place=place, active=False, finish_status=status)


# ------------------------------------------------------------ ruling 1
def test_early_game_blocked_player_may_reveal_or_pick_up():
    engine = make_engine(
        GameState(
            players=[Player(hand=[c(Rank.EIGHT), c(Rank.NINE), c(Rank.JACK)]), Player(hand=filler())],
            draw_pile=[c(Rank.TWO, Suit.CLUBS), c(Rank.ACE, Suit.CLUBS)],
            live_cards=[c(Rank.SEVEN, Suit.SPADES)],
            phase=Phase.EARLY_GAME,
            current_player=0,
        )
    )
    legal = engine.get_legal_action_indices()
    assert set(legal) == {ACTION_REVEAL_DRAW_PILE_TOP, ACTION_PICK_UP_LIVE_PILE}
    view = serialize_view(engine, 0, "playing")
    assert view["legal"]["reveal"] and view["legal"]["pick_up"]

    engine.step(ACTION_PICK_UP_LIVE_PILE)
    assert c(Rank.SEVEN, Suit.SPADES) in engine.state.players[0].hand
    assert len(engine.state.draw_pile) == 2  # nothing revealed
    assert engine.state.current_player == 1


def test_early_game_player_with_a_play_cannot_pick_up_or_reveal():
    engine = make_engine(
        GameState(
            players=[Player(hand=[c(Rank.EIGHT), c(Rank.NINE), c(Rank.SEVEN)]), Player(hand=filler())],
            draw_pile=[c(Rank.TWO, Suit.CLUBS)],
            live_cards=[c(Rank.SEVEN, Suit.SPADES)],
            phase=Phase.EARLY_GAME,
            current_player=0,
        )
    )
    assert engine.get_legal_action_indices() == [c(Rank.SEVEN)]


# ------------------------------------------------------------ ruling 2
def _four_loop_state(**player_kwargs) -> GameState:
    return GameState(
        players=[Player(**player_kwargs), Player(hand=filler())],
        live_cards=[c(Rank.KING, Suit.SPADES), c(Rank.FOUR, Suit.SPADES)],
        pending=PendingEffect(PendingKind.FOUR_LOOP, 1),
        phase=Phase.MIDDLE_GAME,
        current_player=0,
    )


def test_four_loop_no_pickup_when_a_four_five_or_six_is_playable():
    for rank in (Rank.FOUR, Rank.FIVE, Rank.SIX):
        engine = make_engine(_four_loop_state(hand=[c(rank), c(Rank.JACK)]))
        assert engine.get_legal_action_indices() == [c(rank)]


def test_four_loop_pickup_when_blocked_including_face_up_source():
    engine = make_engine(_four_loop_state(hand=[c(Rank.JACK), c(Rank.TWO)]))
    assert engine.get_legal_action_indices() == [ACTION_PICK_UP_LIVE_PILE]

    # Hand empty: the face-up cards decide.
    engine = make_engine(_four_loop_state(face_up_slots=[[c(Rank.SIX)], [c(Rank.JACK)]], face_down_slots=[c(Rank.TWO)]))
    assert engine.get_legal_action_indices() == [c(Rank.SIX)]
    engine = make_engine(_four_loop_state(face_up_slots=[[c(Rank.JACK)]], face_down_slots=[c(Rank.TWO)]))
    assert engine.get_legal_action_indices() == [ACTION_PICK_UP_LIVE_PILE]


# ------------------------------------------------------------ ruling 3
def test_several_nines_played_together_draw_one_random_card():
    nines = [c(Rank.NINE, s) for s in (Suit.HEARTS, Suit.DIAMONDS)]
    discard = [c(Rank.KING, Suit.CLUBS), c(Rank.JACK, Suit.CLUBS), c(Rank.QUEEN, Suit.CLUBS)]
    engine = make_engine(
        GameState(
            players=[Player(hand=nines + filler()), Player(hand=[c(Rank.KING, Suit.SPADES)])],
            live_cards=[c(Rank.SIX, Suit.SPADES)],
            discard_pile=list(discard),
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.step(nines[0])
    engine.step(nines[1])
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.get_legal_action_indices() == [ACTION_RESOLVE_NINE_DRAW]
    engine.step(ACTION_RESOLVE_NINE_DRAW)

    assert engine.state.pending is None
    assert len(engine.state.discard_pile) == 2
    assert engine.state.live_cards[:3] == [c(Rank.SIX, Suit.SPADES)] + nines
    assert len(engine.state.live_cards) == 4 and engine.state.live_cards[-1] in discard
    assert engine.state.current_player == 1


# ------------------------------------------------------------ ruling 4
def test_legal_finisher_takes_first_place_and_the_game_goes_on():
    jack = c(Rank.JACK)
    engine = make_engine(
        GameState(
            players=[Player(hand=[jack]), Player(hand=filler()), Player(hand=[c(Rank.QUEEN, Suit.CLUBS)])],
            live_cards=[c(Rank.NINE, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.step(jack)
    engine.step(ACTION_END_PLAY_GROUP)

    p0 = engine.state.players[0]
    assert p0.finish_status is FinishStatus.LEGAL_WIN and p0.place == 1 and not p0.active
    assert engine.state.winner == 0 and engine.state.loser is None
    assert engine.state.phase is not Phase.GAME_OVER
    assert engine.state.current_player == 1
    view = serialize_view(engine, 0, "playing")
    assert view["players"][0]["place"] == 1 and view["players"][0]["finish"] == "legal"
    assert view["players"][1]["place"] is None and view["players"][1]["finish"] is None
    assert view["legal"]["cards"] == [] and not view["legal"]["pick_up"]  # spectating


def test_finished_players_are_skipped_in_turn_order():
    king = c(Rank.KING, Suit.SPADES)
    engine = make_engine(
        GameState(
            players=[Player(hand=[king, c(Rank.KING, Suit.CLUBS)]), out(1, FinishStatus.LEGAL_WIN), Player(hand=filler())],
            live_cards=[c(Rank.NINE, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.step(king)
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.current_player == 2


def test_illegal_finisher_takes_last_place_and_next_player_continues():
    two = c(Rank.TWO)
    engine = make_engine(
        GameState(
            players=[Player(hand=[two]), Player(hand=filler()), Player(hand=filler())],
            live_cards=[c(Rank.NINE, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.step(two)
    engine.step(ACTION_END_PLAY_GROUP)

    p0 = engine.state.players[0]
    assert p0.finish_status is FinishStatus.ILLEGAL_LOSS and p0.place == 3
    assert engine.state.loser == 0 and engine.state.winner is None
    assert engine.state.phase is not Phase.GAME_OVER
    assert engine.state.current_player == 1


def test_eight_with_two_players_remaining_is_an_illegal_finish():
    # Three seats, one already out: an 8 skips the only other player.
    eight = c(Rank.EIGHT)
    engine = make_engine(
        GameState(
            players=[Player(hand=[eight]), out(1, FinishStatus.LEGAL_WIN), Player(hand=filler())],
            live_cards=[c(Rank.SIX, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.step(eight)
    engine.step(ACTION_END_PLAY_GROUP)

    assert engine.state.players[0].finish_status is FinishStatus.ILLEGAL_LOSS
    assert [p.place for p in engine.state.players] == [3, 1, 2]
    assert engine.state.phase is Phase.GAME_OVER
    assert (engine.state.winner, engine.state.loser) == (1, 0)


def test_eight_with_three_players_remaining_is_a_legal_finish():
    eight = c(Rank.EIGHT)
    engine = make_engine(
        GameState(
            players=[Player(hand=[eight]), Player(hand=filler()), Player(hand=filler())],
            live_cards=[c(Rank.SIX, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
        )
    )
    engine.step(eight)
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.players[0].place == 1
    assert engine.state.current_player == 2  # player 1 skipped


def test_eights_flipper_takes_last_place_below_an_earlier_illegal_finisher():
    eights = [c(Rank.EIGHT, s) for s in Suit]
    engine = make_engine(
        GameState(
            players=[
                Player(hand=[eights[3], c(Rank.KING, Suit.CLUBS)]),
                Player(hand=filler()),
                Player(hand=filler(2)),
                out(4, FinishStatus.ILLEGAL_LOSS),
            ],
            live_cards=eights[:3],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
            loser=3,
        )
    )
    engine.step(eights[3])
    engine.step(ACTION_END_PLAY_GROUP)

    players = engine.state.players
    assert players[0].finish_status is FinishStatus.EIGHTS_LOSS
    assert players[0].place == 4 and players[3].place == 3
    assert engine.state.loser == 0
    assert engine.state.phase is not Phase.GAME_OVER
    assert engine.state.current_player == 1
    assert serialize_view(engine, 1, "playing")["players"][0]["finish"] == "eights"


def test_last_player_left_after_illegal_finishers_wins():
    two = c(Rank.TWO)
    engine = make_engine(
        GameState(
            players=[Player(hand=[two]), Player(hand=filler()), out(3, FinishStatus.ILLEGAL_LOSS)],
            live_cards=[c(Rank.NINE, Suit.SPADES)],
            phase=Phase.MIDDLE_GAME,
            current_player=0,
            loser=2,
        )
    )
    engine.step(two)
    engine.step(ACTION_END_PLAY_GROUP)
    assert [p.place for p in engine.state.players] == [2, 1, 3]
    assert engine.state.phase is Phase.GAME_OVER
    assert (engine.state.winner, engine.state.loser) == (1, 2)


def _check_complete_game(engine: IBFlipEngine) -> None:
    n = engine.num_players
    places = [p.place for p in engine.state.players]
    assert sorted(places) == list(range(1, n + 1))
    assert engine.state.winner == places.index(1)
    assert engine.state.loser == places.index(n)
    losers = [q for q in engine.state.players if q.finish_status in (FinishStatus.ILLEGAL_LOSS, FinishStatus.EIGHTS_LOSS)]
    for player in engine.state.players:
        if player.finish_status is FinishStatus.LEGAL_WIN:
            assert all(player.place < q.place for q in losers)


def test_random_three_and_four_player_games_place_everyone():
    for num_players in (3, 4):
        for seed in range(40):
            engine = IBFlipEngine(num_players, seed=seed)
            engine.reset()
            engine.auto_fix_hands_randomly()
            rng = random.Random(seed)
            for _ in range(20000):
                if engine.state.phase is Phase.GAME_OVER:
                    break
                assert engine.state.players[engine.state.current_player].active
                engine.step(rng.choice(engine.get_legal_action_indices()))
            assert engine.state.phase is Phase.GAME_OVER, seed
            _check_complete_game(engine)
            # Everyone but the last one standing finished (or flipped the 8s).
            assert sum(p.finish_status is not None for p in engine.state.players) == num_players - 1


def test_bot_games_run_to_full_placements_and_score_is_linear():
    for num_players in (3, 4):
        agents = [HeuristicAgent() for _ in range(num_players)]
        result = play_game(agents, seed=num_players)
        assert sorted(result["places"]) == list(range(1, num_players + 1))
        scores = [score(result, seat, num_players) for seat in range(num_players)]
        assert abs(sum(scores)) < 1e-9
        assert scores[result["winner"]] == 1.0 and scores[result["loser"]] == -1.0
    assert score({"winner": None, "loser": None, "places": [1, None, 2]}, 1, 3) == 0.0
    assert abs(score({"places": [2, 1, 3, 4]}, 0, 4) - 1.0 / 3) < 1e-9


def test_trained_model_still_loads_and_plays_with_finished_opponents():
    assert model_available()
    agents = [NeuralAgent(seed=i) for i in range(3)] + [RandomAgent()]
    result = play_game(agents, seed=11)
    assert sorted(result["places"]) == [1, 2, 3, 4]
    # Observation / action shapes are unchanged.
    engine = IBFlipEngine(3, seed=1)
    engine.reset()
    engine.auto_fix_hands_randomly()
    assert encode(engine, engine.state.current_player).shape == (OBS_SIZE,)
    mask, _ = compact_legal(engine)
    assert mask.shape == (17,) and mask.dtype == np.bool_


def test_finished_human_spectates_until_the_game_is_over():
    from fastapi.testclient import TestClient

    from ibflip_web.main import app, registry

    jack = c(Rank.JACK)
    with TestClient(app) as client:
        created = client.post("/api/rooms", json={"name": "Me", "bots": ["medium", "medium"], "autostart": True}).json()
        room = registry.get(created["code"])
        room.bot_delay = 0.0
        room.engine.fix_done(0)
        room._after_fixing_check()
        fresh = IBFlipEngine(3, seed=5)
        fresh.reset()
        fresh.auto_fix_hands_randomly()
        state = fresh.state
        # Seat 0 holds a single jack and plays on a 9: a legal finish.
        state.players[0] = Player(hand=[jack])
        for card in [jack, c(Rank.NINE, Suit.SPADES)]:
            for other in state.players[1:]:
                if card in other.hand:
                    other.hand.remove(card)
                for slot in other.face_up_slots:
                    if card in slot:
                        slot.remove(card)
                if card in other.face_down_slots:
                    other.face_down_slots[other.face_down_slots.index(card)] = None
            if card in state.draw_pile:
                state.draw_pile.remove(card)
        state.live_cards = [c(Rank.NINE, Suit.SPADES)]
        state.current_player = 0
        state.required_start_card_id = None
        # Middle game, so playing the jack does not draw new cards.
        state.discard_pile, state.draw_pile = state.draw_pile, []
        state.phase = Phase.MIDDLE_GAME
        room.engine.set_state(state)
        room.engine.events = []
        with client.websocket_connect(f"/ws/{created['code']}?token={created['token']}") as ws:
            ws.receive_json()
            ws.send_json({"type": "action", "action": jack})
            ws.send_json({"type": "action", "action": ACTION_END_PLAY_GROUP})
            saw_spectating = False
            for _ in range(20000):
                msg = ws.receive_json()
                if msg["type"] != "state":
                    continue
                game = msg["game"]
                if game["players"][0]["place"] == 1 and game["status"] == "playing":
                    saw_spectating = True
                    assert game["players"][0]["finish"] == "legal"
                    assert game["legal"]["cards"] == [] and game["current"] != 0
                if game["status"] == "over":
                    break
            assert saw_spectating
            assert game["status"] == "over"
            assert sorted(p["place"] for p in game["players"]) == [1, 2, 3]
            assert game["winner"] == 0
