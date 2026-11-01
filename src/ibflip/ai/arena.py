"""Play full games between agents and measure win rates."""

from __future__ import annotations

import random
from collections import Counter
from typing import Sequence

from ibflip.engine import IBFlipEngine
from ibflip.ai.observation import resolve_forced
from ibflip.state import Phase


def play_game(agents: Sequence, seed: int | None = None, max_steps: int = 3000) -> dict:
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
    return {"winner": state.winner, "loser": state.loser, "places": [p.place for p in state.players]}


def score(result: dict, seat: int, num_players: int) -> float:
    """Zero-sum score from placements: 1st +1, last -1, linear in between.

    A seat without a place (game cut short) scores 0. Results without
    ``places`` fall back to the old winner/loser scoring.
    """
    places = result.get("places")
    if places is not None:
        place = places[seat]
        if place is None:
            return 0.0
        return 1.0 - 2.0 * (place - 1) / (num_players - 1)
    if result["winner"] is not None:
        return 1.0 if result["winner"] == seat else -1.0 / (num_players - 1)
    if result["loser"] is not None:
        return -1.0 if result["loser"] == seat else 1.0 / (num_players - 1)
    return 0.0


def evaluate(make_hero, make_villain, num_players: int, games: int, seed: int = 0) -> dict:
    """Hero sits in a rotating seat against (num_players-1) villains."""
    rng = random.Random(seed)
    wins = losses = 0
    total = 0.0
    outcomes = Counter()
    for game in range(games):
        seat = game % num_players
        agents = [make_hero() if i == seat else make_villain() for i in range(num_players)]
        result = play_game(agents, seed=rng.randrange(2**31))
        s = score(result, seat, num_players)
        total += s
        wins += result["winner"] == seat
        losses += result["loser"] == seat
        outcomes["winner" if result["winner"] is not None else "loser" if result["loser"] is not None else "timeout"] += 1
    return {
        "games": games,
        "win_rate": wins / games,
        "illegal_loss_rate": losses / games,
        "mean_score": total / games,
        "fair_win_rate": 1.0 / num_players,
        "outcomes": dict(outcomes),
    }
