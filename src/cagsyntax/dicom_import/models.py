from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class ImportedItem:
    stored_path: Path
    sop_instance_uid: str
    mrn_hash: str
    view_label: str
    study_date: str
    series_description: str
    warnings: list[str]


@dataclass
class ImportResult:
    imported: list[ImportedItem] = field(default_factory=list)
    skipped_duplicates: list[Path] = field(default_factory=list)
    rejected: list[tuple[Path, str]] = field(default_factory=list)


@dataclass
class SeriesHeader:
    """What the series list needs, read without decoding pixel data."""
    view_label: str
    series_description: str
    study_date: str
    burned_in_unclear: bool  # BurnedInAnnotation is anything other than "NO"
