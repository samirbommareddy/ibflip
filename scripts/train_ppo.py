"""PPO self-play trainer for IB-Flip.

* One shared policy plays every seat (2-5 players per game, mixed).
* League: some seats are filled with frozen past snapshots and the heuristic
  bot so the policy does not overfit to itself.
* Asymmetric actor-critic: the actor only sees legal information (what the
  web bot will see); the critic additionally sees the hidden cards during
  training, which cuts variance in this imperfect-information game.
* Rollouts run in worker processes using the *numpy* actor (identical to the
  deployed inference code); learning uses torch.

Usage (torch is only needed here, not at runtime):
    python scripts/train_ppo.py --hours 3 --out runs/main
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import sys
import time
from pathlib import Path

# One BLAS thread per process: rollouts run in many worker processes, and
# multi-threaded BLAS in each of them oversubscribes the CPU badly (torch
# sets its own thread count separately).
for _var in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ibflip.ai.agents import HeuristicAgent, MLPPolicy, RandomAgent, heuristic_fix  # noqa: E402
from ibflip.ai.arena import evaluate, game_result, score  # noqa: E402
from ibflip.ai.observation import (  # noqa: E402
    NUM_COMPACT_ACTIONS,
    NUM_RANKS,
    OBS_SIZE,
    MAX_OPPONENTS,
    compact_legal,
    encode,
    opponent_order,
    resolve_forced,
)
from ibflip.cards import RANK_INDEX_BY_ID  # noqa: E402
from ibflip.engine import IBFlipEngine  # noqa: E402
from ibflip.state import Phase  # noqa: E402

PRIV_SIZE = NUM_RANKS * (2 + 2 * MAX_OPPONENTS)
MAX_STEPS = 1000  # overridden by --max-steps


def privileged(engine: IBFlipEngine, player_index: int) -> np.ndarray:
    out = np.zeros(PRIV_SIZE, dtype=np.float32)
    st = engine.state
    for c in st.players[player_index].face_down_slots:
        if c is not None:
            out[RANK_INDEX_BY_ID[c]] += 0.25
    for c in st.draw_pile:
        out[NUM_RANKS + RANK_INDEX_BY_ID[c]] += 0.25
    for k, opp in enumerate(opponent_order(engine, player_index)):
        base = NUM_RANKS * (2 + 2 * k)
        for c in st.players[opp].hand:
            out[base + RANK_INDEX_BY_ID[c]] += 0.25
        for c in st.players[opp].face_down_slots:
            if c is not None:
                out[base + NUM_RANKS + RANK_INDEX_BY_ID[c]] += 0.25
    return out


def sample(policy: MLPPolicy, obs: np.ndarray, mask: np.ndarray, rng: np.random.Generator) -> tuple[int, float]:
    logits = policy.logits(obs, mask)
    z = logits - logits.max()
    p = np.exp(z) * mask
    p /= p.sum()
    a = int(rng.choice(NUM_COMPACT_ACTIONS, p=p))
    return a, float(np.log(p[a] + 1e-12))


class PolicySeat:
    def __init__(self, policy: MLPPolicy, rng: np.random.Generator) -> None:
        self.policy = policy
        self.rng = rng

    def fix(self, engine, idx):
        heuristic_fix(engine, idx)


# --------------------------------------------------------------------------
# Rollout worker
# --------------------------------------------------------------------------
def rollout_worker(args) -> dict:
    weights, pool, n_decisions, seed, cfg = args
    rng = np.random.default_rng(seed)
    prng = random.Random(seed)
    learner = MLPPolicy(weights)
    pool_policies = [MLPPolicy(w) for w in pool]
    champion = MLPPolicy(cfg["champion"]) if cfg.get("champion") is not None else None
    heuristic = HeuristicAgent(seed)

    buf = {k: [] for k in ("obs", "priv", "mask", "act", "logp", "ret_idx")}
    episodes: list[list[int]] = []  # per-trajectory list of buffer indices
    rewards: list[float] = []
    n = 0
    games = 0
    timeouts_count = 0
    lens = []
    while n < n_decisions:
        num_players = prng.choice(cfg["player_counts"])
        engine = IBFlipEngine(num_players, seed=prng.randrange(2**31))
        engine.record_events = False
        engine.reset()
        # seat assignment
        seats: list = ["L"] * num_players
        roll = prng.random()
        c_frac = cfg["champion_frac"] if champion is not None else 0.0
        league_frac = (1.0 - c_frac) * (1.0 - cfg["selfplay_frac"])
        if roll < c_frac:
            # One learner (sometimes two) against a table of the champion.
            heroes = set(prng.sample(range(num_players), 1 if num_players < 4 or prng.random() < 0.7 else 2))
            seats = ["L" if i in heroes else champion for i in range(num_players)]
        elif roll < c_frac + league_frac:
            hero = prng.randrange(num_players)
            for i in range(num_players):
                if i == hero:
                    continue
                r = prng.random()
                if r < cfg["heuristic_frac"] or not pool_policies:
                    seats[i] = "H"
                else:
                    seats[i] = prng.choice(pool_policies)
        for i in range(num_players):
            heuristic_fix(engine, i)
            engine.fix_done(i)
        traj: dict[int, list[int]] = {i: [] for i in range(num_players) if seats[i] == "L"}
        steps = 0
        while engine.state.phase is not Phase.GAME_OVER and steps < cfg["max_steps"]:
            resolve_forced(engine)
            if engine.state.phase is Phase.GAME_OVER:
                break
            cur = engine.state.current_player
            mask, mapping = compact_legal(engine)
            seat = seats[cur]
            if seat == "H":
                a = heuristic.choose_compact(engine, mask)
            elif mask.sum() == 1:
                a = int(np.flatnonzero(mask)[0])
            else:
                obs = encode(engine, cur)
                if seat == "L":
                    a, logp = sample(learner, obs, mask, rng)
                    buf["obs"].append(obs)
                    buf["priv"].append(privileged(engine, cur))
                    buf["mask"].append(mask.copy())
                    buf["act"].append(a)
                    buf["logp"].append(logp)
                    traj[cur].append(n)
                    n += 1
                else:
                    a, _ = sample(seat, obs, mask, rng)
            engine.step(prng.choice(mapping[a]), validate=False)
            steps += 1
        result = game_result(engine)
        timed_out = engine.state.phase is not Phase.GAME_OVER
        for i, idxs in traj.items():
            if idxs:
                episodes.append(idxs)
                # A stalled game is a loss for everyone: never worth dragging out.
                rewards.append(cfg["timeout_reward"] if timed_out else score(result, i, num_players))
        games += 1
        lens.append(steps)
        timeouts_count += int(timed_out)
    return {
        "obs": np.asarray(buf["obs"], dtype=np.float32),
        "priv": np.asarray(buf["priv"], dtype=np.float32),
        "mask": np.asarray(buf["mask"], dtype=bool),
        "act": np.asarray(buf["act"], dtype=np.int64),
        "logp": np.asarray(buf["logp"], dtype=np.float32),
        "episodes": episodes,
        "rewards": rewards,
        "games": games,
        "mean_len": float(np.mean(lens)) if lens else 0.0,
        "timeouts": timeouts_count,
    }


def selfplay_len_worker(args) -> dict:
    """Greedy policy vs itself: long games mean the policy learned to stall."""
    weights, num_players, games, seed = args
    policy = MLPPolicy(weights)
    rng = random.Random(seed)
    lens = []
    for _ in range(games):
        engine = IBFlipEngine(num_players, seed=rng.randrange(2**31))
        engine.record_events = False
        engine.reset()
        for i in range(num_players):
            heuristic_fix(engine, i)
            engine.fix_done(i)
        steps = 0
        while engine.state.phase is not Phase.GAME_OVER and steps < 3000:
            resolve_forced(engine)
            if engine.state.phase is Phase.GAME_OVER:
                break
            mask, mapping = compact_legal(engine)
            if mask.sum() == 1:
                a = int(np.flatnonzero(mask)[0])
            else:
                a = int(np.argmax(policy.logits(encode(engine, engine.state.current_player), mask)))
            engine.step(rng.choice(mapping[a]), validate=False)
            steps += 1
        lens.append(steps)
    return {"lens": lens}


def h2h_worker(args) -> dict:
    """Mean score of ONE `hero` seat vs a table of `villain` (deployed agent logic)."""
    hero_w, villain_w, num_players, games, seed = args
    from ibflip.ai.agents import NeuralAgent
    from ibflip.ai.arena import play_game

    hero_p, villain_p = MLPPolicy(hero_w), MLPPolicy(villain_w)
    rng = random.Random(seed)
    total, wins = 0.0, 0
    for g in range(games):
        seat = g % num_players
        agents = [NeuralAgent(hero_p if i == seat else villain_p, seed=rng.randrange(2**31)) for i in range(num_players)]
        result = play_game(agents, seed=rng.randrange(2**31), max_steps=1500)
        total += score(result, seat, num_players)
        wins += result["winner"] == seat
    return {"score": total, "wins": wins, "games": games}


def eval_worker(args) -> dict:
    weights, num_players, games, seed, opponent = args
    policy = MLPPolicy(weights)

    class Greedy:
        def __init__(self):
            self.rng = random.Random(seed)

        def fix(self, engine, idx):
            heuristic_fix(engine, idx)

        def choose(self, engine):
            mask, mapping = compact_legal(engine)
            if mask.sum() == 1:
                a = int(np.flatnonzero(mask)[0])
            else:
                a = int(np.argmax(policy.logits(encode(engine, engine.state.current_player), mask)))
            return self.rng.choice(mapping[a])

    villain = {"heuristic": HeuristicAgent, "random": RandomAgent}[opponent]
    return evaluate(Greedy, villain, num_players, games, seed=seed)


# --------------------------------------------------------------------------
# Learner
# --------------------------------------------------------------------------
def build_models(torch, hidden: list[int]):
    nn = torch.nn

    class Actor(nn.Module):
        def __init__(self):
            super().__init__()
            layers, d = [], OBS_SIZE
            for h in hidden:
                layers += [nn.Linear(d, h), nn.ReLU()]
                d = h
            self.trunk = nn.Sequential(*layers)
            self.head = nn.Linear(d, NUM_COMPACT_ACTIONS)
            nn.init.orthogonal_(self.head.weight, 0.01)
            nn.init.zeros_(self.head.bias)

        def forward(self, x, mask):
            logits = self.head(self.trunk(x))
            return logits.masked_fill(~mask, -1e9)

    class Critic(nn.Module):
        def __init__(self):
            super().__init__()
            layers, d = [], OBS_SIZE + PRIV_SIZE
            for h in hidden:
                layers += [nn.Linear(d, h), nn.ReLU()]
                d = h
            layers += [nn.Linear(d, 1)]
            self.net = nn.Sequential(*layers)

        def forward(self, x, priv):
            return self.net(torch.cat([x, priv], dim=-1)).squeeze(-1)

    return Actor(), Critic()


def widen_inputs(torch, ck) -> bool:
    """Function-preserving upgrade of an older checkpoint to a wider
    observation: new input features get zero weights."""
    w = ck["actor"]["trunk.0.weight"]
    old = w.shape[1]
    if old == OBS_SIZE:
        return False
    pad = torch.zeros(w.shape[0], OBS_SIZE - old)
    ck["actor"]["trunk.0.weight"] = torch.cat([w, pad], dim=1)
    cw = ck["critic"]["net.0.weight"]
    ck["critic"]["net.0.weight"] = torch.cat([cw[:, :old], torch.zeros(cw.shape[0], OBS_SIZE - old), cw[:, old:]], dim=1)
    print(f"widened inputs {old} -> {OBS_SIZE}", flush=True)
    return True


def export_actor(actor) -> dict:
    out = {}
    linears = [m for m in actor.trunk if hasattr(m, "weight")]
    for i, lin in enumerate(linears):
        out[f"w{i}"] = lin.weight.detach().cpu().numpy().T.copy()
        out[f"b{i}"] = lin.bias.detach().cpu().numpy().copy()
    out["pw"] = actor.head.weight.detach().cpu().numpy().T.copy()
    out["pb"] = actor.head.bias.detach().cpu().numpy().copy()
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="runs/main")
    parser.add_argument("--hours", type=float, default=2.0)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--decisions", type=int, default=65536, help="decisions per iteration")
    parser.add_argument("--hidden", default="512,512,256")
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--minibatch", type=int, default=4096)
    parser.add_argument("--clip", type=float, default=0.2)
    parser.add_argument("--ent", type=float, default=0.01)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--eval-every", type=int, default=10)
    parser.add_argument("--snapshot-every", type=int, default=10)
    parser.add_argument("--resume", default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--eval-games", type=int, default=400)
    parser.add_argument("--async-rollouts", type=int, default=1)
    parser.add_argument("--player-counts", default="2,2,3,3,4,4,5,5")
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--champion", default=None, help="actor .npz to train against and evaluate head-to-head")
    parser.add_argument("--champion-frac", type=float, default=0.35)
    parser.add_argument("--h2h-games", type=int, default=2000, help="games per player count per direction")
    parser.add_argument("--lr-end", type=float, default=None, help="linearly decay LR to this by the deadline")
    parser.add_argument("--init-actor", default=None, help="actor .npz to initialise from")
    parser.add_argument("--timeout-reward", type=float, default=-1.0)
    args = parser.parse_args()

    import torch

    torch.set_num_threads(args.threads or max(1, (os.cpu_count() or 2)))
    torch.manual_seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    hidden = [int(h) for h in args.hidden.split(",")]
    actor, critic = build_models(torch, hidden)
    opt = torch.optim.Adam(list(actor.parameters()) + list(critic.parameters()), lr=args.lr, eps=1e-5)
    pool: list[dict] = []
    start_iter = 0
    if args.resume:
        ck = torch.load(args.resume, weights_only=False)
        widened = widen_inputs(torch, ck)
        actor.load_state_dict(ck["actor"])
        critic.load_state_dict(ck["critic"])
        if not widened:
            opt.load_state_dict(ck["opt"])
        pool = ck.get("pool", [])
        start_iter = ck.get("iter", 0)

    champion_w = dict(np.load(args.champion)) if args.champion else None
    if champion_w is not None:
        champion_w = {k: v.astype(np.float32) for k, v in champion_w.items()}
    if args.init_actor:
        init = np.load(args.init_actor)
        linears = [m for m in actor.trunk if hasattr(m, "weight")]
        with torch.no_grad():
            for i, lin in enumerate(linears):
                w_init = init[f"w{i}"].astype(np.float32)
                if i == 0 and w_init.shape[0] < OBS_SIZE:
                    w_init = np.concatenate([w_init, np.zeros((OBS_SIZE - w_init.shape[0], w_init.shape[1]), np.float32)])
                lin.weight.copy_(torch.from_numpy(w_init.T))
                lin.bias.copy_(torch.from_numpy(init[f"b{i}"].astype(np.float32)))
            actor.head.weight.copy_(torch.from_numpy(init["pw"].astype(np.float32).T))
            actor.head.bias.copy_(torch.from_numpy(init["pb"].astype(np.float32)))
    cfg = {
        "player_counts": [int(x) for x in args.player_counts.split(",")],
        "selfplay_frac": 0.6,
        "heuristic_frac": 0.3,
        "max_steps": args.max_steps,
        "champion": champion_w,
        "champion_frac": args.champion_frac,
        "timeout_reward": args.timeout_reward,
    }
    ctx = mp.get_context("fork")
    procs = ctx.Pool(args.workers)
    deadline = time.time() + args.hours * 3600
    log = open(out / "log.jsonl", "a")
    it = start_iter
    seed_rng = random.Random(args.seed + start_iter)
    per = args.decisions // args.workers

    def launch():
        w = export_actor(actor)
        jobs = [(w, pool[-16:], per, seed_rng.randrange(2**31), cfg) for _ in range(args.workers)]
        return procs.map_async(rollout_worker, jobs)

    # Rollouts for iteration k+1 run while the learner updates on k (one
    # iteration of policy lag; PPO's ratio uses the behaviour log-probs).
    pending = launch()
    t_start = time.time()
    while time.time() < deadline:
        t0 = time.time()
        if args.lr_end is not None:
            frac = min(1.0, (t0 - t_start) / max(1.0, deadline - t_start))
            for group in opt.param_groups:
                group["lr"] = args.lr + (args.lr_end - args.lr) * frac
        results = pending.get()
        t_roll = time.time() - t0
        pending = launch() if args.async_rollouts else None

        obs = np.concatenate([r["obs"] for r in results])
        priv = np.concatenate([r["priv"] for r in results])
        mask = np.concatenate([r["mask"] for r in results])
        act = np.concatenate([r["act"] for r in results])
        old_logp = np.concatenate([r["logp"] for r in results])
        offsets = np.cumsum([0] + [len(r["act"]) for r in results])
        episodes, rewards = [], []
        for off, r in zip(offsets, results):
            for idxs, rew in zip(r["episodes"], r["rewards"]):
                episodes.append([off + i for i in idxs])
                rewards.append(rew)

        with torch.no_grad():
            values = critic(torch.from_numpy(obs), torch.from_numpy(priv)).numpy()
        adv = np.zeros(len(act), dtype=np.float32)
        ret = np.zeros(len(act), dtype=np.float32)
        lam = args.gae_lambda
        for idxs, rew in zip(episodes, rewards):
            next_v, gae = 0.0, 0.0
            for j in reversed(range(len(idxs))):
                i = idxs[j]
                r = rew if j == len(idxs) - 1 else 0.0
                delta = r + next_v - values[i]
                gae = delta + lam * gae
                adv[i] = gae
                ret[i] = gae + values[i]
                next_v = values[i]

        t_obs = torch.from_numpy(obs)
        t_priv = torch.from_numpy(priv)
        t_mask = torch.from_numpy(mask)
        t_act = torch.from_numpy(act)
        t_old = torch.from_numpy(old_logp)
        t_adv = torch.from_numpy((adv - adv.mean()) / (adv.std() + 1e-8))
        t_ret = torch.from_numpy(ret)
        N = len(act)
        stats = {"pl": 0.0, "vl": 0.0, "ent": 0.0, "kl": 0.0, "clipfrac": 0.0}
        nb = 0
        for _ in range(args.epochs):
            perm = torch.randperm(N)
            for s in range(0, N, args.minibatch):
                b = perm[s : s + args.minibatch]
                logits = actor(t_obs[b], t_mask[b])
                logp_all = torch.log_softmax(logits, -1)
                logp = logp_all.gather(1, t_act[b, None]).squeeze(1)
                ratio = torch.exp(logp - t_old[b])
                a_b = t_adv[b]
                pl = -torch.min(ratio * a_b, torch.clamp(ratio, 1 - args.clip, 1 + args.clip) * a_b).mean()
                probs = logp_all.exp()
                ent = -(probs * torch.where(t_mask[b], logp_all, torch.zeros_like(logp_all))).sum(-1).mean()
                v = critic(t_obs[b], t_priv[b])
                vl = ((v - t_ret[b]) ** 2).mean()
                loss = pl + 0.5 * vl - args.ent * ent
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(list(actor.parameters()) + list(critic.parameters()), 0.5)
                opt.step()
                with torch.no_grad():
                    stats["pl"] += pl.item()
                    stats["vl"] += vl.item()
                    stats["ent"] += ent.item()
                    stats["kl"] += (t_old[b] - logp).mean().item()
                    stats["clipfrac"] += ((ratio - 1).abs() > args.clip).float().mean().item()
                nb += 1
        stats = {k: v / nb for k, v in stats.items()}
        if pending is None:
            pending = launch()
        it += 1
        rec = {
            "iter": it,
            "decisions": int(N),
            "games": sum(r["games"] for r in results),
            "mean_len": float(np.mean([r["mean_len"] for r in results])),
            "mean_reward": float(np.mean(rewards)) if rewards else 0.0,
            "timeouts": sum(r["timeouts"] for r in results),
            "t_roll": round(t_roll, 1),
            "t_total": round(time.time() - t0, 1),
            **{k: round(v, 4) for k, v in stats.items()},
        }

        if it % args.snapshot_every == 0:
            pool.append(export_actor(actor))
            pool = pool[-24:]
        if it % args.eval_every == 0:
            w = export_actor(actor)
            chunks = max(1, args.workers)
            if champion_w is not None:
                combined = []
                for np_ in (2, 3, 4, 5):
                    per_h2h = max(2, args.h2h_games // chunks)
                    a = procs.map(h2h_worker, [(w, champion_w, np_, per_h2h, 1000003 * it + 31 * c + np_) for c in range(chunks)])
                    b = procs.map(h2h_worker, [(champion_w, w, np_, per_h2h, 2000003 * it + 31 * c + np_) for c in range(chunks)])
                    sa = sum(x["score"] for x in a) / sum(x["games"] for x in a)
                    sb = sum(x["score"] for x in b) / sum(x["games"] for x in b)
                    rec[f"h2h_{np_}p"] = round((sa - sb) / 2, 4)  # >0: candidate beats champion
                    combined.append((sa - sb) / 2)
                rec["h2h_mean"] = round(float(np.mean(combined)), 4)
            else:
                per_chunk = max(4, args.eval_games // chunks)
                for np_ in (2, 4):
                    ev = procs.map(eval_worker, [(w, np_, per_chunk, 7919 * it + 31 * c + np_, "heuristic") for c in range(chunks)])
                    rec[f"eval_{np_}p_score"] = round(float(np.mean([e["mean_score"] for e in ev])), 4)
            np.savez(out / f"actor_{it:05d}.npz", **w)
            np.savez(out / "actor_latest.npz", **w)
            torch.save(
                {"actor": actor.state_dict(), "critic": critic.state_dict(), "opt": opt.state_dict(), "pool": pool, "iter": it, "hidden": hidden},
                out / "checkpoint.pt",
            )
        print(json.dumps(rec), flush=True)
        log.write(json.dumps(rec) + "\n")
        log.flush()

    w = export_actor(actor)
    np.savez(out / "actor_latest.npz", **w)
    torch.save(
        {"actor": actor.state_dict(), "critic": critic.state_dict(), "opt": opt.state_dict(), "pool": pool, "iter": it, "hidden": hidden},
        out / "checkpoint.pt",
    )
    procs.close()


if __name__ == "__main__":
    main()
