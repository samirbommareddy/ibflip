"""Run scripts/train_ppo.py on a large Modal CPU container.

    modal run --detach scripts/modal_train.py --hours 4 --name main
    modal volume get ibflip-runs main/actor_latest.npz .
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
CPU = 64

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
    print(train.remote(hours, name, extra))


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
