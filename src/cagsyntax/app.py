from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QInputDialog, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QSplitter, QVBoxLayout,
                               QWidget)

from .dicom_import.deidentify import get_or_create_salt
from .dicom_import.importer import import_path
from .dicom_import.models import ImportRejected, ImportResult
from .dicom_import.reader import read_header, read_xa
from .dicom_import.views import label_view
from .library import DEFAULT_LABEL, Library
from .viewer.widget import CineWidget

PATH_ROLE = 0x100   # Qt.UserRole: stored file path
LABEL_ROLE = 0x101  # folder name of the row
ALL_FOLDERS = "All folders"
BURNED_IN_FLAG = " | check burned-in text"


def row_text(view: str, description: str, study_date: str, burned_in_unclear: bool,
             folder: str = DEFAULT_LABEL) -> str:
    return (f"[{folder}] {view} | {description} | {study_date}"
            f"{BURNED_IN_FLAG if burned_in_unclear else ''}")


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
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.library = Library(self.data_dir)
        self.store_dir = self.library.store_dir
        self.salt = get_or_create_salt(self.data_dir)
        self._shown_uid: str | None = None
        self.folder_combo = QComboBox()
        self.item_list = QListWidget()
        left = QWidget()
        box = QVBoxLayout(left)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.folder_combo)
        box.addWidget(self.item_list, 1)
        self.cine = CineWidget()
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.cine)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        bar = self.addToolBar("Actions")
        for text, slot in (("Import file", self._pick_file), ("Import folder", self._pick_folder),
                           ("Rename folder", self.rename_folder),
                           ("Delete series", self.delete_selected_series),
                           ("Delete folder", self.delete_folder)):
            act = QAction(text, self)
            act.triggered.connect(lambda _checked=False, s=slot: s())
            bar.addAction(act)
        self.item_list.currentItemChanged.connect(self._on_select)
        self.folder_combo.currentTextChanged.connect(lambda _t: self.refresh_list())
        self.refresh_list()

    # ---- list ----
    def refresh_list(self) -> None:
        """Rebuild the folder filter and the series list from the library (tags only, no decoding)."""
        entries = self.library.entries()
        labels = sorted({e.label for e in entries}, key=str.lower)
        wanted = self.folder_combo.currentText()
        selected = self.item_list.currentItem()
        selected_uid = Path(selected.data(PATH_ROLE)).stem if selected else None
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        self.folder_combo.addItems([ALL_FOLDERS] + labels)
        self.folder_combo.setCurrentText(wanted if wanted in labels else ALL_FOLDERS)
        self.folder_combo.blockSignals(False)
        shown = self.folder_combo.currentText()
        self.item_list.blockSignals(True)
        self.item_list.clear()
        for e in entries:
            if shown not in (ALL_FOLDERS, e.label):
                continue
            try:
                h = read_header(e.path)
            except ImportRejected:
                continue
            row = QListWidgetItem(row_text(h.view_label, h.series_description, h.study_date,
                                           h.burned_in_unclear, e.label))
            row.setData(PATH_ROLE, str(e.path))
            row.setData(LABEL_ROLE, e.label)
            self.item_list.addItem(row)
            if e.uid == selected_uid:
                self.item_list.setCurrentItem(row)
        self.item_list.blockSignals(False)

    # ---- import ----
    def import_from(self, path: Path, label: str = DEFAULT_LABEL) -> ImportResult:
        result = import_path(path, self.store_dir, self.salt)
        # Series that were already in the library (duplicates) keep their existing folder name.
        self.library.assign([i.sop_instance_uid for i in result.imported], label)
        self.refresh_list()
        return result

    def _current_folder(self) -> str | None:
        if self.folder_combo.currentText() != ALL_FOLDERS:
            return self.folder_combo.currentText()
        item = self.item_list.currentItem()
        return item.data(LABEL_ROLE) if item is not None else None

    def rename_folder(self, old: str | None = None, new: str | None = None) -> int:
        old = old if old is not None else self._current_folder()
        if old is None:
            return 0
        if new is None:
            new = self._ask_label(old)
        if new is None or not new.strip():
            return 0
        count = self.library.rename_folder(old, new)
        self.refresh_list()
        return count

    # ---- delete (the app's own copies only; source files are never touched) ----
    def _confirm(self, text: str) -> bool:
        answer = QMessageBox.question(self, "Please confirm", text,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _clear_viewer_if_shown(self, uids: set[str]) -> None:
        if self._shown_uid in uids:
            self.cine.clear()
            self._shown_uid = None

    def delete_selected_series(self) -> bool:
        item = self.item_list.currentItem()
        if item is None:
            return False
        uid = Path(item.data(PATH_ROLE)).stem
        if not self._confirm(f"Delete this series from MUSSA?\n\n{item.text()}\n\n"
                             "Only MUSSA's copy is removed. The original files are not touched."):
            return False
        self.library.delete_series(uid)
        self._clear_viewer_if_shown({uid})
        self.refresh_list()
        return True

    def delete_folder(self, label: str | None = None) -> int:
        if label is None:
            label = self._current_folder()
        if label is None:
            return 0
        uids = {e.uid for e in self.library.entries() if e.label == label}
        if not uids:
            return 0
        if not self._confirm(f"Delete the folder '{label}' and its {len(uids)} series from MUSSA?\n\n"
                             "Only MUSSA's copies are removed. The original files are not touched."):
            return 0
        count = self.library.delete_folder(label)
        self._clear_viewer_if_shown(uids)
        self.refresh_list()
        return count

    # ---- viewing ----
    def _on_select(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            return
        self.statusBar().showMessage("Loading series, please wait...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()  # paint the message before the (slow) decode
        path = Path(current.data(PATH_ROLE))
        try:
            s = read_xa(path)
        except ImportRejected as exc:
            QMessageBox.warning(self, "Cannot open", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()
        self._shown_uid = path.stem
        self.cine.set_series(s, label_view(s.primary_angle, s.secondary_angle))

    # ---- import dialogs ----
    def _report(self, result: ImportResult) -> None:
        QMessageBox.information(self, "Import summary", format_summary(result))

    def _ask_label(self, suggestion: str) -> str | None:
        text, ok = QInputDialog.getText(
            self, "Folder name",
            "Name for this folder in MUSSA.\nThe original folder name is only a suggestion; "
            "avoid patient names:", text=suggestion)
        return text if ok else None

    def _pick_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Import DICOM file")
        if name:
            label = self._ask_label(Path(name).parent.name)
            if label is not None:
                self._report(self.import_from(Path(name), label))

    def _pick_folder(self) -> None:
        name = QFileDialog.getExistingDirectory(self, "Import DICOM folder")
        if name:
            label = self._ask_label(Path(name).name)
            if label is not None:
                self._report(self.import_from(Path(name), label))


def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow(Path.home() / "MUSSA-data")
    win.resize(1000, 700)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
