"""Compress an actor while retaining its schema and source provenance."""
import sys
from pathlib import Path

import numpy as np


def export_model(src: str | Path, dst: str | Path) -> None:
    with np.load(src, allow_pickle=False) as data:
        values = {key: data[key].astype(np.float16) if data[key].dtype.kind == 'f' else data[key] for key in data.files}
    np.savez_compressed(dst, **values)


if __name__ == '__main__':
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / 'src/ibflip/ai/model.npz'
    export_model(src, dst)
    print('wrote', dst, Path(dst).stat().st_size, 'bytes')
