# IB-Flip

A web card game for friends and bots, an exact rules engine, and a self-play
trained AI opponent ("Shark").

- **Play with friends**: create a room, share the 4-letter code or invite link,
  fill empty seats with bots, play in real time over WebSockets.
- **Play vs bots**: Rookie (sloppy heuristic), Regular (solid heuristic),
  Shark (neural policy trained by self-play, plus search).
- Full rules in `IB-Flip__The_Complete_Rules.pdf`; an in-game "How to play"
  sheet includes a what-can-go-on-what matrix.

## Layout

| Path | What |
|---|---|
| `src/ibflip/engine.py` | Rules engine (`IBFlipEngine`): legal actions, `step()`, simultaneous hand fixing, public-knowledge tracking (`Player.known_hand`), event stream for UIs |
| `src/ibflip/env.py` | PettingZoo AEC environment |
| `src/ibflip/ai/observation.py` | 17-action rank-level action space + card-counting observation encoder (only legal information) |
| `src/ibflip/ai/agents.py` | Random / heuristic bots and the numpy-only neural agent (no torch at runtime) |
| `src/ibflip/ai/search.py` | Determinized Monte-Carlo search (PIMC) over hidden cards |
| `src/ibflip/ai/model.npz` | Trained policy weights (exported by the trainer) |
| `scripts/train_ppo.py` | PPO self-play trainer (torch, training-time only) |
| `scripts/modal_train.py` | Runs the trainer on a 64-core Modal container |
| `src/ibflip_web/` | FastAPI app: rooms, seats, bots, per-player (hidden-info safe) views, WebSockets |
| `static/` | Front-end (vanilla JS/CSS, no build step) |

## Run locally

```bash
uv run uvicorn ibflip_web.main:app --reload
```

Open http://127.0.0.1:8000 — the backend also serves the front-end. (If you
serve `static/` from another local port, the client talks to `:8000`.)

## Tests

```bash
uv run pytest -q
uv run python scripts/stress_test.py --games 20000   # random-play fuzzing
```

## How the AI works

IB-Flip is a multiplayer game of imperfect information: you can't see the deck,
opponents' hands or even your own face-down cards. Shark is a policy network
trained purely by self-play (PPO):

- One shared policy plays every seat in 2–5 player games; a league of frozen
  past snapshots and the heuristic bot fills some seats so it doesn't overfit
  to itself.
- The actor sees only what a player legitimately knows, including card
  counting and cards everyone saw going into an opponent's hand. The critic
  additionally sees the hidden cards during training (asymmetric
  actor-critic), which reduces variance.
- A game that hits the step cap counts as a loss for everyone, so the policy
  never learns to stall.
- At runtime it's a ~1 MB numpy MLP (no torch), with a guard that varies its
  play if the game stops making progress.

`src/ibflip/ai/search.py` holds an experimental determinized search; with cheap
playouts it played worse than the policy alone, so Shark doesn't use it.

Benchmark (`scripts/evaluate.py`, 400 games each, win rate vs fair share):

| Players | Shark alone vs heuristic bots | Shark alone vs random bots | Heuristic bot alone vs Sharks |
|---|---|---|---|
| 2 | 70% (50%) | 82% | 7% |
| 3 | 39% (33%) | 75% | 12% |
| 4 | 28.5% (25%) | 54% | 16% |
| 5 | 18% (20%) | 32% | 14.5% |

Train (needs torch; not a runtime dependency):

```bash
python scripts/train_ppo.py --hours 2 --out runs/local
# or on Modal (64 cores):
modal run --detach scripts/modal_train.py::main --hours 4 --name main
```

Then copy `runs/<name>/actor_latest.npz` to `src/ibflip/ai/model.npz`.

## Deploy

- **Backend** (Render, `render.yaml`): `uvicorn ibflip_web.main:app`.
- **Front-end** (Netlify, `netlify.toml`): publishes `static/`; the client
  talks to the API URL in the `ibflip-api` meta tag of `static/index.html`.
