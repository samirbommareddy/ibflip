"""Public, credential-free provenance embedded in new policy artifacts."""
from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import subprocess

from ibflip.ai.arena import MAX_GAME_STEPS, SCORING_VERSION, TIMEOUT_REWARD
from ibflip.ai.observation import ACTION_VERSION, NUM_COMPACT_ACTIONS, OBSERVATION_VERSION, OBS_SIZE


def schema() -> dict:
    return {
        'observation_version': OBSERVATION_VERSION, 'observation_size': OBS_SIZE,
        'action_version': ACTION_VERSION, 'action_count': NUM_COMPACT_ACTIONS,
        'scoring_version': SCORING_VERSION, 'timeout_reward': TIMEOUT_REWARD,
        'max_steps_default': MAX_GAME_STEPS,
    }


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(root: Path, config: dict) -> dict:
    # Explicit paths only: never collect environment variables or .env files.
    paths = sorted([*root.glob('src/**/*.py'), *root.glob('scripts/*.py')])
    paths += [p for p in (root / 'docs/rules-audit.md', root / 'IB-Flip__The_Complete_Rules.pdf') if p.exists()]
    hashes = {str(p.relative_to(root)): file_hash(p) for p in paths}
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=root, text=True))
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = os.environ.get('IBFLIP_SOURCE_REVISION', 'unknown'), None
    packages = {}
    for name in ('numpy', 'torch'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            pass
    return {
        'schema': schema(), 'revision': revision, 'dirty': dirty,
        'source_hashes': hashes,
        'source_digest': hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        'config': config, 'packages': packages,
        'initialization': {key: file_hash(Path(config[key])) for key in ('init_actor', 'champion', 'resume') if config.get(key)},
    }
