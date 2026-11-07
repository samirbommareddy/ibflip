"""Persist a cloud run's absolute deadline across container restarts."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time


def remaining_run_hours(run_dir: Path, requested_hours: float, *, now: float | None = None) -> float:
    if not math.isfinite(requested_hours) or requested_hours <= 0:
        raise ValueError('requested training hours must be finite and positive')
    now = time.time() if now is None else now
    path = run_dir / 'run-budget.json'
    if path.exists():
        deadline = float(json.loads(path.read_text())['deadline_unix'])
        if not math.isfinite(deadline):
            raise ValueError('invalid persisted training deadline')
    else:
        run_dir.mkdir(parents=True, exist_ok=True)
        deadline = now + requested_hours * 3600
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'started_unix': now, 'deadline_unix': deadline,
                                         'requested_hours': requested_hours}) + '\n')
        temporary.replace(path)
    return max(0.0, (deadline - now) / 3600)
