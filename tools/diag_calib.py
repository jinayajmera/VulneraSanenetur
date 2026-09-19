"""tools/diag_calib.py — rank calibration points by leave-one-out error."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robosurge.sensor_fusion import (
    LocalAffineMapper,
    CALIBRATION_PHYSICAL_PTS as P,
    CALIBRATION_PIXEL_PTS as X,
)

m = LocalAffineMapper(P, X)
e = m.leave_one_out_errors()
print("worst leave-one-out calibration points:")
for i in np.argsort(e)[::-1]:
    print(f"  phys={str(P[i]):14s} pixel={str(X[i]):18s} err={e[i]:5.2f} cm")
