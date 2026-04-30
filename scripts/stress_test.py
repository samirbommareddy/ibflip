from __future__ import annotations

import argparse
import gc
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, is_dataclass
from enum import Enum
import random
import sys
import time
import tracemalloc
from pathlib import Path
from pprint import pformat
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ibflip import IBFlipEngine  # noqa: E402
from ibflip.actions import ACTION_END_PLAY_GROUP  # noqa: E402
from ibflip.state import Phase  # noqa: E402


class FatalDeadlockError(RuntimeError):
    pass


class InfiniteLoopError(RuntimeError):
    pass


def serialize_for_dump(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.name
    if is_dataclass(value):
        return {key: serialize_for_dump(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [serialize_for_dump(item) for item in value]
    if isinstance(value, tuple):
        return tuple(serialize_for_dump(item) for item in value)
    if isinstance(value, dict):
        return {serialize_for_dump(key): serialize_for_dump(item) for key, item in value.items()}
    return value


def dump_state(engine: IBFlipEngine, game_index: int, turn_count: int) -> str:
    legal_actions = engine.get_legal_actions()
    return pformat(
        {
            "game": game_index,
            "turn_count": turn_count,
            "phase": engine.state.phase.name,
            "current_player": engine.state.current_player,
            "legal_actions": [index for index, is_legal in enumerate(legal_actions) if is_legal],
            "state": serialize_for_dump(engine.state),
        },
        width=120,
        sort_dicts=False,
    )


def memory_sample(label: str) -> tuple[str, int, int]:
    current, peak = tracemalloc.get_traced_memory()
    return label, current, peak


def format_bytes(value: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TiB"


def run_stress_test(total_games: int, max_turns: int, seed: int, num_players: int, workers: int | None = None) -> None:
    workers = max(1, min(workers or os.cpu_count() or 1, total_games))
    if workers == 1:
        stats = run_stress_slice(1, total_games, max_turns, seed, num_players, {1, total_games} | ({50_000} if total_games >= 50_000 else set()))
        print_summary(total_games, stats)
        return

    sample_games = {1, total_games}
    if total_games >= 50_000:
        sample_games.add(50_000)

    started_at = time.perf_counter()
    futures = []
    base = total_games // workers
    remainder = total_games % workers
    next_start = 1
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for worker_index in range(workers):
            count = base + (1 if worker_index < remainder else 0)
            start = next_start
            end = start + count - 1
            next_start = end + 1
            worker_samples = {game for game in sample_games if start <= game <= end}
            futures.append(
                executor.submit(
                    run_stress_slice,
                    start,
                    end,
                    max_turns,
                    seed + worker_index * 1_000_003,
                    num_players,
                    worker_samples,
                )
            )

        combined: dict[str, Any] = {
            "elapsed": 0.0,
            "turn_sum": 0,
            "turn_min": None,
            "turn_max": 0,
            "timeout_count": 0,
            "wins_by_seat": [0] * num_players,
            "memory_samples": [],
        }
        for future in futures:
            stats = future.result()
            combined["turn_sum"] += stats["turn_sum"]
            combined["turn_min"] = stats["turn_min"] if combined["turn_min"] is None else min(combined["turn_min"], stats["turn_min"])
            combined["turn_max"] = max(combined["turn_max"], stats["turn_max"])
            combined["timeout_count"] += stats["timeout_count"]
            combined["memory_samples"].extend(stats["memory_samples"])
            for seat, wins in enumerate(stats["wins_by_seat"]):
                combined["wins_by_seat"][seat] += wins

    combined["elapsed"] = time.perf_counter() - started_at
    combined["memory_samples"].sort(key=lambda sample: sample[0])
    print_summary(total_games, combined, workers=workers)


def run_stress_slice(
    start_game: int,
    end_game: int,
    max_turns: int,
    seed: int,
    num_players: int,
    sample_games: set[int],
) -> dict[str, Any]:
    rng = random.Random(seed)
    turn_sum = 0
    turn_min: int | None = None
    turn_max = 0
    wins_by_seat = [0] * num_players
    memory_samples: list[tuple[str, int, int]] = []
    timeout_count = 0
    started_at = time.perf_counter()

    for game_index in range(start_game, end_game + 1):
        trace_this_game = game_index in sample_games
        if trace_this_game:
            gc.collect()
            tracemalloc.start()

        engine = IBFlipEngine(num_players=num_players, seed=rng.randrange(2**63))
        engine.reset()
        engine.auto_fix_hands_randomly()

        turn_count = 0
        while engine.state.phase is not Phase.GAME_OVER:
            legal_indices = engine.get_legal_action_indices()
            if not legal_indices:
                print(dump_state(engine, game_index, turn_count), file=sys.stderr)
                raise FatalDeadlockError(f"no legal actions in game {game_index} after {turn_count} turns")

            if ACTION_END_PLAY_GROUP in legal_indices and rng.random() < 0.75:
                action = ACTION_END_PLAY_GROUP
            elif ACTION_END_PLAY_GROUP in legal_indices and len(legal_indices) > 1:
                action = rng.choice([candidate for candidate in legal_indices if candidate != ACTION_END_PLAY_GROUP])
            else:
                action = rng.choice(legal_indices)
            engine.step(action, validate=False)
            turn_count += 1

            if turn_count >= max_turns:
                timeout_count += 1
                break

        turn_sum += turn_count
        turn_min = turn_count if turn_min is None else min(turn_min, turn_count)
        turn_max = max(turn_max, turn_count)
        if engine.state.winner is not None:
            wins_by_seat[engine.state.winner] += 1

        if trace_this_game:
            memory_samples.append(memory_sample(f"game {game_index:,}"))
            tracemalloc.stop()

    return {
        "elapsed": time.perf_counter() - started_at,
        "turn_sum": turn_sum,
        "turn_min": turn_min or 0,
        "turn_max": turn_max,
        "timeout_count": timeout_count,
        "wins_by_seat": wins_by_seat,
        "memory_samples": memory_samples,
    }


def print_summary(total_games: int, stats: dict[str, Any], workers: int = 1) -> None:
    elapsed = stats["elapsed"]
    games_per_second = total_games / elapsed

    print("IB-Flip random-agent stress test")
    print(f"Games completed: {total_games:,}")
    print(f"Workers: {workers}")
    print(f"Total execution time: {elapsed:.3f}s")
    print(f"Games per second: {games_per_second:,.2f}")
    print(f"Average turns per game: {stats['turn_sum'] / total_games:.2f}")
    print(f"Min turns per game: {stats['turn_min']}")
    print(f"Max turns per game: {stats['turn_max']}")
    print(f"Timeout count: {stats['timeout_count']:,}")
    print("Win rate distribution by starting seat:")
    for seat, wins in enumerate(stats["wins_by_seat"], start=1):
        print(f"  Player {seat}: {wins / total_games:.2%} ({wins:,}/{total_games:,})")
    print("Memory samples:")
    for label, current, peak in stats["memory_samples"]:
        print(f"  {label}: current={format_bytes(current)}, peak={format_bytes(peak)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run random-agent IB-Flip engine stress tests.")
    parser.add_argument("--games", type=int, default=100_000)
    parser.add_argument("--max-turns", type=int, default=5_000)
    parser.add_argument("--seed", type=int, default=20260430)
    parser.add_argument("--players", type=int, default=2)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()

    run_stress_test(
        total_games=args.games,
        max_turns=args.max_turns,
        seed=args.seed,
        num_players=args.players,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
