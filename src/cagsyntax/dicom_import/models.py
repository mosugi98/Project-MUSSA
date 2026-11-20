from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pydicom


class ImportRejected(Exception):
    """A file could not be imported. The message is shown to the user."""


@dataclass
class XASeries:
    dataset: pydicom.Dataset
    frames: np.ndarray  # (n, rows, cols)
    fps: float
    primary_angle: float | None
    secondary_angle: float | None
    sop_instance_uid: str
    source: Path
