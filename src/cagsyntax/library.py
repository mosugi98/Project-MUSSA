from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LABEL = "Unsorted"


@dataclass
class Entry:
    path: Path
    uid: str
    label: str


class Library:
    """The app's store of de-identified series plus the user-chosen folder label of each.
    Labels live in folders.json (never inside the DICOM files) and are shown as folder names.
    Deleting only ever removes the app's own copies, never a source file."""

    def __init__(self, data_dir: Path):
        self.store_dir = Path(data_dir) / "store"
        self._index_path = Path(data_dir) / "folders.json"
        self._labels: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}  # missing or corrupt index: series fall back to the default label

    def _save(self) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._index_path.with_name(self._index_path.name + ".tmp")
        tmp.write_text(json.dumps(self._labels, indent=1), encoding="utf-8")
        os.replace(tmp, self._index_path)

    def entries(self) -> list[Entry]:
        found = [Entry(p, p.stem, self._labels.get(p.stem, DEFAULT_LABEL))
                 for p in self.store_dir.glob("*.dcm")]
        return sorted(found, key=lambda e: (e.label.lower(), e.path.name))

    def labels(self) -> list[str]:
        return sorted({e.label for e in self.entries()}, key=str.lower)

    def assign(self, uids: list[str], label: str) -> None:
        label = label.strip() or DEFAULT_LABEL
        for uid in uids:
            self._labels[uid] = label
        self._save()

    def delete_series(self, uid: str) -> bool:
        if Path(uid).name != uid or not uid:
            raise ValueError(f"invalid series id: {uid!r}")
        path = self.store_dir / f"{uid}.dcm"
        existed = path.exists()
        path.unlink(missing_ok=True)
        if self._labels.pop(uid, None) is not None:
            self._save()
        return existed

    def delete_folder(self, label: str) -> int:
        uids = [e.uid for e in self.entries() if e.label == label]
        for uid in uids:
            self.delete_series(uid)
        return len(uids)

    def rename_folder(self, old: str, new: str) -> int:
        new = new.strip()
        if not new:
            return 0
        uids = [e.uid for e in self.entries() if e.label == old]
        if uids:
            self.assign(uids, new)
        return len(uids)
