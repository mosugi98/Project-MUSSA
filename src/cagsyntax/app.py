from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QFileDialog, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QSplitter)

from .dicom_import.deidentify import get_or_create_salt
from .dicom_import.importer import import_path
from .dicom_import.models import ImportRejected, ImportResult
from .dicom_import.reader import read_header, read_xa
from .dicom_import.views import label_view
from .viewer.widget import CineWidget

PATH_ROLE = 0x100  # Qt.UserRole
BURNED_IN_FLAG = " | check burned-in text"


def row_text(view: str, description: str, study_date: str, burned_in_unclear: bool) -> str:
    return f"{view} | {description} | {study_date}{BURNED_IN_FLAG if burned_in_unclear else ''}"


def format_summary(result: ImportResult) -> str:
    lines = [f"Imported: {len(result.imported)}",
             f"Duplicates skipped: {len(result.skipped_duplicates)}",
             f"Rejected: {len(result.rejected)}"]
    lines += [f"  - {msg}" for _, msg in result.rejected]
    for item in result.imported:
        lines += [f"  ! {item.stored_path.name}: {w}" for w in item.warnings]
    return "\n".join(lines)


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path):
        super().__init__()
        self.setWindowTitle("MUSSA - XA viewer")
        self.data_dir = Path(data_dir)
        self.store_dir = self.data_dir / "store"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.salt = get_or_create_salt(self.data_dir)
        self.item_list = QListWidget()
        self.cine = CineWidget()
        split = QSplitter()
        split.addWidget(self.item_list)
        split.addWidget(self.cine)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        bar = self.addToolBar("Import")
        for text, slot in (("Import file", self._pick_file), ("Import folder", self._pick_folder)):
            act = QAction(text, self)
            act.triggered.connect(slot)
            bar.addAction(act)
        self.item_list.currentItemChanged.connect(self._on_select)
        self._load_store()

    def _add_row(self, text: str, path: Path) -> None:
        row = QListWidgetItem(text)
        row.setData(PATH_ROLE, str(path))
        self.item_list.addItem(row)

    def _load_store(self) -> None:
        for path in sorted(self.store_dir.glob("*.dcm")):
            try:
                h = read_header(path)  # tags only; pixels are decoded when a row is selected
            except ImportRejected:
                continue
            self._add_row(row_text(h.view_label, h.series_description, h.study_date,
                                   h.burned_in_unclear), path)

    def import_from(self, path: Path) -> ImportResult:
        result = import_path(path, self.store_dir, self.salt)
        for it in result.imported:
            self._add_row(row_text(it.view_label, it.series_description, it.study_date,
                                   any("burned-in" in w for w in it.warnings)), it.stored_path)
        return result

    def _on_select(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            return
        self.statusBar().showMessage("Loading series, please wait...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()  # paint the message before the (slow) decode
        try:
            s = read_xa(Path(current.data(PATH_ROLE)))
        except ImportRejected as exc:
            QMessageBox.warning(self, "Cannot open", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()
        self.cine.set_series(s, label_view(s.primary_angle, s.secondary_angle))

    def _report(self, result: ImportResult) -> None:
        QMessageBox.information(self, "Import summary", format_summary(result))

    def _pick_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Import DICOM file")
        if name:
            self._report(self.import_from(Path(name)))

    def _pick_folder(self) -> None:
        name = QFileDialog.getExistingDirectory(self, "Import DICOM folder")
        if name:
            self._report(self.import_from(Path(name)))


def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow(Path.home() / "MUSSA-data")
    win.resize(1000, 700)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
