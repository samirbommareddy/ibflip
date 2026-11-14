# Shark v3 training preparation

> **Status (14 November 2026): closed for production.** The shipped
> `src/ibflip/ai/model.npz` remains the production Shark. The v3 pilot candidate
> (iteration 740) was +0.117 ± 0.009 at 2p but slightly worse at 4p and 5p, so it
> was not promoted (see [Candidate validation](#candidate-validation)). No
> further training or evaluation is planned. The pilot's artifacts are kept under
> the Git-ignored `runs/shark-v3-20261107-main-7c67960/` in the main checkout,
> together with this document and `scripts/validate_candidate.py`, in case the
> work resumes.

The audited Python engine is the rules authority. New policies have **545
observations and 20 actions**, with schema/version metadata embedded in exports.
The shipped `src/ibflip/ai/model.npz` remains unchanged and is an old-rules
baseline, not a trained v3 model.

## What changed

Actions 0–12 play a rank from the hand; 13–16 retain pickup, reveal, end-group and
face-down meanings. Actions 17–19 choose face-up slots 0–2. Only the engine's
legal cards in the chosen slot can be selected, including within an open group.
There are no duplicate rank actions for face-up cards.

Observations preserve the entire v1/v2 prefix and append public information:
rank and size of each of three slots for self and every opponent, placements,
finished flags, active turn distance in the current direction, active-player
count and the unclaimed placement range. Missing opponents are padded with
zeroes. No face-down identity or unknown opponent hand enters the actor.

Old 17-output models work through an explicit adapter: a visible slot receives
its rank's old logit. This is compatibility for baseline comparisons, not
retraining. A warm start copies shared layers, zero-pads new inputs and
initializes the three new output heads at zero. It does not pretend to preserve
the old policy's behavior on new slot decisions.

Fixing remains heuristic: choose strong visible cards, consolidate equal ranks
across visible slots (refilling any slot this empties with the best hand card,
since every face-up slot must hold a card before ready), then stack matching
hand cards and refill according to the engine. Validation runs recorded before
14 November 2026 used the earlier fixing, which could leave a slot empty. Runtime and training share this implementation, so stacks actually
occur in self-play. Learned fixing and search imitation remain separate future
experiments, not prerequisites for a valid rules-correct PPO run.

## Scoring and cutoffs

A completed game scores linearly by place: first +1, last −1. At a cutoff,
retain the score of an earned place and give **−1 only to unplaced seats**.
Training, arena, evaluation and search use this shared scoring function.
Complete games are zero-sum; cutoff games need not be. This retains credit for
finishing rather than punishing someone for later players' stalls.

The default cap is 3,000 policy decisions. Forced 9 draws do not count toward
that cap; they have no choice and a finite discard pile. The trainer passes its
configured cap to periodic evaluation too. Reports identify cutoffs even when
there is already a first-place player, and separate illegal finishes, eights
losses and ordinary last place. Evaluation uses the runtime NeuralAgent safety
and repetition logic. The PPO learner samples its raw masked policy, as before.

## Checkpoints and run identity

Each run writes `manifest.json`; `.npz` actors and `.pt` checkpoints embed the
same manifest. It records source revision/dirty status, hashes of Python source,
the PDF and audit rulings, schemas, scoring contract, configuration, random seed,
package versions and initialization-file hashes. It never captures `.env` or
environment credentials. The Modal image embeds the launching Git revision; source hashes also identify
the uploaded code when the container has no Git checkout.

Resume requires matching source digest and schemas. For changed code or old
checkpoints, use `--init-actor` and a new run directory instead. Output with an
existing checkpoint cannot silently start over. Actor/checkpoint replacement is
atomic, and exports preserve metadata while compressing floating weights.

The trainer bounds rollout/evaluation waits by its deadline and always saves the
latest checkpoint and terminates its workers on exit. A CPU minibatch/save can
finish after the requested deadline. The Modal wrapper has an additional hard
subprocess limit of requested duration plus one minute (then five seconds to
terminate), rejects output/duration overrides, and preserves the last checkpoint
if a worker stalls. Startup, image builds, storage and concurrent workloads
still need to be included in any free-credit budget; a duration is not a complete
billing cap.

## Local validation and smoke runs

CPU-only Torch is a training-time dependency, not added to runtime dependencies:

```bash
./scripts/with-env uv run --locked --with torch --index https://download.pytorch.org/whl/cpu python -m pytest -vv
./scripts/with-env uv run --locked --with torch --index https://download.pytorch.org/whl/cpu python scripts/train_ppo.py \
  --out runs/shark-v3-smoke --hours 0.03 --iterations 1 \
  --workers 2 --threads 2 --hidden 32,32 --decisions 128 \
  --epochs 1 --minibatch 128 --eval-every 1 --eval-games 4
```

Choose a new output directory or explicitly resume its checkpoint. For a warm
start from shipped weights omit `--hidden 32,32` (they use 512,512,256) and add
`--init-actor src/ibflip/ai/model.npz`. An old champion can be passed with
`--champion src/ibflip/ai/model.npz`. Smoke runs test the pipeline; their tiny
match counts say nothing reliable about playing strength.

Validation covers exact slot selection and group locking, distinguishing slot
partitions without changing the legacy prefix, finished-player features,
hidden-card invariance, legacy/new mixed tables, cutoff scoring, truncation
reporting, schema rejection, provenance-preserving export, secret exclusion,
Torch/NumPy logits parity, masked rollout actions and fixing/card conservation.
Local CLI smoke runs also exercise old-weight initialization, baseline matches
at 2–5 players, checkpoint writes and resume.

## Cloud status

At preparation time, no cloud compute had been launched. The read-only `modal billing summary --json`
returned zero metered/billed usage for this month. `modal billing rates --json`
also succeeded. These APIs do **not** establish the unused free-credit allowance;
the MSI dashboard redirects to login. The owner subsequently confirmed sufficient available free credit on 7 November
2026, satisfying the pre-launch check required by `AGENTS.md`. A generic monthly plan allowance is
not evidence of this account's available balance.

Read-only billing reports are stored under Git-ignored `runs/preflight/`.
Current billing APIs are documented at https://modal.com/docs/cli/latest/billing.
Once the balance is confirmed, reserve headroom for startup/storage/evaluation,
choose a bounded pilot that fits, and keep the old shipped model until a fresh
paired evaluation establishes a better candidate at every table size.

The current website calls the Python backend over WebSockets. There is no
separate browser rules-engine/network implementation to validate today. If a
browser Worker/offline port is built later, it requires trace and observation
parity tests before shipping.

Prepared-state verification (7 November 2026): the full Torch-enabled suite passed
**147 tests**; the final targeted v3 suite passed **16 tests** after tightening
metadata-version checks. A local warm-start pilot against the shipped baseline
completed training, checkpoint/export and comparisons at 2–5 players, with no
cutoffs in those small comparisons. This is pipeline validation, not strength
evidence. A separate local run resumed successfully at its next iteration.
Read-only identity checks confirmed that the workspace and login account match. The owner confirmed
enough remaining free credit before authorizing the
bounded pilot. A fresh read-only check showed no usage or other running apps.


## Authorized cloud pilot

The initial pilot is limited to two hours, 64 CPU cores and 32 GiB memory, with
hard CPU/memory limits and one training container. Live rates at launch were
$0.04730 per CPU-hour and $0.00800 per GiB-hour, estimating $6.5664 for the
two-hour training allocation. Startup/image-build/storage overhead is additional;
most of the confirmed credit is reserved rather than allocated to this first run.
No paid plan or automatic recharge was enabled.

Use the shipped old actor to initialize shared layers and as a frozen baseline.
Use 60 single-BLAS-thread rollout workers, 8 learner threads, 65,536 decisions per
iteration, the shared 3,000-decision cutoff, evaluation every 20 iterations (400
games per table size per direction), and snapshots every 5 iterations. Keep the
original model in place until larger fresh-seed evaluations validate a candidate.


### Pilot launch result

The 64-CPU request remained queued without starting a container and was stopped.
The replacement started on **16 CPUs with a hard 16-CPU limit**, 32 GiB memory,
14 rollout workers, 2 learner threads and 32,768 decisions per iteration. Its
training allocation estimate is **$2.0256 for two hours**, plus startup/storage
overhead. It was launched from clean local `main`, source revision
`7c67960df4cfc3928cb3703563e35ff9cd3ec7fd`, and the first PPO update completed
successfully after 402 self-play games. This establishes that the pipeline is
running; it is not evidence that the model is stronger yet.

- Started 7 November 2026 around 14:09 Europe/Stockholm; expected trainer cutoff
  around 16:09, with a short shutdown allowance.
- Run name: `shark-v3-20261107-main-7c67960`.
- Artifacts: `ibflip-runs` volume, under the run-name directory.
- Local receipt: `runs/shark-v3-20261107-main-7c67960/launch.json` (Git-ignored).
- Periodic volume commits run every five minutes. Snapshots are retained every
  five iterations; full checkpoints/latest actor are saved at evaluation and exit.
- No model promotion, Git push, website deployment or paid-plan change occurred.

### Monitoring and shutdown result

The local watchdog checked progress and billing every five minutes, kept an
absolute stop deadline, and downloaded verified backups around 30, 60 and 90
minutes. Modal restarted the container during the run; automatic resumption
reset the old per-process duration. The independent watchdog therefore stopped
the app at **16:12 Stockholm time**, rather than allowing that new timer to run
for another full window. Logs showed progress through iteration 757. The latest
committed actor and resumable checkpoint retained iteration 740.

Modal subsequently reported **zero containers**, with the app stopped and zero
tasks. The latest billing check (16:17 Stockholm time) reported **$2.11005220
metered**, covered by **$2.11 in credits** and the network allowance, with
**$0 billed**. Earlier snapshots reported $2.13 before billing adjustments settled. This is the
reported billing state at shutdown, not an assertion about unrelated future
workspace use.

Artifacts and monitoring receipts are downloaded under
`runs/shark-v3-20261107-main-7c67960/`. The shipped model was not changed. A fresh
validation is still required before promoting a candidate.

The wrapper now persists `run-budget.json` and commits its original absolute
deadline before starting the trainer. Container restarts consume only the
remaining time; they cannot reset or extend the original budget. Six local
regressions cover restarts, attempted extension, expiry and invalid budgets.
This fix was tested locally; no replacement cloud training was launched.


Final artifact verification checked all 38 actor files for readable schemas and
finite weights, confirmed the latest actor exactly matches the resumable Torch
checkpoint at iteration 740, and completed local smoke games at all four table
sizes. These are integrity/legality checks, not evidence for model promotion.
Logs include repeated iteration numbers from checkpoint resumption; do not sum
all log rows as if they were unique training updates.


## Candidate validation

Local-only validation on MSI, 9 November 2026 (no cloud compute). The shipped
`src/ibflip/ai/model.npz` was not modified or replaced, and nothing was promoted.

**Models.** Candidate = iteration **740**, `cloud-final/.../actor_00740.npz`,
SHA-256 `58d241d63e7a5741e3e0698444041d04f257afbbf46e5f5c4d3560a79ce67164`, identical to `actor_latest.npz` and to
`latest_actor_sha256` in `artifact-verification.json`. Backups map by hash to
iterations: 30 min → 160, 60 min → 360, **90 min → 560**. Baseline = shipped
Shark, `model.npz` SHA-256 `9f346475588b02fe0313c21173ead05d09eb6f3f40e13da6a5abbafd3b0e61c1`, a 17-action old-rules model
that plays the v3 engine through the legacy slot adapter. Both play as
`NeuralAgent` with the runtime defaults (greedy, safety veto, repetition guard),
as in the game. Regular = `HeuristicAgent`, the web's `medium` bot.

**Protocol** (`scripts/validate_candidate.py`). The unit of pairing is the deal
(engine seed). For each deal, the candidate plays every seat in turn against a
baseline table, and one all-baseline control game is played on the same deal with
the same per-seat agent seeds. The deal statistic is the mean candidate score
over seats minus the mean control score over seats. Standard errors are computed
over deals, never over the correlated games within a deal. `rev` is the reverse
direction: the baseline alone in a candidate table, against an all-candidate
control. At 2p it is the same experiment. `regular` puts the candidate and the
baseline each alone in the same Regular table, on the same deal and seat. Scores
use the shared placement score (1st +1, last −1, unplaced at a cutoff −1).
Positive means the candidate is better. The deals are fresh seeds (base
7,400,000), not used by training h2h or `bench_search.py`. A 200-deal pilot on
other seeds (base 100,000), used only for sizing, agreed with every result
below.

Per-deal standard deviations under seat rotation were 0.66 (2p), 0.41–0.46 (3p)
and 0.31–0.35 (4p). These are far below the 1.27 per-game figure in
`SHARK_PLAN.md`, so the deal counts below give tighter errors than the plan's
1,000-deal guidance.

### Results (mean score difference ± 1 s.e.; win = first-place rate)

| Players | Matchup | Deals (games) | Candidate − shipped | Candidate win | Shipped win | Fair |
|---|---|---|---|---|---|---|
| 2 | 740 vs shipped | 6,000 (18,000) | **+0.117 ± 0.009** | 0.558 | 0.499 | 0.500 |
| 3 | 740 alone in shipped table | 3,000 (12,000) | +0.007 ± 0.008 | 0.297 | 0.333 | 0.333 |
| 3 | shipped alone in 740 table (rev) | 1,500 (6,000) | +0.008 ± 0.012 | 0.333 | 0.368 | 0.333 |
| 4 | 740 alone in shipped table | 3,000 (15,000) | −0.002 ± 0.006 | 0.227 | 0.250 | 0.250 |
| 4 | shipped alone in 740 table (rev) | 1,500 (7,500) | **−0.020 ± 0.009** | 0.250 | 0.290 | 0.250 |

"Shipped win" is the shipped seat's rate in the paired game: the control game
for forward rows and the solo shipped seat for `rev` rows. "Candidate win" is
defined the same way for the candidate.

Sanity check against Regular (each model alone in a Regular table):

| Players | Deals (games) | Candidate score / win | Shipped score / win | Difference |
|---|---|---|---|---|
| 2 | 1,500 (6,000) | +0.541 / 0.770 | +0.543 / 0.772 | −0.003 ± 0.019 |
| 4 | 1,000 (8,000) | +0.186 / 0.306 | +0.187 / 0.326 | −0.001 ± 0.013 |

Training progress (90-minute backup, iteration 560, on the same deal seeds):

| Players | Matchup | Deals | Difference |
|---|---|---|---|
| 2 | 560 vs shipped | 2,000 | +0.111 ± 0.015 |
| 4 | 560 alone in shipped table | 1,500 | −0.006 ± 0.008 |
| 2 | 740 vs 560 (direct) | 2,000 | −0.017 ± 0.015 |

Other observations:
- Cutoffs: 16 of 18,000 games at 2p and at most 1 per matchup elsewhere.
- Illegal finishes occurred in 8–15 % of seats for both models at similar rates.
  Eights losses were ≤ 0.2 %.
- Average length per game: 2p ≈ 370 decisions (Shark vs Shark) versus ≈ 214 for
  the Regular table. 3–4p ran 250–340.
- At 3p and 4p the candidate has the same mean score but wins first place less
  often (0.297 vs 0.333 and 0.227 vs 0.250). It trades first places for fewer
  last places rather than playing better overall.

**Inference cost.** The architecture is unchanged (512-512-256 MLP). Only the
input width (545 vs 299 consumed) and the action head (20 vs 17) differ.
Single-process `NeuralAgent.choose` measured **0.24 ms/move (candidate) vs 0.28
ms/move (shipped)** at 2p and 0.25 vs 0.24 at 4p. A bare forward pass took 0.08–0.09
ms vs 0.12–0.13 ms. The shipped model pays for the legacy-adapter path. There is no
meaningful difference either way.

**Interpretation.**
- The candidate is clearly stronger at **2p**: +0.117 is 13 s.e. and well above
  the plan's +0.05 bar.
- At **3p** it is neutral in both directions, consistent with the ≥ 0 bar but not
  better.
- At **4p** the forward direction is neutral. The reverse direction is −0.020 ±
  0.009 (≈ 2.2 s.e.): a shipped seat does slightly better among candidates than
  the candidates do. That is a small multiplayer regression or noise, not yet
  resolved.
- Against Regular both models are indistinguishable at 2p and 4p, so the 2p gain
  is specific to Shark-vs-Shark play.
- Iteration 560 matches 740 at both sizes, and 740 does not beat 560 directly (−0.017 ± 0.015). Strength plateaued by roughly 90
  minutes, matching the flat training `h2h_mean` (≈ 0.02 from iteration ~500).
  More training with the same configuration is unlikely to fix 3–4p.
- 5p was not evaluated here; training h2h at 740 read −0.004 at 5p.

**Initial recommendation (9 November): do not promote yet.** The 4p result was
unresolved and 5p untested, so a targeted 4p/5p run followed. It is reported below
and supersedes this recommendation.

Reproduce (about 40 minutes on MSI with 9 workers):

```bash
R=runs/shark-v3-20261107-main-7c67960/cloud-final/shark-v3-20261107-main-7c67960
./scripts/with-env uv run --locked python -u scripts/validate_candidate.py --candidate $R/actor_00740.npz \
  --timing h2h:2:6000 h2h:3:3000 h2h:4:3000 rev:3:1500 rev:4:1500 regular:2:1500 regular:4:1000
```

### Follow-up: 4p and 5p (13 November 2026)

This was the targeted run recommended above. It was local only, on 10 workers,
with fresh deal seeds (base 8,500,000, which overlaps no earlier run). The
protocol, models and sign convention are the same as above. Wall clock was 34
minutes, and the planned deal counts ran in full.

| Players | Matchup | Deals (games) | Candidate − shipped | Candidate win | Shipped win | Fair |
|---|---|---|---|---|---|---|
| 4 | 740 alone in shipped table | 5,000 (25,000) | −0.007 ± 0.005 | 0.222 | 0.250 | 0.250 |
| 4 | shipped alone in 740 table (rev) | 5,000 (25,000) | **−0.015 ± 0.005** | 0.250 | 0.282 | 0.250 |
| 5 | 740 alone in shipped table | 3,000 (18,000) | **−0.018 ± 0.005** | 0.177 | 0.200 | 0.200 |
| 5 | shipped alone in 740 table (rev) | 3,000 (18,000) | −0.004 ± 0.005 | 0.200 | 0.219 | 0.200 |

Per-deal standard deviations were 0.32/0.35 at 4p and 0.26/0.28 at 5p
(forward/reverse). Cutoffs were at most 4 games per matchup. Illegal-finish rates
(10–13 %) and eights losses (≤ 0.2 %) were equal between models.

- **4p:** the reverse direction replicates the first run (−0.020 ± 0.009 then,
  −0.015 ± 0.005 now, ≈ 2.9 s.e.). The forward direction leans the same way
  (−0.007 ± 0.005).
- **5p:** a lone candidate loses −0.018 ± 0.005 (≈ 4 s.e.) in a shipped table.
  The reverse direction is neutral.
- Every 4p and 5p estimate is ≤ 0, and two of the four are clearly negative.
- In every multiplayer matchup the candidate's first-place rate is below the
  shipped model's.
- The deficit is small (0.5–2 % of the score range), but it is consistent.

**Updated recommendation: do not promote the candidate as the general Shark.**
- It fails the Phase A bar (≥ 0 at 3–5p) at 4p and 5p.
- It fails the stricter "better at every table size" rule outright: it is better
  only at 2p (+0.117 ± 0.009).
- No further deals are needed. The 4p/5p question is answered at s.e. ≈ 0.005.
  Larger samples would only refine a deficit that is already established.

Options, in order of preference:
1. **Keep the shipped `model.npz`** for all tables.
2. **Optional:** use the candidate for 2-player tables only. This would need a
   small runtime change to select the policy by table size (`rooms.py` currently
   loads one shared policy), plus a 2p regression check. That decision belongs
   to the owner; nothing has been changed.
3. **Next training run:** iteration 560 already matched 740, so strength had
   plateaued. Do not simply train longer. Re-weight `--player-counts` toward 4–5p
   (the pilot used an even 2–5p mix), and keep the shipped model as a league
   opponent. Accept a new candidate only if it shows ≥ 0 in both directions at
   3–5p with s.e. ≤ 0.005, about 5,000 deals at 4p and 3,000 at 5p.

Reproduce the follow-up (about 35 minutes on MSI with 10 workers):

```bash
R=runs/shark-v3-20261107-main-7c67960/cloud-final/shark-v3-20261107-main-7c67960
./scripts/with-env uv run --locked python -u scripts/validate_candidate.py --workers 10 --seed-base 8500000 \
  --candidate $R/actor_00740.npz h2h:4:5000 rev:4:5000 h2h:5:3000 rev:5:3000
```
