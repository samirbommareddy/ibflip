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
opponents' hands or even your own face-down cards. The Shark bot combines:

1. **A policy network trained by self-play (PPO).** One shared policy plays
   every seat in 2–5 player games; a league of frozen past snapshots and the
   heuristic bot fill some seats so it doesn't overfit to itself. The actor
   sees only what a player legitimately knows (incl. cards seen being picked
   up); the critic additionally sees hidden cards during training
   (asymmetric actor-critic), which reduces variance.
2. **Search at decision time.** For each candidate move, sample hidden cards
   consistent with everything public, play the game out, and pick the move
   with the best average outcome.

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
