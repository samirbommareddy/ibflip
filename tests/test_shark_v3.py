from copy import deepcopy
import json
from pathlib import Path
import random

import numpy as np
import pytest

from ibflip import IBFlipEngine
from ibflip.actions import ACTION_END_PLAY_GROUP
from ibflip.ai.agents import HeuristicAgent, MLPPolicy, NeuralAgent
from ibflip.ai.arena import evaluate, game_result, play_game, score
from ibflip.ai.observation import (
    A_FACE_UP_SLOT_0, NUM_COMPACT_ACTIONS, OBS_SIZE, OBS_SIZE_V2,
    PLACEMENTS_OFFSET, SELF_SLOTS_OFFSET, SLOT_FEATURES, compact_legal, encode,
)
from ibflip.ai.provenance import build_manifest, schema
from ibflip.cards import Rank, Suit, card_id
from ibflip.state import FinishStatus, GameState, Phase, Player


def c(rank, suit=Suit.HEARTS):
    return card_id(rank, suit)


def slots_engine():
    e = IBFlipEngine(3, seed=3)
    e.set_state(GameState(players=[
        Player(face_up_slots=[[c(Rank.QUEEN)], [c(Rank.QUEEN, Suit.DIAMONDS), c(Rank.QUEEN, Suit.CLUBS)], [c(Rank.KING)]]),
        Player(hand=[c(Rank.TWO)]), Player(hand=[c(Rank.FIVE)]),
    ], phase=Phase.MIDDLE_GAME))
    return e


def weights(obs=OBS_SIZE, actions=NUM_COMPACT_ACTIONS):
    rng = np.random.default_rng(4)
    return {'w0': rng.normal(0, .1, (obs, 16)).astype(np.float32), 'b0': np.zeros(16, np.float32),
            'pw': rng.normal(0, .1, (16, actions)).astype(np.float32), 'pb': np.zeros(actions, np.float32)}


def test_slot_actions_choose_the_exact_stack_and_stay_there():
    e = slots_engine()
    mask, mapping = compact_legal(e)
    assert set(np.flatnonzero(mask)) == {17, 18, 19}
    assert mapping[17] == [c(Rank.QUEEN)]
    assert set(mapping[18]) == {c(Rank.QUEEN, Suit.DIAMONDS), c(Rank.QUEEN, Suit.CLUBS)}
    e.step(mapping[18][0])
    mask, mapping = compact_legal(e)
    assert set(np.flatnonzero(mask)) == {15, 18}
    e.step(mapping[18][0])
    assert e.get_legal_action_indices() == [ACTION_END_PLAY_GROUP]


def test_slot_partition_is_visible_without_changing_legacy_prefix():
    e = slots_engine()
    before = encode(e, 0)
    e.state.players[0].face_up_slots[0].append(e.state.players[0].face_up_slots[1].pop())
    after = encode(e, 0)
    np.testing.assert_array_equal(before[:OBS_SIZE_V2], after[:OBS_SIZE_V2])
    assert not np.array_equal(before, after)
    assert before[SELF_SLOTS_OFFSET + 13] == .25
    assert before[SELF_SLOTS_OFFSET + SLOT_FEATURES + 13] == .5


def test_placement_features_distinguish_finished_opponents_and_remaining_places():
    e = slots_engine()
    e.state.players[1] = Player(active=False, place=1, finish_status=FinishStatus.LEGAL_WIN)
    obs = encode(e, 0)
    base = PLACEMENTS_OFFSET + 5
    assert obs[base] == 1
    assert obs[base + 1] == 1
    assert obs[base + 6] == 0  # no turn for a finished player
    assert obs[-3] == .4
    np.testing.assert_allclose(obs[-2:], [.4, .6])


def test_legacy_policy_adapts_rank_logits_to_each_visible_slot():
    e = slots_engine()
    w = weights(OBS_SIZE_V2, 17)
    w['pw'][:] = 0
    w['pb'][:] = np.arange(17)
    mask, _ = compact_legal(e)
    logits = MLPPolicy(w).logits(encode(e, 0), mask)
    assert logits[17] == logits[18] == int(Rank.QUEEN)
    assert logits[19] == int(Rank.KING)
    assert logits[0] < -1e8


def test_v3_policy_can_prefer_second_same_rank_slot():
    e = slots_engine()
    w = weights()
    w['pw'][:] = 0
    w['pb'][18] = 20
    agent = NeuralAgent(MLPPolicy(w), safe=False)
    assert agent.choose(e) in e.state.players[0].face_up_slots[1]


@pytest.mark.parametrize('n', [2, 3, 4, 5])
def test_current_and_legacy_policies_can_share_a_complete_table(n):
    agents = [NeuralAgent(seed=0)] + [HeuristicAgent(i) for i in range(1, n)]
    result = play_game(agents, seed=17, max_steps=10000)
    assert not result['truncated']
    assert sorted(result['places']) == list(range(1, n + 1))


def test_cutoff_keeps_earned_placements_and_penalizes_only_unplaced():
    result = {'places': [1, None, 4, None], 'truncated': True}
    assert [score(result, i, 4) for i in range(4)] == [1, -1, -1, -1]
    assert sum(score({'places': [1, 2, 3, 4]}, i, 4) for i in range(4)) == pytest.approx(0)
    result = play_game([HeuristicAgent(), HeuristicAgent()], seed=1, max_steps=1)
    assert result['truncated']
    assert [score(result, i, 2) for i in range(2)] == [-1, -1]


def test_evaluation_does_not_count_partial_winners_as_complete_games(monkeypatch):
    import ibflip.ai.arena as arena
    monkeypatch.setattr(arena, 'play_game', lambda *a, **k: {'places': [1, None, 3], 'winner': 0, 'loser': 2,
                        'finishes': ['LEGAL_WIN', None, 'EIGHTS_LOSS'], 'truncated': True})
    result = evaluate(HeuristicAgent, HeuristicAgent, 3, 3)
    assert result['outcomes'] == {'timeout': 3}
    assert result['truncation_rate'] == 1
    assert result['illegal_loss_rate'] == 0
    assert result['eights_loss_rate'] == pytest.approx(1 / 3)


def test_policy_export_retains_provenance(tmp_path):
    from scripts.export_model import export_model
    w = weights()
    w['metadata'] = np.array(json.dumps({'schema': schema(), 'revision': 'example'}))
    source, target = tmp_path / 'actor.npz', tmp_path / 'export.npz'
    np.savez(source, **w)
    export_model(source, target)
    with np.load(target, allow_pickle=False) as out:
        assert out['w0'].dtype == np.float16
        assert json.loads(str(out['metadata']))['schema'] == schema()
    MLPPolicy(target)


def test_manifest_hashes_source_and_does_not_capture_credentials(tmp_path, monkeypatch):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'example.py').write_text('a=1')
    (tmp_path / '.env').write_text('PRIVATE_TOKEN=secret')
    manifest = build_manifest(tmp_path, {'seed': 7})
    assert manifest['config']['seed'] == 7
    assert 'secret' not in json.dumps(manifest)
    (tmp_path / 'src' / 'example.py').write_text('a=2')
    assert build_manifest(tmp_path, {})['source_digest'] != manifest['source_digest']


def test_torch_export_matches_numpy_and_rollout_shapes():
    torch = pytest.importorskip('torch')
    from scripts.train_ppo import build_models, export_actor, rollout_worker
    torch.set_num_threads(1)
    actor, _ = build_models(torch, [16])
    w = export_actor(actor)
    policy = MLPPolicy(w)
    e = slots_engine()
    mask, _ = compact_legal(e)
    obs = encode(e, 0)
    expected = actor(torch.from_numpy(obs), torch.from_numpy(mask)).detach().numpy()
    np.testing.assert_allclose(policy.logits(obs, mask), expected, atol=1e-6)
    cfg = {'player_counts': [2, 3, 4, 5], 'champion_frac': 0, 'selfplay_frac': 1, 'heuristic_frac': 0,
           'max_steps': 100, 'timeout_reward': -1}
    result = rollout_worker((w, [], 16, 42, cfg))
    assert result['obs'].shape[1] == OBS_SIZE
    assert result['mask'].shape[1] == 20
    assert np.all(result['mask'][np.arange(len(result['act'])), result['act']])


def test_declared_policy_schema_must_match_weights():
    w = weights()
    wrong = schema()
    wrong['observation_size'] -= 1
    w['metadata'] = np.array(json.dumps({'schema': wrong}))
    with pytest.raises(ValueError, match='metadata'):
        MLPPolicy(w)
    wrong = schema()
    wrong['action_version'] += 1
    w['metadata'] = np.array(json.dumps({'schema': wrong}))
    with pytest.raises(ValueError, match='schema version'):
        MLPPolicy(w)
    with pytest.raises(ValueError, match='v3 observations'):
        MLPPolicy(weights(OBS_SIZE_V2, 20))


def test_shared_fixing_exposes_stacks_to_training_without_losing_cards():
    from ibflip.ai.agents import heuristic_fix
    e = IBFlipEngine(2, seed=4)
    e.set_state(GameState(players=[Player(hand=[c(Rank.TWO), c(Rank.JACK), c(Rank.KING)],
        face_up_slots=[[c(Rank.TWO, Suit.DIAMONDS)], [c(Rank.TWO, Suit.CLUBS)], [c(Rank.QUEEN)]]),
        Player(hand=[c(Rank.FIVE)])], phase=Phase.FIXING_HANDS, draw_pile=[c(Rank.THREE), c(Rank.FOUR)]))
    before = sorted(e.state.draw_pile + e.state.players[0].hand + [v for slot in e.state.players[0].face_up_slots for v in slot])
    heuristic_fix(e, 0)
    p = e.state.players[0]
    after = sorted(e.state.draw_pile + p.hand + [v for slot in p.face_up_slots for v in slot])
    assert before == after
    assert any(len(slot) >= 2 for slot in p.face_up_slots)
    assert len(p.hand) == 3 or not e.state.draw_pile
    assert set(p.known_hand) <= set(p.hand)
