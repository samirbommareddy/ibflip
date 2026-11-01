"""Determinized Monte-Carlo search (a.k.a. Perfect Information Monte Carlo).

IB-Flip hides: the draw-pile order, everyone's face-down cards (including
your own!) and the parts of opponents' hands nobody saw being picked up.
For each candidate move we sample several *determinizations* — hidden cards
re-dealt uniformly, consistent with everything public — play each one out
with a fast rollout policy, and pick the move with the best average result.
The same determinizations are reused for every candidate (common random
numbers), which makes the comparison much less noisy.
"""

from __future__ import annotations

import random
import time
from copy import deepcopy

import numpy as np

from ibflip.cards import RANK_INDEX_BY_ID, Rank
from ibflip.engine import IBFlipEngine
from ibflip.state import Phase
from ibflip.ai.arena import game_result, score
from ibflip.ai.observation import (
    A_END_GROUP,
    A_FACE_DOWN,
    A_PICK_UP,
    A_REVEAL,
    NUM_COMPACT_ACTIONS,
    compact_legal,
    encode,
    resolve_forced,
)
from ibflip.ai.agents import KEEP_BY_INDEX, heuristic_fix


def determinize(engine: IBFlipEngine, viewer: int, rng: random.Random) -> IBFlipEngine:
    """Copy of ``engine`` with every card hidden from ``viewer`` re-dealt."""
    sim = IBFlipEngine.__new__(IBFlipEngine)
    sim.num_players = engine.num_players
    sim.rng = random.Random(rng.random())
    sim.state = deepcopy(engine.state)
    sim.events = []
    sim.record_events = False
    st = sim.state
    pool: list[int] = list(st.draw_pile)
    slots: list[tuple] = [("draw", i) for i in range(len(st.draw_pile))]
    for p_index, player in enumerate(st.players):
        for k, card in enumerate(player.face_down_slots):
            if card is not None:
                pool.append(card)
                slots.append(("down", p_index, k))
        if p_index != viewer:
            unknown = list(player.hand)
            for card in player.known_hand:
                if card in unknown:
                    unknown.remove(card)
            for card in unknown:
                pool.append(card)
                slots.append(("hand", p_index))
            player.hand = [c for c in player.hand if c not in unknown]
    rng.shuffle(pool)
    for card, slot in zip(pool, slots):
        if slot[0] == "draw":
            st.draw_pile[slot[1]] = card
        elif slot[0] == "down":
            st.players[slot[1]].face_down_slots[slot[2]] = card
        else:
            st.players[slot[1]].hand.append(card)
    return sim


class FastRollout:
    """Cheap heuristic policy for playouts (no look-ahead)."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def choose_compact(self, engine: IBFlipEngine, mask: np.ndarray) -> int:
        legal = np.flatnonzero(mask)
        if len(legal) == 1:
            return int(legal[0])
        state = engine.state
        group = state.turn_context.open_group_rank
        live = state.live_cards
        if group is not None:
            g = int(group)
            if mask[g] and g not in (int(Rank.TWO), int(Rank.TEN)):
                if g != int(Rank.EIGHT) or _run(live) < 3:
                    return g
            return A_END_GROUP if mask[A_END_GROUP] else int(legal[0])
        ranks = [int(a) for a in legal if a < 13 and not (a == int(Rank.EIGHT) and _run(live) >= 3)]
        if ranks:
            best = min(KEEP_BY_INDEX[a] for a in ranks)
            return self.rng.choice([a for a in ranks if KEEP_BY_INDEX[a] == best])
        for a in (A_REVEAL, A_FACE_DOWN, A_PICK_UP):
            if mask[a]:
                return a
        return int(legal[0])


class PolicyRollout:
    def __init__(self, policy, rng: random.Random, temperature: float = 0.0) -> None:
        self.policy = policy
        self.rng = rng
        self.temperature = temperature
        self.np_rng = np.random.default_rng(rng.randrange(2**31))

    def choose_compact(self, engine: IBFlipEngine, mask: np.ndarray) -> int:
        legal = np.flatnonzero(mask)
        if len(legal) == 1:
            return int(legal[0])
        logits = self.policy.logits(encode(engine, engine.state.current_player), mask)
        if self.temperature <= 0:
            return int(np.argmax(logits))
        z = (logits - logits.max()) / self.temperature
        p = np.exp(z) * mask
        p /= p.sum()
        return int(self.np_rng.choice(len(p), p=p))


def _run(live: list[int]) -> int:
    if not live:
        return 0
    top = RANK_INDEX_BY_ID[live[-1]]
    n = 0
    for card in reversed(live):
        if RANK_INDEX_BY_ID[card] != top:
            break
        n += 1
    return n


def _step_compact(engine: IBFlipEngine, compact: int, mapping, rng: random.Random) -> None:
    engine.step(rng.choice(mapping[compact]), validate=False)


def playout(engine: IBFlipEngine, rollout, rng: random.Random, max_steps: int = 600) -> dict:
    steps = 0
    while engine.state.phase is not Phase.GAME_OVER and steps < max_steps:
        resolve_forced(engine)
        if engine.state.phase is Phase.GAME_OVER:
            break
        mask, mapping = compact_legal(engine)
        if not mask.any():
            break
        _step_compact(engine, rollout.choose_compact(engine, mask), mapping, rng)
        steps += 1
    return game_result(engine)


class SearchAgent:
    """PIMC search on top of a rollout policy. Falls back to the prior when
    only one move is legal or the time budget is spent."""

    name = "search"

    def __init__(
        self,
        determinizations: int = 24,
        rollout: str = "fast",
        policy=None,
        time_budget: float = 0.6,
        seed: int | None = None,
        prior_filter: int = 0,
    ) -> None:
        self.n = determinizations
        self.rng = random.Random(seed)
        self.rollout_kind = rollout
        self.policy = policy
        self.time_budget = time_budget
        self.prior_filter = prior_filter

    def _rollout(self):
        if self.rollout_kind == "policy" and self.policy is not None:
            return PolicyRollout(self.policy, self.rng)
        return FastRollout(self.rng)

    def fix(self, engine: IBFlipEngine, player_index: int) -> None:
        heuristic_fix(engine, player_index)

    def choose(self, engine: IBFlipEngine) -> int:
        mask, mapping = compact_legal(engine)
        return self.rng.choice(mapping[self.choose_compact(engine, mask)])

    def choose_compact(self, engine: IBFlipEngine, mask: np.ndarray) -> int:
        legal = [int(a) for a in np.flatnonzero(mask)]
        if len(legal) == 1:
            return legal[0]
        me = engine.state.current_player
        n_players = engine.num_players
        candidates = legal
        if self.prior_filter and self.policy is not None and len(legal) > self.prior_filter:
            logits = self.policy.logits(encode(engine, me), mask)
            candidates = [int(a) for a in np.argsort(-logits)[: self.prior_filter]]
        totals = {a: 0.0 for a in candidates}
        counts = {a: 0 for a in candidates}
        deadline = time.perf_counter() + self.time_budget
        rollout = self._rollout()
        for k in range(self.n):
            world = determinize(engine, me, self.rng)
            seed = self.rng.random()
            for a in candidates:
                sim = world.clone()
                sim.rng.seed(seed)
                sim_rng = random.Random(seed)
                rollout.rng = sim_rng
                _, sim_map = compact_legal(sim)
                _step_compact(sim, a, sim_map, sim_rng)
                result = playout(sim, rollout, sim_rng)
                totals[a] += score(result, me, n_players)
                counts[a] += 1
            if k >= 3 and time.perf_counter() > deadline:
                break
        return max(candidates, key=lambda a: totals[a] / max(1, counts[a]))
