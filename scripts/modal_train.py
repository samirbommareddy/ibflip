"""Run scripts/train_ppo.py on a large Modal CPU container.

    modal run --detach scripts/modal_train.py --hours 4 --name main
    modal volume get ibflip-runs main/actor_latest.npz .
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
CPU = int(os.environ.get("IBFLIP_MODAL_CPU", "64"))

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("numpy", "torch", extra_index_url="https://download.pytorch.org/whl/cpu")
    .add_local_dir(ROOT / "src", "/app/src")
    .add_local_dir(ROOT / "scripts", "/app/scripts")
)
volume = modal.Volume.from_name("ibflip-runs", create_if_missing=True)
app = modal.App("ibflip-selfplay", image=image)


@app.function(cpu=CPU, memory=32768, timeout=24 * 3600, volumes={"/runs": volume})
def train(hours: float, name: str, extra: str = "") -> str:
    out = f"/runs/{name}"
    cmd = [
        sys.executable, "/app/scripts/train_ppo.py", "--out", out, "--hours", str(hours),
        "--workers", str(CPU * 2 - 4), "--threads", str(CPU), *extra.split(),
    ]
    if Path(out, "checkpoint.pt").exists() and "--resume" not in extra:
        cmd += ["--resume", f"{out}/checkpoint.pt"]
    print("running", " ".join(cmd), flush=True)
    stop = threading.Event()

    def committer():
        while not stop.wait(300):
            volume.commit()

    threading.Thread(target=committer, daemon=True).start()
    proc = subprocess.run(cmd)
    stop.set()
    volume.commit()
    return f"exit {proc.returncode}"


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
    load = lambda p: {k: v.astype(np.float32) for k, v in np.load(p if p.startswith("/") else f"/runs/{p}").items()}
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
