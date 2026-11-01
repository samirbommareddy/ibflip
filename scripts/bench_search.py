"""PRIORITY benchmark: does search (PIMC) make Shark stronger, and at what cost?

Paired design to cancel deal luck: every deal (seed) is played twice with the
hero in the same seat — once as the variant, once as plain Shark — against
plain Shark opponents. Reports the mean score difference ± 1 s.e. plus the
variant's ms per decision (search only fires on uncertain decisions).

    uv run python -u scripts/bench_search.py fix:2:200 fix:4:200 search:4:200 search:2:120 search:3:150

Variants:
  search  Shark play + PIMC at uncertain decisions (16 worlds, top-3, gate 0.9)
  fix     plain Shark play but the face-up arrangement chosen by search (16 worlds)
  both    both of the above
Prints running estimates every 40 deals, so partial results are usable.
Score: winner +1 / others -1/(n-1); illegal loser -1 / others +1/(n-1).
"""

from __future__ import annotations

import statistics
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ibflip.ai.agents import NeuralAgent  # noqa: E402
from ibflip.ai.arena import play_game, score  # noqa: E402
from ibflip.ai.pimc import PimcAgent  # noqa: E402


def make(kind: str, seed: int):
    if kind == "shark":
        return NeuralAgent(seed=seed)
    if kind == "search":
        return PimcAgent(seed=seed, worlds=16, topk=3, gate=0.9)
    if kind == "fix":
        return PimcAgent(seed=seed, gate=2.0, search_fix_worlds=16)  # gate > 1: never searches play
    if kind == "both":
        return PimcAgent(seed=seed, worlds=16, topk=3, gate=0.9, search_fix_worlds=16)
    raise ValueError(kind)


def _timed(agent, method: str, acc: list) -> None:
    inner = getattr(agent, method)

    def wrapper(*a, **k):
        t = time.perf_counter()
        try:
            return inner(*a, **k)
        finally:
            acc[0] += time.perf_counter() - t

    setattr(agent, method, wrapper)


def paired(args):
    kind, n, game_seed = args
    seat = game_seed % n
    scores, timing, hero_stats = [], (0.0, 0), (0.0, 0.0, 0, 0)
    for hero_kind in (kind, "shark"):
        agents = [make(hero_kind if i == seat else "shark", game_seed * 10 + i) for i in range(n)]
        hero = agents[seat]
        play_acc, fix_acc = [0.0], [0.0]
        if hero_kind == kind:
            _timed(hero, "choose", play_acc)
            _timed(hero, "fix", fix_acc)
        t = time.perf_counter()
        result = play_game(agents, seed=game_seed, max_steps=3000)
        if hero_kind == kind:
            timing = (time.perf_counter() - t, getattr(hero, "decisions", 0))
            hero_stats = (play_acc[0], fix_acc[0], getattr(hero, "decisions", 0), getattr(hero, "searches", 0))
        scores.append(score(result, seat, n))
    return scores[0] - scores[1], scores[0], scores[1], timing, hero_stats


def main() -> None:
    # kind:players:deals[:seed_base]  (default seed base 50000; use another to get fresh deals)
    plan = []
    for x in sys.argv[1:]:
        k, n, g, *base = x.split(":")
        plan.append((k, int(n), int(g), int(base[0]) if base else 50_000))
    with Pool(4) as pool:
        for kind, n, games, base in plan:
            t0 = time.time()
            res = []
            for i, r in enumerate(pool.imap_unordered(paired, [(kind, n, base + s) for s in range(games)])):
                res.append(r)
                if (i + 1) % 40 == 0:
                    d = [x[0] for x in res]
                    print(f"  .. {kind} {n}p after {i + 1}: {statistics.mean(d):+.3f} ± {statistics.stdev(d) / len(d) ** 0.5:.3f}", flush=True)
            d = [r[0] for r in res]
            secs = sum(r[3][0] for r in res)
            decisions = max(1, sum(r[3][1] for r in res))
            print(
                f"{kind:6} {n}p  improvement {statistics.mean(d):+.3f} ± {statistics.stdev(d) / len(d) ** 0.5:.3f} (1 s.e.)  "
                f"hero {statistics.mean(r[1] for r in res):+.3f} vs base {statistics.mean(r[2] for r in res):+.3f}  "
                f"~{1000 * secs / decisions:.0f} ms/decision (CPython, whole game incl. opponents)  "
                f"[{games} paired deals, {time.time() - t0:.0f}s]",
                flush=True,
            )
            play_s = sum(r[4][0] for r in res)
            fix_s = sum(r[4][1] for r in res)
            hero_dec = max(1, sum(r[4][2] for r in res))
            searches = sum(r[4][3] for r in res)
            print(
                f"         hero only: {1000 * play_s / hero_dec:.1f} ms/move avg, "
                f"search fired {searches}/{hero_dec} = {100 * searches / hero_dec:.1f}% of moves, "
                f"~{1000 * play_s / max(1, searches):.0f} ms per searched move (upper bound), "
                f"{1000 * fix_s / len(res):.0f} ms fixing per deal",
                flush=True,
            )


if __name__ == "__main__":
    main()
