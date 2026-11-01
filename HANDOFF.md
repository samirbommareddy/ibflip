# Handoff: next phase (deployment + Shark in the browser + design iteration)

Written at the end of a session so a fresh session (with new env vars) can
continue. Delete this file when the phase is done.

## PRIORITY #1 — Shark-with-search experiment (user: "should not lose focus!!")

Before/alongside the deployment work, run the search benchmark and report it:

```bash
uv run python -u scripts/bench_search.py fix:2:200 fix:4:200 search:4:200 search:2:120 search:3:150
```

It is slow on 4 local cores (hours for the 2p search arm): run it in the
background (`nohup ... > /tmp/bench_search.log &`) and read the running
estimates as they come (every 40 deals). If Modal credit allows, the same
paired design can be fanned out on Modal for more games.

Questions to answer for the user:
1. Does policy + PIMC search beat policy-only Shark, by how much, at 2/3/4p?
2. Does searched hand-fixing (`search_fix`) beat the heuristic fixing?
3. Cost: ms per move. The browser bar is ~1 s/move on a mid-range phone,
   measured in the JS/Worker implementation; CPython timings are a proxy.
4. If search helps: ship it in the browser Worker (budgeted by time), and
   consider distilling search back into the network (train the policy to
   imitate search choices, i.e. expert iteration) so even policy-only Shark
   gets stronger. If it doesn't help: say so with numbers and ship policy-only.

## HARD RULE (from the user)

The user must never be charged. Never add payment methods, upgrade plans,
pick paid instance types, buy add-ons/domains, or enable anything metered.
If something only works on a paid tier: stop and tell the user.

## The user's request, verbatim intent

Env vars expected: `CLOUDFLARE_API_TOKEN` (Pages:Edit, DNS:Edit + Zone:Read for
ibflip.com), `CLOUDFLARE_ACCOUNT_ID`, `RENDER_API_KEY`. Network allowlist:
api.cloudflare.com, api.render.com, *.pages.dev, *.onrender.com, ibflip.com.
If the env vars are missing, tell the user. ibflip.com nameservers point to
Cloudflare (meiling/piotr.ns.cloudflare.com); the domain is registered at
Squarespace. **Check the zone status via the API before relying on DNS.**
Netlify is dropped: don't deploy there; delete `netlify.toml` once Pages works.

Target architecture (all free):

1. **Frontend**: Cloudflare Pages project `ibflip` serving `static/` at
   ibflip.com (www → apex redirect). Deploy with `npx wrangler pages deploy`.
   Every branch gets a preview (`<branch>.ibflip.pages.dev`); production
   deploys from `main`. If auto-deploy on merge needs a GitHub Actions secret
   or a dashboard GitHub connection, give the user the exact clicks.
2. **Rooms API**: existing Render free web service at `api.ibflip.com`. Add
   the custom domain via the Render API; create CNAME `api → ibflip.onrender.com`
   in Cloudflare with `proxied=false` (DNS-only) so Render can issue its cert.
   Frontend uses `https://api.ibflip.com` for HTTP + WebSockets; keep
   localhost behaviour for dev. `render.yaml`: `runtime: python`,
   `healthCheckPath: /health`, `plan: free`.
3. Render sleeps after 15 min idle: show a friendly "waking the server…"
   state for rooms, and "room expired" (not errors) after a restart.
4. **Shark**: benchmark policy-only vs policy + PIMC search (win rate gained vs
   ms/move). Ship search only if it clearly helps within ~1 s/move on a
   mid-range phone; otherwise policy-only. Report the numbers.
5. **Solo vs bots fully in the browser** (no server): engine + Shark (+search
   if shipped) in a Web Worker. User prefers Pyodide (one codebase); a JS port
   is OK only with parity tests against the Python engine.
6. **Rooms with humans + bots**: server stays authoritative (deals, validates
   every move). Bot turns go to the host's browser with only that bot's legal
   observation (own hand + public info, never other humans' hands). Host runs
   Shark in a Web Worker and returns the move. If no reply in ~3 s, or the
   host disconnects, the server plays a policy-only move; host duty passes to
   the next human.
7. **Design iteration** (after the above works): 2–3 distinct design
   directions (static/ only), each on its own branch with a Pages preview.
   Check each at 390px phone and desktop widths with Playwright; send the user
   preview links + screenshots. They want a cleaner option than the current
   "casino" look, and animations must be really smooth.

Run `uv run pytest -q` and merge to `main` when green. Verify the live site
with a browser smoke test before reporting done. Continue improving Shark
alongside and update based on results.

## Decisions already made

- **JS port over Pyodide** (explain to the user): search needs thousands of
  playouts per move and Pyodide is ~3–10× slower than CPython; Pyodide+numpy
  is ~15 MB on a phone; and pyodide's numpy wheel is served from a CDN this
  sandbox cannot reach, so it couldn't be tested here. Plan: port
  `src/ibflip/engine.py`, `src/ibflip/rules.py`, `src/ibflip/ai/observation.py`
  (`compact_legal`, `encode` incl. v2 "lacks" features), the MLP forward,
  `NeuralAgent` (incl. `RepetitionGuard`), `heuristic_fix`, `HeuristicAgent`,
  `_EasyAgent` (src/ibflip_web/rooms.py) and, if shipped, `determinize` +
  `PimcAgent` to an ES module under `static/` usable in a Worker and in Node.
  **Parity tests**: Python generates traces (wrap `random.Random` to log
  `randrange` results and `shuffle` permutations; the engine uses RNG only in
  `reset` shuffle, nine-draw `randrange`, nine-flip `shuffle`), JS replays
  them and must match state, legal actions and observation vectors at every
  step. Run JS tests with node from pytest (or a separate npm script).
- Model for the browser: export `src/ibflip/ai/model.npz` (float16, MLP
  299-input v2 obs; w0 may have 299 rows) to a compact binary + JSON header
  in `static/`; decode float16 in JS.

## State of the AI work

- Shipped model `src/ibflip/ai/model.npz` = round-3 champion (`champion/c3.npz`
  on the Modal volume `ibflip-runs`). Vs the first champion: 2p +0.218,
  3p +0.059, 4p +0.015, 5p +0.003 (6000 games/size/direction).
- `src/ibflip/ai/pimc.py`: policy-guided PIMC (`PimcAgent`: searches only when
  policy max-prob < gate; top-k candidates × N determinized worlds, playouts by
  the policy) and `search_fix` (searches the face-up arrangement). **Not yet
  benchmarked — see PRIORITY #1.** Script: `scripts/bench_search.py`, paired design — same deal seed played twice, once with the hero
  variant and once with plain Shark in the same seat, others Shark; report the
  mean score difference ± s.e. Timings measured: a searched 2p game ≈ 57 s on
  one CPython core (search fires at ~25% of decisions), 4p ≈ 1 s; search_fix
  with 8 worlds ≈ 4.4 s. Earlier finding: PIMC with *heuristic* playouts was
  worse than the policy alone; this version uses policy playouts.
- Training scripts: `scripts/train_ppo.py` (PPO self-play, champion league,
  h2h eval), `scripts/modal_train.py` (`::main` to train, `::compare` for
  6000-game head-to-head), `scripts/evaluate.py` (vs baseline bots).
- Modal: ~$27 of the $30 monthly credit used this month (Nov). Use only if
  clearly worth it. The Modal token must come from env vars
  (`MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET`) — never write it to the repo.

## Sandbox gotchas

- `pkill -f <pattern>` / `pgrep -f` match the invoking shell's own command
  line and kill it (exit 144). Use `ps aux | grep "[x]pattern"` or a script.
- Modal client behind the proxy: `pip install 'modal[api-proxy-support]'`
  and `export SSL_CERT_FILE=/root/.ccr/ca-bundle.crt`. Detached runs must use
  `.spawn()` (already done in `modal_train.py::main`).
- Training deps (torch) live outside the project; install into a separate
  venv: `uv venv /tmp/trainenv/.venv && uv pip install -p ... torch numpy modal[api-proxy-support]`.
- Playwright + Chromium are preinstalled (`require('playwright')`).
- Local dev: `uv run uvicorn ibflip_web.main:app --port 8000` serves the API
  and the front-end.
