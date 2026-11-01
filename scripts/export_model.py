"""Copy a trainer checkpoint (actor_*.npz) into the package as float16."""
import sys
from pathlib import Path

import numpy as np

src, dst = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / "src/ibflip/ai/model.npz")
data = np.load(src)
np.savez_compressed(dst, **{k: data[k].astype(np.float16) for k in data.files})
print("wrote", dst, Path(dst).stat().st_size, "bytes")
