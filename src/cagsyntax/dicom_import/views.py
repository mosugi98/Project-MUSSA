from __future__ import annotations

UNKNOWN_VIEW = "Unknown view"


def label_view(primary: float | None, secondary: float | None) -> str:
    """Label a C-arm view. DICOM convention: +primary = LAO, -primary = RAO;
    +secondary = CRAN, -secondary = CAUD. Vendor exports may differ, so verify
    against a real file."""
    if primary is None or secondary is None:
        return UNKNOWN_VIEW
    p, s = round(primary), round(secondary)
    parts = []
    if p:
        parts.append(f"{'LAO' if p > 0 else 'RAO'} {abs(p)}")
    if s:
        parts.append(f"{'CRAN' if s > 0 else 'CAUD'} {abs(s)}")
    return " ".join(parts) or "AP"
