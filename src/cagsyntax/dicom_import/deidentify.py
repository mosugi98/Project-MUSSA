from __future__ import annotations

import copy
import hashlib
import hmac
import re
import secrets
from pathlib import Path

import pydicom

# Blanked (Type-2) wherever they occur, including inside sequences.
BLANK = {"PatientName", "PatientBirthDate", "ReferringPhysicianName"}
# Removed wherever they occur, including inside sequences. Whole sequences that carry
# identifiers (requests, other patient IDs, physician identification) are dropped.
REMOVE = {
    "PatientAddress", "OtherPatientIDs", "OtherPatientIDsSequence", "OtherPatientNames",
    "PatientBirthTime", "PatientMotherBirthName", "PatientBirthName", "AccessionNumber",
    "IssuerOfPatientID", "IssuerOfAccessionNumberSequence", "StudyID",
    "RequestAttributesSequence", "RequestedProcedureID", "RequestedProcedureDescription",
    "RequestingPhysician", "RequestingService", "OperatorsName", "OperatorIdentificationSequence",
    "PerformingPhysicianName", "PerformingPhysicianIdentificationSequence",
    "NameOfPhysiciansReadingStudy", "PhysiciansReadingStudyIdentificationSequence",
    "PhysiciansOfRecord", "PhysiciansOfRecordIdentificationSequence",
    "ReferringPhysicianIdentificationSequence", "InstitutionName", "InstitutionAddress",
    "InstitutionalDepartmentName", "InstitutionCodeSequence", "StationName", "DeviceSerialNumber",
    "PatientTelephoneNumbers", "PatientComments", "ImageComments", "StudyComments",
    "AdditionalPatientHistory", "MedicalRecordLocator", "PatientInsurancePlanCodeSequence",
    "PerformedProcedureStepID",
}
# UIDs that can be looked up in the hospital PACS; remapped deterministically.
UID_KEYWORDS = {"StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "FrameOfReferenceUID",
                "ReferencedSOPInstanceUID", "SynchronizationFrameOfReferenceUID"}
META_REMOVE = ["SourceApplicationEntityTitle", "SendingApplicationEntityTitle",
               "ReceivingApplicationEntityTitle", "PrivateInformation", "PrivateInformationCreatorUID"]
# Values of these types are never compared in the leak scan (times, dates, numbers, UIDs).
# Only these carry a person's identity; other stripped fields (study ID, station, institution,
# comments) are labels that may legitimately recur in descriptions, so they are not leak-scanned.
SCAN_SOURCE_KEYWORDS = {"PatientID", "OtherPatientIDs", "AccessionNumber", "MedicalRecordLocator",
                        "PatientAddress", "PatientTelephoneNumbers", "RequestedProcedureID"}
SCAN_SKIP_VR = {"UI", "DA", "TM", "DT", "DS", "IS", "FD", "FL", "SL", "SS", "UL", "US", "OB", "OW", "SQ"}


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


def _remap_uid(uid: str, salt: bytes) -> str:
    digest = hmac.new(salt, str(uid).encode(), hashlib.sha256).digest()[:16]
    return "2.25." + str(int.from_bytes(digest, "big"))


def deidentify(ds: pydicom.Dataset, salt: bytes) -> tuple[pydicom.Dataset, str, list[str]]:
    """Return (de-identified copy, MRN hash, warnings). The input is not modified.
    The stored PatientID is the salted MRN hash so repeat cases can be linked."""
    warnings: list[str] = []
    mrn = str(ds.get("PatientID", "")).strip()
    mrn_hash = hash_mrn(mrn, salt) if mrn else ""
    if not mrn:
        warnings.append("no MRN in file; this case cannot be linked to others")
    out = copy.deepcopy(ds)

    def clean(dataset, elem):
        kw = elem.keyword
        if kw in BLANK:
            elem.value = ""
        elif kw in REMOVE:
            del dataset[elem.tag]
        elif kw in UID_KEYWORDS and elem.value:
            elem.value = _remap_uid(elem.value, salt)

    out.walk(clean, recursive=True)
    out.remove_private_tags()
    out.PatientID = mrn_hash
    out.PatientIdentityRemoved = "YES"
    if hasattr(out, "file_meta"):
        for kw in META_REMOVE:
            if kw in out.file_meta:
                del out.file_meta[kw]
        if "SOPInstanceUID" in out:
            out.file_meta.MediaStorageSOPInstanceUID = out.SOPInstanceUID
    if str(ds.get("BurnedInAnnotation", "")).upper() != "NO":
        warnings.append("burned-in annotation (present or not stated): pixels may contain "
                        "patient identifiers that tag removal cannot strip")
    return out, mrn_hash, warnings


def identifier_strings(ds: pydicom.Dataset) -> list[str]:
    """Uppercase strings that must not survive in stored output: person names (split into
    parts), patient IDs, accession numbers and similar identifiers, at any depth.
    Strings shorter than 3 characters are skipped."""
    found: set[str] = set()

    def collect(_dataset, elem):
        is_person_name = elem.VR == "PN" and (elem.keyword in BLANK or elem.keyword in REMOVE)
        if elem.VR == "SQ" or not (is_person_name or elem.keyword in SCAN_SOURCE_KEYWORDS):
            return
        values = elem.value if isinstance(elem.value, (list, pydicom.multival.MultiValue)) else [elem.value]
        for v in values:
            text = str(v).strip()
            parts = re.split(r"[\^=\s,]+", text) if elem.VR == "PN" else [text]
            found.update(p.upper() for p in parts if len(p) >= 3)

    ds.walk(collect, recursive=True)
    return sorted(found)


def scan_identifiers(ds: pydicom.Dataset, forbidden: list[str]) -> list[str]:
    """Return '<keyword> <tag>' for every element whose value still contains a forbidden
    string as a whole word. Times, dates, numbers and UIDs are not compared."""
    patterns = [re.compile(r"(?<![A-Z0-9])" + re.escape(f.upper()) + r"(?![A-Z0-9])")
                for f in forbidden if f]
    leaks = []
    for elem in ds.iterall():
        if elem.keyword == "PixelData" or elem.VR in SCAN_SKIP_VR:
            continue
        text = str(elem.value).upper()
        if any(p.search(text) for p in patterns):
            leaks.append(f"{elem.keyword or 'private'} {elem.tag}")
    return leaks
