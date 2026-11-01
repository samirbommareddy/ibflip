"""Bot players: random, hand-written heuristic, and the trained neural policy.

Every agent exposes ``choose(engine) -> engine action`` for the player whose
turn it is (forced moves such as the 9-draw are resolved by the caller via
``observation.resolve_forced``) and ``fix(engine, player_index)`` for the
hand-fixing phase.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from ibflip.cards import RANK_INDEX_BY_ID, Rank
from ibflip.engine import IBFlipEngine
from ibflip.ai.observation import (
    A_END_GROUP,
    A_FACE_DOWN,
    A_PICK_UP,
    A_REVEAL,
    NUM_COMPACT_ACTIONS,
    compact_legal,
    encode,
)

# How much we'd like to *keep* a rank for later (low = dump it first).
KEEP_VALUE = {
    Rank.JACK: 1.0,
    Rank.QUEEN: 1.5,
    Rank.KING: 2.0,
    Rank.NINE: 2.5,
    Rank.SIX: 3.0,
    Rank.EIGHT: 3.5,
    Rank.THREE: 4.0,
    Rank.ACE: 4.5,
    Rank.SEVEN: 5.0,
    Rank.FIVE: 6.0,
    Rank.FOUR: 7.0,
    Rank.TWO: 8.0,
    Rank.TEN: 9.0,
}
KEEP_BY_INDEX = [KEEP_VALUE[Rank(i)] for i in range(13)]


class RepetitionGuard:
    """Detects when a bot is going round in circles so it can vary its play.

    Two signals: the exact same position recurring, and "no progress" — the
    deck, discard pile and table cards unchanged across many of this bot's
    own turns (e.g. two bots bouncing 4s back and forth forever).
    """

    STALL_TURNS = 12

    def __init__(self) -> None:
        self.seen: dict[tuple, int] = {}
        self.progress_key: tuple | None = None
        self.stalled_for = 0

    def count(self, engine: IBFlipEngine) -> int:
        st = engine.state
        me = st.players[st.current_player]
        key = (
            st.current_player,
            tuple(sorted(RANK_INDEX_BY_ID[c] for c in me.hand)),
            tuple(RANK_INDEX_BY_ID[c] for c in st.live_cards[-4:]),
            len(st.live_cards),
            tuple(len(p.hand) for p in st.players),
        )
        if len(self.seen) > 50_000:
            self.seen.clear()
        self.seen[key] = self.seen.get(key, 0) + 1
        progress = (
            len(st.draw_pile),
            len(st.discard_pile),
            sum(len(slot) for p in st.players for slot in p.face_up_slots),
            sum(c is not None for p in st.players for c in p.face_down_slots),
        )
        if progress == self.progress_key:
            self.stalled_for += 1
        else:
            self.progress_key = progress
            self.stalled_for = 0
        if self.stalled_for >= self.STALL_TURNS:
            return 99
        return self.seen[key]


def _pick_card(engine: IBFlipEngine, mapping: dict[int, list[int]], compact: int, rng: random.Random) -> int:
    return rng.choice(mapping[compact])


def heuristic_fix(engine: IBFlipEngine, player_index: int) -> None:
    """Put the strongest three cards face up, keep the weakest in hand."""
    player = engine.state.players[player_index]
    for _ in range(6):
        if not player.hand:
            break
        best_hand = max(player.hand, key=lambda c: KEEP_BY_INDEX[RANK_INDEX_BY_ID[c]])
        worst_slot = min(
            (i for i, slot in enumerate(player.face_up_slots) if len(slot) == 1),
            key=lambda i: KEEP_BY_INDEX[RANK_INDEX_BY_ID[player.face_up_slots[i][0]]],
            default=None,
        )
        if worst_slot is None:
            break
        if KEEP_BY_INDEX[RANK_INDEX_BY_ID[best_hand]] <= KEEP_BY_INDEX[RANK_INDEX_BY_ID[player.face_up_slots[worst_slot][0]]]:
            break
        engine.fix_swap_card(player_index, best_hand, worst_slot)


class RandomAgent:
    name = "random"

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def fix(self, engine: IBFlipEngine, player_index: int) -> None:
        return

    def choose(self, engine: IBFlipEngine) -> int:
        return self.rng.choice(engine.get_legal_action_indices())


class HeuristicAgent:
    """Dump cheap cards first, save 2s/10s/4s, never flip 8s or finish illegally."""

    name = "heuristic"

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.guard = RepetitionGuard()

    def fix(self, engine: IBFlipEngine, player_index: int) -> None:
        heuristic_fix(engine, player_index)

    def choose(self, engine: IBFlipEngine) -> int:
        mask, mapping = compact_legal(engine)
        if self.guard.count(engine) > 2:
            return self.rng.choice(engine.get_legal_action_indices())
        return _pick_card(engine, mapping, self.choose_compact(engine, mask), self.rng)

    def choose_compact(self, engine: IBFlipEngine, mask: np.ndarray) -> int:
        legal = [a for a in range(NUM_COMPACT_ACTIONS) if mask[a]]
        if len(legal) == 1:
            return legal[0]
        state = engine.state
        live = state.live_cards
        player = state.players[state.current_player]
        rank_moves = [a for a in legal if a < 13]

        def would_flip_eights(rank: int) -> bool:
            if rank != int(Rank.EIGHT):
                return False
            run = 0
            for card in reversed(live):
                if RANK_INDEX_BY_ID[card] != rank:
                    break
                run += 1
            return run >= 3

        def finishes_illegally(rank: int) -> bool:
            remaining = len(player.hand) + sum(len(s) for s in player.face_up_slots) + sum(
                c is not None for c in player.face_down_slots
            )
            return remaining == 1 and rank in (int(Rank.TWO), int(Rank.TEN))

        me = state.current_player

        def loses_now(compact: int) -> bool:
            """Simulate the move (and closing the group) to see if it loses."""
            sim = engine.clone()
            sim.record_events = False
            _, sim_map = compact_legal(sim)
            sim.step(sim_map[compact][0], validate=False)
            if sim.state.turn_context.open_group_rank is not None and sim.state.current_player == me:
                sim_mask, sim_map = compact_legal(sim)
                if sim_mask[A_END_GROUP]:
                    sim.step(sim_map[A_END_GROUP][0], validate=False)
            return sim.state.loser == me

        if state.turn_context.open_group_rank is not None:
            group = int(state.turn_context.open_group_rank)
            if group in rank_moves and not would_flip_eights(group) and group not in (int(Rank.TWO), int(Rank.TEN)):
                if not finishes_illegally(group) and not loses_now(group):
                    return group
            if A_END_GROUP in legal and not loses_now(A_END_GROUP):
                return A_END_GROUP
            others = [a for a in legal if a != A_END_GROUP and not loses_now(a)]
            return others[0] if others else legal[0]

        safe = [a for a in rank_moves if not would_flip_eights(a) and not finishes_illegally(a)]
        safe = [a for a in safe if not loses_now(a)]
        if safe:
            # Attack with a 4 when the next player looks weak on 4/5/6.
            return min(safe, key=lambda a: (KEEP_BY_INDEX[a], self.rng.random()))
        if A_REVEAL in legal:
            return A_REVEAL
        if A_FACE_DOWN in legal:
            return A_FACE_DOWN
        if A_PICK_UP in legal:
            return A_PICK_UP
        return self.rng.choice(legal)


class MLPPolicy:
    """Numpy-only forward pass of the trained actor (no torch at runtime)."""

    def __init__(self, path_or_weights) -> None:
        data = np.load(path_or_weights) if isinstance(path_or_weights, (str, Path)) else path_or_weights
        self.layers: list[tuple[np.ndarray, np.ndarray]] = []
        i = 0
        while f"w{i}" in data:
            self.layers.append((data[f"w{i}"].astype(np.float32), data[f"b{i}"].astype(np.float32)))
            i += 1
        self.policy_w = data["pw"].astype(np.float32)
        self.policy_b = data["pb"].astype(np.float32)
        self.value_w = data["vw"].astype(np.float32) if "vw" in data else None
        self.value_b = data["vb"].astype(np.float32) if "vb" in data else None

    def trunk(self, obs: np.ndarray) -> np.ndarray:
        x = obs
        for w, b in self.layers:
            x = x @ w + b
            x = np.maximum(x, 0.0)
        return x

    def logits(self, obs: np.ndarray, mask: np.ndarray) -> np.ndarray:
        logits = self.trunk(obs) @ self.policy_w + self.policy_b
        return np.where(mask, logits, -1e9)

    def value(self, obs: np.ndarray) -> float:
        if self.value_w is None:
            return 0.0
        return float((self.trunk(obs) @ self.value_w + self.value_b).reshape(-1)[0])


DEFAULT_MODEL_PATH = Path(__file__).with_name("model.npz")


def loses_immediately(engine: IBFlipEngine, compact: int, mapping: dict[int, list[int]]) -> bool:
    """Would this move (closing the group if needed) make the mover lose now?

    Uses only information the mover has: their own cards and public state.
    Moves that depend on hidden randomness (flipping a face-down card or the
    deck) are never flagged.
    """
    if compact in (A_FACE_DOWN, A_REVEAL):
        return False
    me = engine.state.current_player
    sim = engine.clone()
    sim.record_events = False
    sim.step(mapping[compact][0], validate=False)
    if sim.state.turn_context.open_group_rank is not None and sim.state.current_player == me:
        sim_mask, sim_map = compact_legal(sim)
        if sim_mask[A_END_GROUP] and compact != A_END_GROUP:
            # Only flag if *every* way of continuing loses; closing now is one option.
            sim.step(sim_map[A_END_GROUP][0], validate=False)
    return sim.state.loser == me


class NeuralAgent:
    """Plays the self-play trained policy. ``temperature=0`` is greedy.

    ``safe=True`` vetoes moves that lose on the spot (e.g. finishing on a 2,
    flipping four 8s) when an alternative exists.
    """

    name = "neural"

    def __init__(self, path: str | Path = DEFAULT_MODEL_PATH, temperature: float = 0.0, seed: int | None = None, safe: bool = True) -> None:
        self.policy = path if isinstance(path, MLPPolicy) else MLPPolicy(path)
        self.safe = safe
        self.temperature = temperature
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.guard = RepetitionGuard()

    def fix(self, engine: IBFlipEngine, player_index: int) -> None:
        heuristic_fix(engine, player_index)

    def choose(self, engine: IBFlipEngine) -> int:
        mask, mapping = compact_legal(engine)
        legal = np.flatnonzero(mask)
        if len(legal) == 1:
            compact = int(legal[0])
        else:
            logits = self.policy.logits(encode(engine, engine.state.current_player), mask)
            if self.safe:
                for a in np.argsort(-logits):
                    if not mask[a]:
                        break
                    if loses_immediately(engine, int(a), mapping):
                        logits[a] = -1e8  # still preferable to illegal, but last resort
                    else:
                        break
            temperature = self.temperature
            if self.guard.count(engine) > 2:
                temperature = max(temperature, 1.5)  # break repetition loops
            if temperature <= 0:
                compact = int(np.argmax(logits))
            else:
                z = logits / temperature
                z = z - z.max()
                p = np.exp(z) * mask
                p /= p.sum()
                compact = int(self.np_rng.choice(len(p), p=p))
        return _pick_card(engine, mapping, compact, self.rng)


def model_available(path: str | Path = DEFAULT_MODEL_PATH) -> bool:
    return Path(path).exists()
