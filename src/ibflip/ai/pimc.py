"""Policy-guided determinized search (Perfect Information Monte Carlo).

AlphaZero-style idea adapted to hidden information: the trained policy
proposes moves and plays out the future, while search over sampled deals
of the hidden cards decides between the proposals.

* ``PimcAgent`` — at uncertain decisions, evaluates the policy's top-k moves
  in the same N determinized worlds (common random numbers), each played to
  the end by the policy for every seat, and picks the best average score.
* ``search_fix`` — chooses which 3 of your 6 cards to put face-up by playing
  out every arrangement in sampled worlds.
"""

from __future__ import annotations

import itertools
import random
import time

import numpy as np

from ibflip.cards import RANK_INDEX_BY_ID
from ibflip.engine import IBFlipEngine
from ibflip.state import Phase
from ibflip.ai.agents import MLPPolicy, NeuralAgent, heuristic_fix
from ibflip.ai.arena import score
from ibflip.ai.observation import compact_legal, encode, resolve_forced
from ibflip.ai.search import determinize


def _softmax(logits: np.ndarray) -> np.ndarray:
    z = logits - logits.max()
    p = np.exp(z)
    return p / p.sum()


def policy_playout(engine: IBFlipEngine, policy: MLPPolicy, rng: random.Random, np_rng: np.random.Generator,
                   temperature: float = 1.0, max_steps: int = 800) -> dict:
    steps = 0
    while engine.state.phase is not Phase.GAME_OVER and steps < max_steps:
        resolve_forced(engine)
        if engine.state.phase is Phase.GAME_OVER:
            break
        mask, mapping = compact_legal(engine)
        legal = np.flatnonzero(mask)
        if len(legal) == 1:
            a = int(legal[0])
        else:
            logits = policy.logits(encode(engine, engine.state.current_player), mask)
            if temperature <= 0:
                a = int(np.argmax(logits))
            else:
                p = _softmax(logits / temperature) * mask
                a = int(np_rng.choice(len(p), p=p / p.sum()))
        engine.step(rng.choice(mapping[a]), validate=False)
        steps += 1
    return {"winner": engine.state.winner, "loser": engine.state.loser}


class PimcAgent(NeuralAgent):
    """Shark + search when it's unsure (policy max-prob below ``gate``)."""

    name = "shark+search"

    def __init__(self, path=None, worlds: int = 16, topk: int = 3, gate: float = 0.9,
                 temperature: float = 1.0, time_budget: float | None = None, seed: int | None = None,
                 search_fix_worlds: int = 0) -> None:
        if path is None:
            from ibflip.ai.agents import DEFAULT_MODEL_PATH
            path = DEFAULT_MODEL_PATH
        super().__init__(path, seed=seed)
        self.worlds = worlds
        self.topk = topk
        self.gate = gate
        self.rollout_temperature = temperature
        self.time_budget = time_budget
        self.search_rng = random.Random(seed)
        self.search_np = np.random.default_rng(seed)
        self.search_fix_worlds = search_fix_worlds
        self.searches = 0
        self.decisions = 0

    def fix(self, engine: IBFlipEngine, player_index: int) -> None:
        if self.search_fix_worlds:
            search_fix(engine, player_index, self.policy, self.search_fix_worlds, self.search_rng)
        else:
            heuristic_fix(engine, player_index)

    def choose(self, engine: IBFlipEngine) -> int:
        mask, mapping = compact_legal(engine)
        legal = np.flatnonzero(mask)
        self.decisions += 1
        if len(legal) == 1 or self.guard.count(engine) > 2:
            return super().choose(engine)
        me = engine.state.current_player
        p = _softmax(self.policy.logits(encode(engine, me), mask)) * mask
        if p.max() >= self.gate:
            return self.rng.choice(mapping[int(np.argmax(p))])
        self.searches += 1
        cands = [int(a) for a in np.argsort(-p)[: self.topk] if mask[a]]
        totals = {a: 0.0 for a in cands}
        deadline = None if self.time_budget is None else time.perf_counter() + self.time_budget
        n = engine.num_players
        done = 0
        for _ in range(self.worlds):
            world = determinize(engine, me, self.search_rng)
            seed = self.search_rng.random()
            for a in cands:
                sim = world.clone()
                sim.rng.seed(seed)
                r = random.Random(seed)
                npr = np.random.default_rng(int(seed * 2**31))
                _, sim_map = compact_legal(sim)
                sim.step(r.choice(sim_map[a]), validate=False)
                totals[a] += score(policy_playout(sim, self.policy, r, npr, self.rollout_temperature), me, n)
            done += 1
            if deadline is not None and done >= 4 and time.perf_counter() > deadline:
                break
        best = max(cands, key=lambda a: (totals[a], p[a]))
        return self.rng.choice(mapping[best])


def fix_arrangements(engine: IBFlipEngine, player_index: int) -> list[tuple[int, ...]]:
    """All distinct choices (by rank) of 3 face-up cards from hand+face-up."""
    player = engine.state.players[player_index]
    cards = list(player.hand) + [slot[0] for slot in player.face_up_slots if len(slot) == 1]
    seen, out = set(), []
    for combo in itertools.combinations(cards, 3):
        key = tuple(sorted(RANK_INDEX_BY_ID[c] for c in combo))
        if key not in seen:
            seen.add(key)
            out.append(combo)
    return out


def apply_arrangement(engine: IBFlipEngine, player_index: int, face_up: tuple[int, ...]) -> None:
    player = engine.state.players[player_index]
    target = list(face_up)
    for slot_index in range(len(player.face_up_slots)):
        slot = player.face_up_slots[slot_index]
        if len(slot) != 1:
            continue
        if slot[0] in target:
            target.remove(slot[0])
    for slot_index in range(len(player.face_up_slots)):
        slot = player.face_up_slots[slot_index]
        if len(slot) == 1 and slot[0] not in face_up and target:
            engine.fix_swap_card(player_index, target.pop(), slot_index)


def search_fix(engine: IBFlipEngine, player_index: int, policy: MLPPolicy, worlds: int, rng: random.Random) -> None:
    """Pick the face-up arrangement with the best average playout result."""
    options = fix_arrangements(engine, player_index)
    if len(options) <= 1:
        heuristic_fix(engine, player_index)
        return
    totals = [0.0] * len(options)
    n = engine.num_players
    for _ in range(worlds):
        world = determinize(engine, player_index, rng)
        seed = rng.random()
        for i, arrangement in enumerate(options):
            sim = world.clone()
            sim.rng.seed(seed)
            apply_arrangement(sim, player_index, arrangement)
            for j in range(n):
                if j != player_index and not sim.state.players[j].fixing_done:
                    heuristic_fix(sim, j)
            for j in range(n):
                if not sim.state.players[j].fixing_done:
                    sim.fix_done(j)
            r = random.Random(seed)
            totals[i] += score(policy_playout(sim, policy, r, np.random.default_rng(int(seed * 2**31))), player_index, n)
    apply_arrangement(engine, player_index, options[int(np.argmax(totals))])
