"""Play full games between agents and measure win rates."""

from __future__ import annotations

import random
from collections import Counter
from typing import Sequence

from ibflip.engine import IBFlipEngine
from ibflip.ai.observation import resolve_forced
from ibflip.state import Phase

MAX_GAME_STEPS = 3000
TIMEOUT_REWARD = -1.0
SCORING_VERSION = "placement-v2-unplaced-timeout-loss"


def play_game(agents: Sequence, seed: int | None = None, max_steps: int = MAX_GAME_STEPS) -> dict:
    """Return {'winner', 'loser', 'places', 'steps'} (see ``game_result``)."""
    engine = IBFlipEngine(len(agents), seed=seed)
    engine.record_events = False
    engine.reset()
    for index, agent in enumerate(agents):
        agent.fix(engine, index)
    for index in range(len(agents)):
        engine.fix_done(index)
    steps = 0
    while engine.state.phase is not Phase.GAME_OVER and steps < max_steps:
        resolve_forced(engine)
        if engine.state.phase is Phase.GAME_OVER:
            break
        action = agents[engine.state.current_player].choose(engine)
        engine.step(action, validate=False)
        steps += 1
    return {**game_result(engine), "steps": steps}


def game_result(engine: IBFlipEngine) -> dict:
    """Winner / loser seats and every seat's place (None if unplaced)."""
    state = engine.state
    return {
        "winner": state.winner, "loser": state.loser,
        "places": [p.place for p in state.players],
        "finishes": [p.finish_status.name if p.finish_status else None for p in state.players],
        "truncated": state.phase is not Phase.GAME_OVER,
    }


def score(result: dict, seat: int, num_players: int, timeout_reward: float = TIMEOUT_REWARD) -> float:
    """Placement score: 1st +1, last -1, linear in between.

    At a cutoff retain earned places; only unplaced seats receive the timeout
    loss. Complete results are zero-sum; truncated results need not be.
    Results without
    ``places`` fall back to the old winner/loser scoring.
    """
    places = result.get("places")
    if places is not None:
        place = places[seat]
        if place is None:
            return timeout_reward
        return 1.0 - 2.0 * (place - 1) / (num_players - 1)
    if result["winner"] is not None:
        return 1.0 if result["winner"] == seat else -1.0 / (num_players - 1)
    if result["loser"] is not None:
        return -1.0 if result["loser"] == seat else 1.0 / (num_players - 1)
    return 0.0


def evaluate(make_hero, make_villain, num_players: int, games: int, seed: int = 0, max_steps: int = MAX_GAME_STEPS, timeout_reward: float = TIMEOUT_REWARD) -> dict:
    """Hero sits in a rotating seat against (num_players-1) villains."""
    rng = random.Random(seed)
    wins = losses = illegal = eights = truncations = 0
    total = 0.0
    outcomes = Counter()
    for game in range(games):
        seat = game % num_players
        agents = [make_hero() if i == seat else make_villain() for i in range(num_players)]
        result = play_game(agents, seed=rng.randrange(2**31), max_steps=max_steps)
        s = score(result, seat, num_players, timeout_reward)
        total += s
        wins += result["winner"] == seat
        losses += result["loser"] == seat
        illegal += result["finishes"][seat] == "ILLEGAL_LOSS"
        eights += result["finishes"][seat] == "EIGHTS_LOSS"
        truncations += result["truncated"]
        outcomes["timeout" if result["truncated"] else "complete"] += 1
    return {
        "games": games,
        "win_rate": wins / games,
        "loss_rate": losses / games,
        "illegal_loss_rate": illegal / games,
        "eights_loss_rate": eights / games,
        "truncation_rate": truncations / games,
        "mean_score": total / games,
        "fair_win_rate": 1.0 / num_players,
        "outcomes": dict(outcomes),
    }
