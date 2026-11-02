# Shark retraining plan

A plan for the next time Modal credit is available. It uses what we learned from
three rounds of PPO, the search benchmark, and the rule changes of November 2026.

## Where Shark is today

| | |
|---|---|
| Network | MLP 299 → 512 → 512 → 256 → 17 policy logits (+ value head in training), ~0.5 M parameters, `src/ibflip/ai/model.npz` (~1 MB) |
| Actions | 17 rank-level "compact" actions (play rank r, pick up, reveal, end group, flip face-down) |
| Training | PPO self-play (`scripts/train_ppo.py`), one shared policy for 2–5 players, league of frozen snapshots + heuristic bot, asymmetric critic that sees hidden cards |
| Fixing (choosing face-up cards) | Hand-written `heuristic_fix`, not learned |
| Strength history | Round 3 vs round 1: 2p +0.218, 3p +0.059, 4p +0.015, 5p +0.003 (6,000 games per size per seat) |
| Speed (one CPython core) | ~10 games/s at 2p, ~15 games/s at 4p for four Sharks; ~40 games/s with heuristic bots |

### Results we already have

* **Search at play time (PIMC, policy playouts, 16 worlds, top-3, gate 0.9)**: 2p **+0.068 ± 0.052** over 600 paired deals (≈ 53 % vs 50 % win rate), 3p +0.003 ± 0.062, 4p +0.027 ± 0.039. Search fired on 26 % of 2p moves at ~1.5 s each in CPython. Not worth shipping.
* **Searched hand fixing** (16 worlds): no gain at 2p (+0.035 ± 0.089) or 4p (−0.017 ± 0.052).
* **Evaluation noise**: a paired 2p deal has a standard deviation of ~1.27 score points, so ±0.05 needs ~600 paired deals and ±0.03 needs ~1,800. Budget evaluation like training, not as an afterthought.

## Why the current model has to be retrained

The rules changed under it. Each change alters what good play looks like, and some change what the
network can even express:

1. **Draw after every card** in the early game (a drawn card of the same rank can join the play).
2. **Face-up groups only from one stacked slot.** The compact action space says "play a 7"; it cannot say *which* face-up slot. With the slot rule this choice now matters, and the agent picks a slot at random.
3. **Pickup is a choice** early on (reveal the deck top *or* pick up), and **forbidden in a 4 chain** if you hold a 4, 5 or 6.
4. **Games run to full placements** with 3+ players. The model was trained with "first finish ends the game" and a win/lose reward; it never learned to fight for 2nd vs 3rd, and it has never seen finished players in its input.
5. **Ace-as-one, consecutive 5s and the 9-flip fixes** shift card values slightly.

Fine-tuning the old weights is possible for (1), (3) and (5), but (2) and (4) need a new input and
output layout, so plan on a fresh run that initialises the shared layers from the old model.

## What to change before spending compute

### 1. Observation v3

Keep everything in v2 and add:

* Per opponent (in seat order relative to me): finished flag, place (one-hot), and turns until they move.
* My face-up slots as **slots**: for each of 3 slots, its rank and stack size (today they are pooled).
* Opponents' face-up slots the same way.
* Play state: direction, 4-chain active and its depth, 9-draw pending, "5 under" target, ace-as-one on top, cards in the live pile.
* Public card counting: how many of each rank are gone for good (discard), seen in hands, in the live pile.
* Players remaining, and my current place range (best and worst place still possible).

### 2. Action space v3

17 compact actions + **3 face-up slot actions** ("play face-up slot k"). The engine already knows
which cards each slot holds, so the mapping is direct. That is 20 logits; the browser cost is unchanged.

### 3. Learn the hand fixing

Fixing decides a lot (what you are left with in the middle and end game) and is the least-trained part.
Enumerate the distinct arrangements (usually under 20 by rank), score each with the **value head**
on the resulting position, and pick the best (or sample during training). No extra network and no
per-world search, unlike `search_fix`, which was slow and did not help.

### 4. Placement reward

Score = linear in place (1st +1 … last −1), already implemented in `ibflip.ai.arena.score` and in
`train_ppo.py`. Add a small bonus for an **illegal-finish avoidance** auxiliary signal only if early
runs show the agent finishing on 2s and 10s more often than the heuristic bot.

### 5. Faster self-play

Self-play speed decides how far the budget goes. In order of payoff:

1. Batch the policy forward pass across many games per worker (one matrix multiply for 64 games instead of 64 small ones). Likely 3–5× on its own.
2. Skip forced moves without calling the network (already done for single-legal-move states; extend to "end group" when no same-rank card is left).
3. Profile `engine.step` and `encode`; a 2× from caching legal-move masks is plausible.

### 6. JavaScript parity first

The browser runs a JavaScript port of the engine and the network. Build the parity tests (Python
writes traces, JS replays them, states and observation vectors must match) **before** training, so the
model we evaluate is exactly the model players face.

## Search from the start? (expert iteration)

The idea: run search during self-play, train the policy to imitate search's choices, repeat. This is
how AlphaZero-style systems get strong, and it fixes the weakness we measured: policy-only Shark makes
mistakes in uncertain spots that a search could catch.

Why not run it naively from step one:

* **Cost.** At ~1.5 s per searched 2p move in CPython and search on ~25 % of moves, a searched game is
  ~60× slower than a policy game. A $30 month buys a few thousand searched games, not the millions
  PPO uses.
* **Weak search early.** Search with policy playouts is only as good as the policy. Our PIMC gained
  +0.07 on a well-trained policy; on a random early policy it adds noise.
* **Imperfect information.** Plain determinization (PIMC) suffers from strategy fusion: it assumes it
  will know the hidden cards later. That is a likely reason the gain was small.

Recommended instead, in three phases:

| Phase | What | Rough compute | Pass if |
|---|---|---|---|
| A. PPO on the new rules | obs v3 + actions v3, init from old weights where shapes match, league with old Shark (adapted) and heuristic. Train on mixed 2–5p. | 60–70 % of budget | Beats heuristic at every size; beats old Shark on the new rules by ≥ +0.05 at 2p and ≥ 0 at 3–5p (paired, ≥ 1,000 deals per size) |
| B. Value-guided search, then imitate | Replace full playouts with **truncated rollouts scored by the value head** (5–10 moves deep), sample worlds from a belief that respects `known_hand` and `lacks_mask`, and only search when the policy is unsure (gate). Collect searched decisions from self-play; train the policy on them (cross-entropy to search's visit distribution, plus the usual PPO loss). | 25–30 % | Policy after imitation beats phase A policy by ≥ +0.03 at 2p with no search at play time |
| C. Evaluate and ship | Paired evaluation at every size vs phase A, old Shark and heuristic; JS parity check; browser latency check (≤ 30 ms per move without search on a mid-range phone). | 5–10 % | Ship the best policy; keep search out of the browser unless it gains ≥ +0.10 within 1 s per move |

Phase B gives the benefit of search (better decisions in uncertain spots) without paying for it in the
browser, and its search is far cheaper than the PIMC we benchmarked because a value estimate replaces
the 100+ move playout.

## Compute and money

* Hard rule: **the user is never charged.** Use only the free Modal credit ($30/month); stop runs
  before it runs out; never pick paid add-ons.
* Use preemptible CPU containers; the network is small, so a GPU does not pay for itself.
* Checkpoint every ~10 minutes to the `ibflip-runs` volume so a stopped run loses nothing.
* Spend about a quarter of each phase's budget on evaluation. Without it we cannot tell a +0.03
  improvement from noise.

## Evaluation protocol (keep it)

* **Paired deals**: same deal seed played twice, hero variant vs baseline in the same seat, others fixed. Report mean score difference ± 1 s.e.
* **Sizes**: 2p (most sensitive), 3p, 4p, 5p separately; never pool sizes.
* **Fresh seeds** for confirmation runs: the first search run read +0.20 on 120 deals and settled at +0.07 on 600.
* **Placement-aware score**: 1st +1 … last −1.
* Also log: average game length (stalling), illegal-finish rate, and 8s-flip rate.

## Order of work

1. Obs v3 + actions v3 + learned fixing, with tests (no compute needed).
2. JS port with parity tests (no compute needed).
3. Batched self-play speed-up; measure games/s before and after.
4. Phase A on Modal.
5. Phase B on Modal.
6. Phase C, then ship to the browser Worker.
