from __future__ import annotations

import hashlib

SPLITS = ("train", "val", "test")


def suggest_split(patient_key: str) -> str:
    """Patient-level split suggestion: 70% train, 15% val, 15% test.

    Chosen from a hash of the patient key only, so every case of one patient lands in the same
    split (no patient straddles train and test) and repeated exports agree. With only a handful of
    patients the shares are not meaningful."""
    digest = hashlib.sha256(("mussa-split:" + patient_key).encode()).hexdigest()
    bucket = int(digest[:8], 16) % 100
    if bucket < 70:
        return "train"
    if bucket < 85:
        return "val"
    return "test"
