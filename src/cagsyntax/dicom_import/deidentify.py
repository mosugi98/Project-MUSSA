from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
from pathlib import Path

import pydicom

# Type-2 elements are blanked; the rest are removed.
BLANK = ["PatientName", "PatientID", "PatientBirthDate", "ReferringPhysicianName"]
REMOVE = [
    "PatientAddress", "OtherPatientIDs", "OtherPatientNames", "PatientBirthTime",
    "PatientMotherBirthName", "AccessionNumber", "StudyID", "OperatorsName",
    "PerformingPhysicianName", "PhysiciansOfRecord", "InstitutionName",
    "InstitutionAddress", "InstitutionalDepartmentName", "StationName",
    "DeviceSerialNumber", "PatientTelephoneNumbers", "PatientComments",
]


def get_or_create_salt(data_dir: Path) -> bytes:
    path = Path(data_dir) / "salt.key"
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(32)
    path.write_bytes(salt)
    return salt


def hash_mrn(mrn: str, salt: bytes) -> str:
    return hmac.new(salt, mrn.strip().upper().encode(), hashlib.sha256).hexdigest()


def deidentify(ds: pydicom.Dataset, salt: bytes) -> tuple[pydicom.Dataset, str, list[str]]:
    """Return (de-identified copy, MRN hash, warnings). The input is not modified."""
    warnings: list[str] = []
    mrn = str(ds.get("PatientID", "")).strip()
    mrn_hash = hash_mrn(mrn, salt) if mrn else ""
    if not mrn:
        warnings.append("no MRN in file; this case cannot be linked to others")
    out = copy.deepcopy(ds)
    for kw in BLANK:
        if kw in out:
            out[kw].value = ""
    for kw in REMOVE:
        if kw in out:
            del out[kw]
    out.remove_private_tags()
    out.PatientIdentityRemoved = "YES"
    if str(ds.get("BurnedInAnnotation", "")).upper() == "YES":
        warnings.append("burned-in annotation: pixels may contain patient identifiers "
                        "that tag removal cannot strip")
    return out, mrn_hash, warnings


def scan_identifiers(ds: pydicom.Dataset, forbidden: list[str]) -> list[str]:
    """Return a description of every element whose value still contains a forbidden string."""
    needles = [f.upper() for f in forbidden if f]
    leaks = []
    for elem in ds.iterall():
        if elem.keyword == "PixelData" or elem.VR == "SQ":
            continue
        text = str(elem.value).upper()
        if any(n in text for n in needles):
            leaks.append(f"{elem.tag} {elem.keyword or 'private'}")
    return leaks
