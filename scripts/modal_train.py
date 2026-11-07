"""Run scripts/train_ppo.py on a large Modal CPU container.

    modal run --detach scripts/modal_train.py --hours 4 --name main
    modal volume get ibflip-runs main/actor_latest.npz .
"""

from __future__ import annotations

import os
import math
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
CPU = int(os.environ.get("IBFLIP_MODAL_CPU", "64"))


def source_revision() -> str:
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return os.environ.get('IBFLIP_SOURCE_REVISION', 'unknown')

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("numpy", "torch", extra_index_url="https://download.pytorch.org/whl/cpu")
    .env({"IBFLIP_SOURCE_REVISION": source_revision()})
    .add_local_dir(ROOT / "src", "/app/src")
    .add_local_dir(ROOT / "scripts", "/app/scripts")
    .add_local_file(ROOT / "docs/rules-audit.md", "/app/docs/rules-audit.md")
    .add_local_file(ROOT / "IB-Flip__The_Complete_Rules.pdf", "/app/IB-Flip__The_Complete_Rules.pdf")
)
volume = modal.Volume.from_name("ibflip-runs", create_if_missing=True)
app = modal.App("ibflip-selfplay", image=image)


@app.function(cpu=(CPU, CPU), memory=(32768, 32768), max_containers=1, retries=0, timeout=24 * 3600, volumes={"/runs": volume})
def train(hours: float, name: str, extra: str = "") -> str:
    if not math.isfinite(hours) or not 0 < hours <= 8:
        raise ValueError("training duration must be finite and at most eight hours")
    if not name or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError("run name must stay inside the runs volume")
    parts = shlex.split(extra)
    if any(part.split('=')[0] in ('--hours', '--out') for part in parts):
        raise ValueError("extra arguments cannot override the duration or output")
    out = f"/runs/{name}"
    cmd = [
        sys.executable, "/app/scripts/train_ppo.py", "--out", out, "--hours", str(hours),
        "--workers", str(max(1, CPU * 2 - 4)), "--threads", str(CPU), *shlex.split(extra),
    ]
    if Path(out, "checkpoint.pt").exists():
        # Restarted (e.g. preempted) run: continue from our own checkpoint,
        # never from the original --resume source.
        parts = shlex.split(extra)
        for option in ("--resume", "--init-actor"):
            if option in parts:
                i = parts.index(option)
                del parts[i : i + 2]
            parts = [part for part in parts if not part.startswith(option + '=')]
        cmd = cmd[: cmd.index("--threads") + 2] + parts + ["--resume", f"{out}/checkpoint.pt"]
    print("running", " ".join(cmd), flush=True)
    stop = threading.Event()

    def committer():
        while not stop.wait(300):
            volume.commit()

    threading.Thread(target=committer, daemon=True).start()
    proc = subprocess.Popen(cmd, start_new_session=True)
    try:
        return f"exit {proc.wait(timeout=hours * 3600 + 60)}"
    except subprocess.TimeoutExpired:
        # Bound billing even if learner/evaluation gets stuck. Kill its whole
        # process group, including rollout workers, and retain the last atomic
        # checkpoint. Leave reserve credit for image build/startup and storage.
        import signal
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        return "stopped at hard wall-time limit"
    finally:
        stop.set()
        volume.commit()


@app.local_entrypoint()
def main(hours: float = 4.0, name: str = "main", extra: str = ""):
    # spawn() so the run survives this client exiting (use with --detach).
    call = train.spawn(hours, name, extra)
    print("spawned", call.object_id)


@app.function(cpu=1, volumes={"/runs": volume}, timeout=600)
def fetch(paths: list[str]) -> dict[str, bytes]:
    """Return small files from the volume (the blob host may be firewalled)."""
    volume.reload()
    out = {}
    for p in paths:
        full = Path("/runs") / p
        if full.exists():
            out[p] = full.read_bytes()
    return out


@app.local_entrypoint()
def pull(paths: str, dest: str = "/tmp/modal_runs"):
    """modal run scripts/modal_train.py::pull --paths main/log.jsonl,main/actor_latest.npz"""
    files = fetch.remote(paths.split(","))
    for name, data in files.items():
        target = Path(dest) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print("wrote", target, len(data))


@app.function(cpu=32, memory=16384, timeout=3 * 3600, volumes={"/runs": volume})
def h2h(candidates: list[str], champion: str, games: int = 6000) -> list[dict]:
    """Head-to-head of each candidate vs the champion at 2-5 players.

    For each player count, `games` games with ONE candidate seat vs a table of
    champions and `games` with one champion vs candidates. Reports the mean
    of the two seat scores' difference (>0: candidate stronger) +- 2 s.e.
    """
    import os
    import multiprocessing as mp

    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    sys.path.insert(0, "/app/scripts")
    sys.path.insert(0, "/app/src")
    import numpy as np
    from train_ppo import h2h_worker

    volume.reload()
    load = lambda p: dict(np.load(p if p.startswith("/") else f"/runs/{p}", allow_pickle=False))
    champ = load(champion)
    out = []
    with mp.get_context("fork").Pool(31) as pool:
        for cand in candidates:
            w = load(cand)
            row = {"candidate": cand}
            diffs = []
            for n in (2, 3, 4, 5):
                per = games // 31 + 1
                a = pool.map(h2h_worker, [(w, champ, n, per, 7 * c + n) for c in range(31)])
                b = pool.map(h2h_worker, [(champ, w, n, per, 100003 + 7 * c + n) for c in range(31)])
                ga = sum(x["games"] for x in a)
                sa = sum(x["score"] for x in a) / ga
                sb = sum(x["score"] for x in b) / ga
                d = (sa - sb) / 2
                row[f"{n}p"] = round(d, 4)
                row[f"{n}p_win"] = round(sum(x["wins"] for x in a) / ga, 4)
                diffs.append(d)
            row["mean"] = round(float(np.mean(diffs)), 4)
            print(row, flush=True)
            out.append(row)
    return out


@app.local_entrypoint()
def compare(candidates: str, champion: str = "champion/a880.npz", games: int = 6000):
    """modal run scripts/modal_train.py::compare --candidates e1_multi/actor_01455.npz,..."""
    for row in h2h.remote(candidates.split(","), champion, games):
        print(row)
