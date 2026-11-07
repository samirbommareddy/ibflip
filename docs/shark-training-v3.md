# Shark v3 training preparation

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
across visible slots, then stack matching hand cards and refill according to the
engine. Runtime and training share this implementation, so stacks actually
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
the MSI dashboard redirects to login. The owner subsequently confirmed $30 in available free credit on 7 November
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
Read-only identity checks confirm both workspace and login account are
`samir-bommareddy`. The owner confirmed $30 in remaining free credit before authorizing the
bounded pilot. A fresh read-only check showed no usage or other running apps.


## Authorized cloud pilot

The initial pilot is limited to two hours, 64 CPU cores and 32 GiB memory, with
hard CPU/memory limits and one training container. Live rates at launch were
$0.04730 per CPU-hour and $0.00800 per GiB-hour, estimating $6.5664 for the
two-hour training allocation. Startup/image-build/storage overhead is additional;
most of the confirmed $30 is reserved rather than allocated to this first run.
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
- Dashboard: https://modal.com/apps/samir-bommareddy/main/ap-5KwrtufBE2z4bn3bXC8sHu
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
