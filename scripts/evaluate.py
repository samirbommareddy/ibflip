"""Benchmark a policy file against the baseline bots.

    uv run python scripts/evaluate.py --model src/ibflip/ai/model.npz --games 600

Reports, per player count:
  * Shark alone vs a table of heuristic bots (and vs random bots)
  * a heuristic bot alone vs a table of Sharks (lower = stronger Shark)
  * Shark-vs-Shark game length (long games would mean it learned to stall)
Win rates should be compared with the fair share 1/n.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ibflip.ai.agents import HeuristicAgent, NeuralAgent, RandomAgent  # noqa: E402
from ibflip.ai.arena import evaluate, play_game  # noqa: E402

MODEL = None


def _make(kind: str, seed: int):
    if kind == "shark":
        return NeuralAgent(MODEL, seed=seed)
    if kind == "heuristic":
        return HeuristicAgent(seed)
    return RandomAgent(seed)


def _job(args):
    hero, villain, n, games, seed, model = args
    global MODEL
    MODEL = model
    return evaluate(lambda: _make(hero, seed), lambda: _make(villain, seed + 1), n, games, seed=seed)


def _lengths(args):
    n, games, seed, model = args
    global MODEL
    MODEL = model
    return [play_game([_make("shark", seed + i) for i in range(n)], seed=seed * 1000 + g)["steps"] for g in range(games)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=str(Path(__file__).resolve().parents[1] / "src/ibflip/ai/model.npz"))
    parser.add_argument("--games", type=int, default=600)
    parser.add_argument("--players", default="2,3,4,5")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    w = args.workers
    with Pool(w) as pool:
        print(f"{'n':>2} {'matchup':<28} {'win':>6} {'fair':>6} {'score':>7} {'illegal':>8}")
        for n in [int(x) for x in args.players.split(",")]:
            for hero, villain in (("shark", "heuristic"), ("shark", "random"), ("heuristic", "shark"), ("heuristic", "random")):
                rs = pool.map(_job, [(hero, villain, n, args.games // w, 1000 * n + 17 * i, args.model) for i in range(w)])
                avg = lambda k: sum(r[k] for r in rs) / len(rs)
                print(f"{n:>2} {hero + ' vs ' + villain + ' table':<28} {avg('win_rate'):6.3f} {1 / n:6.3f} {avg('mean_score'):7.3f} {avg('illegal_loss_rate'):8.3f}", flush=True)
            lens = [x for r in pool.map(_lengths, [(n, 10, 50 + i, args.model) for i in range(w)]) for x in r]
            print(f"{n:>2} {'shark self-play length':<28} median {statistics.median(lens):.0f} steps, capped {sum(x >= 3000 for x in lens)}/{len(lens)}", flush=True)


if __name__ == "__main__":
    main()
