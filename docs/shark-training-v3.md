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
environment credentials. In a container without Git, source hashes still identify
the uploaded code; revision may be `unknown`.

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

No cloud compute has been launched. The read-only `modal billing summary --json`
returned zero metered/billed usage for this month. `modal billing rates --json`
also succeeded. These APIs do **not** establish the unused free-credit allowance;
the MSI dashboard redirects to login. Remaining free credit must be confirmed
before launch, as required by `AGENTS.md`. A generic monthly plan allowance is
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
`samir-bommareddy`. The owner expects a $30 allowance; available balance has not
yet been independently confirmed.
