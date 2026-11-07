"""Rulebook examples and cross-layer regressions; no cloud or training needed."""
from copy import deepcopy
import random

import numpy as np
import pytest
from pettingzoo.test import api_test

from ibflip import IBFlipEngine, IllegalActionError
from ibflip.actions import ACTION_END_PLAY_GROUP, ACTION_FIX_STACK_SLOT_0, ACTION_FIX_SWAP_SLOT_0
from ibflip.ai.observation import encode
from ibflip.cards import Rank, Suit, card_id
from ibflip.env import IBFlipAECEnv
from ibflip.rules import can_play_on, can_play_on_index
from ibflip.state import GameState, Phase, Player


def c(rank, suit=Suit.HEARTS):
    return card_id(rank, suit)


def engine_for(players, **kwargs):
    engine = IBFlipEngine(len(players), seed=1)
    engine.set_state(GameState(players=players, phase=Phase.MIDDLE_GAME, **kwargs))
    return engine


def test_complete_pdf_playability_matrix():
    # Independent transcription of the PDF, rows are played ranks.
    rows = {
        Rank.ACE: 'A 2 3 6 7 8 9 J Q K', Rank.TWO: 'A 2 3 6 7 8 9 J Q K',
        Rank.THREE: '2 3 7', Rank.FOUR: 'A 2 3 4 6 7 8 9 J Q K',
        Rank.FIVE: 'A 2 3 4 6 7 8 9 J Q K', Rank.SIX: '2 3 4 6 7',
        Rank.SEVEN: 'A 2 3 6 7 8 9 J Q K', Rank.EIGHT: '2 3 6 8',
        Rank.NINE: '2 3 6 8 9', Rank.TEN: 'A 2 3 6 8 9 J Q K',
        Rank.JACK: '2 3 6 8 9 J', Rank.QUEEN: '2 3 6 8 9 J Q',
        Rank.KING: '2 3 6 8 9 J Q K',
    }
    symbols = dict(zip(Rank, '3 4 5 6 7 8 9 10 J Q K A 2'.split()))
    for played in Rank:
        assert can_play_on(played, None)
        for target in Rank:
            expected = symbols[target] in rows[played].split()
            assert can_play_on(played, target) == expected
            assert can_play_on_index(int(played), int(target)) == expected


@pytest.mark.parametrize('n', [0, 1, 6, 7])
def test_unsupported_table_sizes_fail_before_dealing(n):
    with pytest.raises(ValueError):
        IBFlipEngine(n)


def test_last_hand_card_does_not_merge_with_a_face_up_slot():
    queen, other = c(Rank.QUEEN), c(Rank.QUEEN, Suit.DIAMONDS)
    engine = engine_for([Player(hand=[queen], face_up_slots=[[other]]), Player(hand=[c(Rank.KING)])])
    engine.step(queen)
    assert engine.get_legal_action_indices() == [ACTION_END_PLAY_GROUP]
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.current_player == 1


@pytest.mark.parametrize('simultaneous', [False, True])
def test_fix_swap_is_one_for_one_and_never_creates_a_mixed_stack(simultaneous):
    queen, other, king = c(Rank.QUEEN), c(Rank.QUEEN, Suit.DIAMONDS), c(Rank.KING)
    engine = engine_for([Player(hand=[king], face_up_slots=[[queen, other]]), Player(hand=[c(Rank.TWO)])])
    engine.state.phase = Phase.FIXING_HANDS
    before = deepcopy(engine.state)
    if simultaneous:
        with pytest.raises(IllegalActionError):
            engine.fix_swap_card(0, king, 0)
        assert engine.state == before
    else:
        # Unusable selections should not be offered at all.
        assert king not in engine.get_legal_action_indices()


@pytest.mark.parametrize('simultaneous', [False, True])
def test_fix_can_merge_face_up_cards_and_preserve_every_card(simultaneous):
    queen, other = c(Rank.QUEEN), c(Rank.QUEEN, Suit.DIAMONDS)
    engine = engine_for([Player(hand=[c(Rank.KING)], face_up_slots=[[queen], [other]]), Player(hand=[c(Rank.TWO)])], draw_pile=[c(Rank.JACK)])
    engine.state.phase = Phase.FIXING_HANDS
    if simultaneous:
        engine.fix_stack_card(0, other, 0)
    else:
        engine.step(other)
        engine.step(ACTION_FIX_STACK_SLOT_0)
    player = engine.state.players[0]
    assert player.face_up_slots == [[queen, other], []]
    assert player.hand == [c(Rank.KING)]
    assert engine.state.draw_pile == [c(Rank.JACK)]


def test_ready_players_cannot_change_cards_via_engine_api():
    engine = IBFlipEngine(2, seed=3)
    engine.reset()
    engine.fix_done(0)
    before = deepcopy(engine.state)
    with pytest.raises(IllegalActionError):
        engine.fix_swap_card(0, engine.state.players[0].hand[0], 0)
    assert engine.state == before


def test_env_infos_follow_the_new_current_player_and_illegal_actions_do_not_skip():
    env = IBFlipAECEnv(3, seed=5)
    env.reset()
    env.engine = engine_for([Player(hand=[c(Rank.JACK), c(Rank.KING)]), Player(hand=[c(Rank.QUEEN)]), Player(hand=[c(Rank.TWO)])])
    env.agent_selection = 'player_0'
    before = deepcopy(env.engine.state)
    with pytest.raises(IllegalActionError):
        env.step(69)
    assert env.engine.state == before
    env.step(c(Rank.JACK))
    env.step(ACTION_END_PLAY_GROUP)
    assert env.agent_selection == 'player_1'
    for agent in env.agents:
        np.testing.assert_array_equal(env.infos[agent]['action_mask'], env.observe(agent)['action_mask'])
    assert env.infos['player_1']['action_mask'][c(Rank.QUEEN)]


@pytest.mark.parametrize('n', [3, 4, 5])
def test_multiplayer_aec_contract(n):
    env = IBFlipAECEnv(n, seed=19, max_steps=100)
    env.reset()
    assert env.observe('player_0')['opponent_face_down_count'] == 3 * (n - 1)
    api_test(env, num_cycles=110)


@pytest.mark.parametrize('n', [2, 3, 4, 5])
def test_random_games_preserve_cards_knowledge_turns_and_unique_places(n):
    for seed in range(30):
        engine = IBFlipEngine(n, seed=seed)
        engine.record_events = False
        engine.reset()
        engine.auto_fix_hands_randomly()
        rng = random.Random(seed)
        for _ in range(10000):
            state = engine.state
            cards = state.draw_pile + state.live_cards + state.discard_pile
            for player in state.players:
                cards += player.hand + [v for slot in player.face_up_slots for v in slot] + [v for v in player.face_down_slots if v is not None]
                assert len(player.known_hand) == len(set(player.known_hand))
                assert set(player.known_hand) <= set(player.hand)
                assert all(len({engine.rank(v) for v in slot}) <= 1 for slot in player.face_up_slots)
            assert sorted(cards) == list(range(52))
            places = [p.place for p in state.players if p.place is not None]
            assert len(places) == len(set(places))
            if state.phase is Phase.GAME_OVER:
                assert sorted(places) == list(range(1, n + 1))
                break
            assert state.players[state.current_player].active
            legal = engine.get_legal_action_indices()
            assert legal
            engine.step(rng.choice(legal))
        else:
            pytest.fail(f'game exceeded audit cap: {n=} {seed=}')


def test_policy_observation_does_not_depend_on_hidden_card_assignment():
    engine = IBFlipEngine(5, seed=7)
    engine.reset()
    engine.auto_fix_hands_randomly()
    me = engine.state.current_player
    before = encode(engine, me)
    locations = [(engine.state.draw_pile, i) for i in range(len(engine.state.draw_pile))]
    for index, player in enumerate(engine.state.players):
        locations += [(player.face_down_slots, i) for i in range(3)]
        if index != me:
            locations += [(player.hand, i) for i, value in enumerate(player.hand) if value not in player.known_hand]
    values = [container[i] for container, i in locations][::-1]
    for (container, i), value in zip(locations, values):
        container[i] = value
    np.testing.assert_array_equal(before, encode(engine, me))


def test_bot_activity_does_not_extend_abandoned_room_lifetime():
    import time
    from ibflip_web.rooms import Room, ROOM_TTL_SECONDS
    room = Room(code='AUDITT')
    room.add_human('away')
    room.add_bot()
    room.start()
    room.seats[0].last_seen = time.time() - ROOM_TTL_SECONDS - 10
    room.touch()  # also what a bot turn does
    assert room.expired()


@pytest.mark.parametrize('direction', [-1, 1])
@pytest.mark.parametrize('active', [[True, False, True, False, True], [False, True, False, True, False]])
def test_turns_and_skips_count_only_remaining_players(direction, active):
    engine = engine_for([Player(hand=[i], active=value) for i, value in enumerate(active)], direction=direction)
    for start in range(5):
        for count in range(1, 7):
            index, remaining = start, count
            while remaining:
                index = (index + direction) % 5
                remaining -= active[index]
            assert engine._advance_index(start, count) == index


def test_fixing_masks_never_offer_a_dead_end_selection():
    from ibflip.actions import ACTION_FIX_DONE
    engine = IBFlipEngine(5, seed=12)
    engine.reset()
    rng = random.Random(12)
    for _ in range(500):
        if engine.state.phase is not Phase.FIXING_HANDS:
            break
        legal = engine.get_legal_action_indices()
        assert legal
        engine.step(rng.choice(legal))
    else:
        pytest.fail('fixing did not finish')


def test_start_with_empty_hands_after_fixing_uses_visible_cards():
    engine = engine_for([Player(face_up_slots=[[c(Rank.THREE)]]), Player(face_up_slots=[[c(Rank.SIX)]])])
    engine.state.phase = Phase.FIXING_HANDS
    engine.fix_done(0)
    engine.fix_done(1)
    assert engine.get_legal_action_indices() == [c(Rank.THREE)]
    engine.step(c(Rank.THREE))
    engine.step(ACTION_END_PLAY_GROUP)
    assert engine.state.winner == 0


def test_face_up_combination_over_the_websocket_protocol():
    from fastapi.testclient import TestClient
    from ibflip_web.main import app, registry
    with TestClient(app) as client:
        created = client.post('/api/rooms', json={'name': 'Audit', 'bots': ['easy'], 'autostart': True}).json()
        room = registry.get(created['code'])
        player = room.engine.state.players[0]
        # Keep the original deal intact: find two equal visible/hand ranks,
        # or use a complete deterministic deal with every card accounted for.
        used = [36, 37, 40, 32, 33, 34]
        player.face_up_slots = [[36], [37], [40]]
        player.hand = [32, 33, 34]
        player.face_down_slots = [0, 1, 2]
        used += [0, 1, 2]
        rest = [v for v in range(52) if v not in used]
        other = room.engine.state.players[1]
        other.hand, other.face_up_slots, other.face_down_slots = rest[:3], [[rest[3]], [rest[4]], [rest[5]]], rest[6:9]
        room.engine.state.draw_pile = rest[9:]
        with client.websocket_connect(f"/ws/{room.code}?token={created['token']}") as ws:
            ws.receive_json()
            ws.send_json({'type': 'fix', 'op': 'stack', 'card': 37, 'slot': 0})
            message = ws.receive_json()
            assert message['type'] == 'state'
            assert message['game']['players'][0]['face_up'] == [[36, 37], [], [40]]
            assert message['game']['hand'] == [32, 33, 34]
