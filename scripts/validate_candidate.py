"""Paired, seat-rotated validation of a candidate Shark actor against a baseline.

    ./scripts/with-env uv run --locked python -u scripts/validate_candidate.py \
        --candidate runs/<run>/actor_00740.npz h2h:2:4000 h2h:4:3000 rev:4:3000 regular:2:2000

Every *deal* (engine seed) is the unit of pairing; games within a deal are
correlated and never treated as independent samples. Matchups:

  h2h      Candidate alone in a baseline table. For each seat s the candidate
           plays seat s with baseline agents elsewhere; one all-baseline control
           game is played on the same deal with the same per-seat agent seeds.
           Deal statistic = mean_s cand_score(s) - mean_s control_score(s).
  rev      Reverse direction: baseline alone in a candidate table. Deal statistic
           = mean_s all_candidate_control(s) - mean_s baseline_score(s).
           (At 2p this is the same experiment as h2h.)
  regular  Candidate alone vs Regular (HeuristicAgent) table and baseline alone
           vs the same table, same deal and seat. Statistic = candidate - baseline.

Positive numbers always mean "candidate better". Uses the shared placement
score (1st +1, last -1, unplaced at a cutoff -1). Prints running estimates.
Never writes any model file.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from multiprocessing import Pool
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from ibflip.ai.agents import DEFAULT_MODEL_PATH, HeuristicAgent, MLPPolicy, NeuralAgent  # noqa: E402
from ibflip.ai.arena import MAX_GAME_STEPS, play_game, score  # noqa: E402
from ibflip.engine import IBFlipEngine  # noqa: E402
from ibflip.ai.observation import resolve_forced  # noqa: E402
from ibflip.state import Phase  # noqa: E402

_POLICIES: dict[str, MLPPolicy] = {}


def _init(paths: dict[str, str]) -> None:
    for key, path in paths.items():
        _POLICIES[key] = MLPPolicy(path)


def _agent(kind: str, seed: int):
    if kind == "regular":
        return HeuristicAgent(seed)
    return NeuralAgent(_POLICIES[kind], seed=seed)


def _play(kinds: list[str], deal: int) -> dict:
    agents = [_agent(k, deal * 10 + i) for i, k in enumerate(kinds)]
    return play_game(agents, seed=deal, max_steps=MAX_GAME_STEPS)


def _seat_stats(result: dict, seat: int, n: int) -> tuple[float, int, int, int, int]:
    fin = result["finishes"][seat]
    return (score(result, seat, n), int(result["winner"] == seat), int(fin == "ILLEGAL_LOSS"), int(fin == "EIGHTS_LOSS"), int(result["places"][seat] is None))


def run_deal(args) -> dict:
    """Return per-deal aggregates for both arms (A = candidate arm, B = baseline arm)."""
    mode, n, deal, hero, base = args
    a, b = np.zeros(5), np.zeros(5)  # score, win, illegal, eights, unplaced (averaged over seats)
    lengths, truncs = [], 0
    if mode in ("h2h", "rev"):
        solo, table = (hero, base) if mode == "h2h" else (base, hero)
        control = _play([table] * n, deal)
        lengths.append(control["steps"])
        truncs += control["truncated"]
        ctrl = np.array([_seat_stats(control, s, n) for s in range(n)]).mean(axis=0)
        solo_stats = []
        for s in range(n):
            r = _play([solo if i == s else table for i in range(n)], deal)
            lengths.append(r["steps"])
            truncs += r["truncated"]
            solo_stats.append(_seat_stats(r, s, n))
        solo_mean = np.array(solo_stats).mean(axis=0)
        if mode == "h2h":
            a, b = solo_mean, ctrl  # candidate alone vs baseline seat in all-baseline game
        else:
            a, b = ctrl, solo_mean  # candidate seat in all-candidate game vs baseline alone
    else:  # regular
        sa, sb = [], []
        for s in range(n):
            ra = _play([hero if i == s else "regular" for i in range(n)], deal)
            rb = _play([base if i == s else "regular" for i in range(n)], deal)
            lengths += [ra["steps"], rb["steps"]]
            truncs += ra["truncated"] + rb["truncated"]
            sa.append(_seat_stats(ra, s, n))
            sb.append(_seat_stats(rb, s, n))
        a, b = np.array(sa).mean(axis=0), np.array(sb).mean(axis=0)
    return {"diff": float(a[0] - b[0]), "a": a.tolist(), "b": b.tolist(), "len": float(np.mean(lengths)), "games": len(lengths), "trunc": truncs}


def summarize(label: str, n: int, res: list[dict], seconds: float) -> dict:
    d = [r["diff"] for r in res]
    k = len(d)
    sd = statistics.stdev(d) if k > 1 else float("nan")
    a = np.mean([r["a"] for r in res], axis=0)
    b = np.mean([r["b"] for r in res], axis=0)
    games = sum(r["games"] for r in res)
    return {
        "matchup": label, "players": n, "deals": k, "games": games,
        "diff": statistics.mean(d), "se": sd / math.sqrt(k), "sd_per_deal": sd,
        "a_score": a[0], "a_win": a[1], "a_illegal": a[2], "a_eights": a[3], "a_unplaced": a[4],
        "b_score": b[0], "b_win": b[1], "b_illegal": b[2], "b_eights": b[3], "b_unplaced": b[4],
        "fair_win": 1 / n, "mean_len": float(np.mean([r["len"] for r in res])),
        "truncations": sum(r["trunc"] for r in res), "seconds": round(seconds, 1),
    }


def time_moves(paths: dict[str, str], n: int, games: int) -> dict:
    """Single-process ms per NeuralAgent.choose for each policy, on its own moves in a mixed game."""
    _init(paths)
    out = {}
    for key in paths:
        other = next(k for k in paths if k != key) if len(paths) > 1 else key
        total, moves, fwd = 0.0, 0, 0.0
        for g in range(games):
            agents = [_agent(key if i == 0 else other, 900_000 + g * 10 + i) for i in range(n)]
            engine = IBFlipEngine(n, seed=900_000 + g)
            engine.record_events = False
            engine.reset()
            for i, ag in enumerate(agents):
                ag.fix(engine, i)
            for i in range(n):
                engine.fix_done(i)
            steps = 0
            while engine.state.phase is not Phase.GAME_OVER and steps < MAX_GAME_STEPS:
                resolve_forced(engine)
                if engine.state.phase is Phase.GAME_OVER:
                    break
                p = engine.state.current_player
                t = time.perf_counter()
                action = agents[p].choose(engine)
                dt = time.perf_counter() - t
                if p == 0:
                    total += dt
                    moves += 1
                engine.step(action, validate=False)
                steps += 1
        # pure forward pass, batch of 1
        pol = _POLICIES[key]
        x = np.random.default_rng(0).random(545, dtype=np.float32)
        mask = np.ones(20, dtype=bool)
        t = time.perf_counter()
        for _ in range(2000):
            pol.logits(x, mask)
        fwd = (time.perf_counter() - t) / 2000
        out[key] = {"choose_ms": 1000 * total / max(1, moves), "moves": moves, "forward_ms": 1000 * fwd}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--baseline", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--seed-base", type=int, default=7_400_000, help="first deal seed (fresh vs bench_search/training)")
    parser.add_argument("--workers", type=int, default=9)
    parser.add_argument("--report-every", type=int, default=200)
    parser.add_argument("--json", help="append one JSON line per finished matchup here")
    parser.add_argument("--timing", action="store_true", help="also measure single-process ms/move")
    parser.add_argument("plan", nargs="*", help="mode:players:deals  (mode = h2h | rev | regular)")
    args = parser.parse_args()
    paths = {"cand": args.candidate, "base": args.baseline}
    print(f"candidate {args.candidate}\nbaseline  {args.baseline}\nseed base {args.seed_base}", flush=True)
    if args.timing:
        for n in (2, 4):
            print(f"timing {n}p:", json.dumps(time_moves(paths, n, 20)), flush=True)
    with Pool(args.workers, initializer=_init, initargs=(paths,)) as pool:
        for item in args.plan:
            mode, n, deals = item.split(":")
            n, deals = int(n), int(deals)
            t0 = time.time()
            jobs = [(mode, n, args.seed_base + 1000 * n + d, "cand", "base") for d in range(deals)]
            res = []
            for r in pool.imap_unordered(run_deal, jobs, chunksize=4):
                res.append(r)
                if len(res) % args.report_every == 0 and len(res) < deals:
                    s = summarize(mode, n, res, time.time() - t0)
                    print(f"  .. {mode} {n}p {len(res)}/{deals}: {s['diff']:+.4f} ± {s['se']:.4f}  ({s['seconds']:.0f}s)", flush=True)
            s = summarize(mode, n, res, time.time() - t0)
            print(
                f"{mode:7} {n}p  diff {s['diff']:+.4f} ± {s['se']:.4f} (1 s.e., sd/deal {s['sd_per_deal']:.3f})  "
                f"A score {s['a_score']:+.4f} win {s['a_win']:.3f} | B score {s['b_score']:+.4f} win {s['b_win']:.3f} | fair {s['fair_win']:.3f}  "
                f"illegal A/B {s['a_illegal']:.4f}/{s['b_illegal']:.4f} 8s A/B {s['a_eights']:.4f}/{s['b_eights']:.4f}  "
                f"len {s['mean_len']:.0f} trunc {s['truncations']}/{s['games']}  [{deals} deals, {s['seconds']:.0f}s]",
                flush=True,
            )
            if args.json:
                with open(args.json, "a") as fh:
                    fh.write(json.dumps({**s, "candidate": args.candidate, "baseline": args.baseline, "seed_base": args.seed_base}) + "\n")


if __name__ == "__main__":
    main()
