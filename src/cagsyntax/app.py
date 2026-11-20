from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget)

from .cases import study_of
from .dicom_import.deidentify import get_or_create_salt
from .dicom_import.importer import import_path
from .dicom_import.models import ImportRejected, ImportResult
from .dicom_import.reader import read_header, read_xa
from .dicom_import.views import label_view
from .form_state import case_from_json, case_to_json
from .library import DEFAULT_LABEL, Library
from .report import disagreement_report
from .scoring import Case, Lesion
from .store import LEVELS, CaseStore, Confirmation, Entry, StoreError, User
from .ui.scoring_panel import ScoringPanel
from .viewer.widget import CineWidget

PATH_ROLE = 0x100   # Qt.UserRole: stored file path
LABEL_ROLE = 0x101  # folder name of the row
ALL_FOLDERS = "All folders"
BURNED_IN_FLAG = " | check burned-in text"


def kind_text(kind: str, frame_count: int) -> str:
    return f"CINE {frame_count} frames" if kind == "cine" else "STILL"


def score_flag(status: tuple[int, int, bool] | None) -> str:
    """Flag for a series whose study has saved scores: (complete entries, drafts, has reference)."""
    if status is None:
        return ""
    complete, drafts, confirmed = status
    if confirmed:
        return "[scored - reference]"
    if complete:
        return "[scored - not confirmed]"
    if drafts:
        return "[draft only]"
    return ""


def row_text(view: str, description: str, study_date: str, burned_in_unclear: bool,
             folder: str = DEFAULT_LABEL, kind: str = "cine", frame_count: int = 1,
             flag: str = "") -> str:
    return (f"[{folder}] {kind_text(kind, frame_count)} | {view} | {description} | {study_date}"
            f"{BURNED_IN_FLAG if burned_in_unclear else ''}{' | ' + flag if flag else ''}")


def format_summary(result: ImportResult) -> str:
    cines = sum(i.kind == "cine" for i in result.imported)
    stills = len(result.imported) - cines
    lines = [f"Imported: {len(result.imported)} ({cines} cine, {stills} still)",
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
        self._scoring_study: tuple[str, str] | None = None     # (study uid, MRN hash) of the open case
        self._saved_json: str | None = None                    # form as last loaded or saved
        self._form_unreadable = False                          # the stored entry could not be read
        self._open_label = ""
        self._active_user_id: int | None = None
        self.store: CaseStore | None = None
        self.store_error = ""
        try:
            self.store = CaseStore(self.data_dir / "cases.sqlite")
        except StoreError as exc:
            self.store_error = str(exc)                        # viewer still works; scoring is off
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
        self._build_scoring_ui()
        self.item_list.currentItemChanged.connect(self._on_select)
        self.folder_combo.currentTextChanged.connect(lambda _t: self.refresh_list())
        self.refresh_list()
        self._restore_users()
        if self.store_error:
            self.statusBar().showMessage(self.store_error)

    def announce_startup_problems(self) -> None:
        """Show the case-store problem (if any) in a dialog. main() calls this once the window is
        running so the problem is not missed; the status bar alone is easy to overlook."""
        if self.store_error:
            self._warn(self.store_error)

    # ---- scoring UI ----
    def _build_scoring_ui(self) -> None:
        self.addToolBarBreak()                      # scoring tools get their own row
        bar = self.addToolBar("Scoring")
        bar.addWidget(QLabel(" Scorer: "))
        self.user_combo = QComboBox()
        self.user_combo.setMinimumWidth(160)
        self.user_combo.currentIndexChanged.connect(self._on_user_changed)
        bar.addWidget(self.user_combo)
        for text, slot in (("Add scorer", self._ask_add_user), ("Score case", self.score_selected_case),
                           ("Disagreements", self._show_disagreements_dialog)):
            act = QAction(text, self)
            act.triggered.connect(lambda _checked=False, s=slot: s())
            bar.addAction(act)
        self.panel = ScoringPanel()
        self.entries_list = QListWidget()
        self.entries_list.setMaximumHeight(90)
        buttons = QHBoxLayout()
        for text, slot in (("Save score", self.save_entry),
                           ("Confirm selected entry as reference", self.confirm_selected_entry)):
            button = QPushButton(text)
            button.clicked.connect(lambda _c=False, s=slot: s())
            buttons.addWidget(button)
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.addWidget(self.panel, 1)
        layout.addWidget(QLabel("Scores saved for this case:"))
        layout.addWidget(self.entries_list)
        self.reference_label = QLabel("")
        self.reference_label.setWordWrap(True)
        layout.addWidget(self.reference_label)
        layout.addLayout(buttons)
        self.scoring_dock = QDockWidget("Scoring", self)
        self.scoring_dock.setWidget(holder)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.scoring_dock)
        self.scoring_dock.hide()

    def _say(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "MUSSA", text)

    def _failed(self, text: str) -> None:
        """A failure the scorer must not miss: status bar plus a dialog."""
        self._say(text)
        self._warn(text)

    def _dirty(self) -> bool:
        return (self._scoring_study is not None and self._saved_json is not None
                and case_to_json(self.panel.case()) != self._saved_json)

    def _restore_users(self) -> None:
        self._fill_user_combo()
        if self.store is None:
            return
        try:
            last = self.store.get_meta("last_user_id")
        except StoreError:
            return
        if last and last.isdigit():
            index = self.user_combo.findData(int(last))
            if index >= 0:
                self.user_combo.setCurrentIndex(index)

    def _fill_user_combo(self, select_id: int | None = None) -> None:
        self.user_combo.blockSignals(True)
        self.user_combo.clear()
        self.user_combo.addItem("No scorer chosen", None)
        try:
            users = self.store.users() if self.store else []
        except StoreError as exc:
            users = []
            self._say(str(exc))
        for u in users:
            self.user_combo.addItem(f"{u.name} ({u.level})", u.id)
        if select_id is not None:
            self.user_combo.setCurrentIndex(max(0, self.user_combo.findData(select_id)))
        self.user_combo.blockSignals(False)
        self._active_user_id = self.user_combo.currentData()

    def _on_user_changed(self, _index: int) -> None:
        new_id = self.user_combo.currentData()
        if new_id == self._active_user_id:
            return
        if self._dirty() and not self._confirm(
                "You have unsaved changes to this score. Switch scorer and discard them?"):
            self.user_combo.blockSignals(True)
            self.user_combo.setCurrentIndex(max(0, self.user_combo.findData(self._active_user_id)))
            self.user_combo.blockSignals(False)
            return
        self._active_user_id = new_id
        user = self.current_user()
        if self.store is not None and user is not None:
            try:
                self.store.set_meta("last_user_id", str(user.id))
            except StoreError as exc:
                self._say(str(exc))
        if self._scoring_study is not None and not self.scoring_dock.isHidden():
            self._load_scoring_case()

    def current_user(self) -> User | None:
        user_id = self.user_combo.currentData()
        if self.store is None or user_id is None:
            return None
        try:
            return next((u for u in self.store.users() if u.id == user_id), None)
        except StoreError:
            return None

    def add_user(self, name: str, level: str) -> User | None:
        """Add a scorer and switch to them (asking first if there are unsaved edits).
        Returns None, with a message, if the scorer could not be added."""
        if self.store is None:
            self._say(self.store_error or "Scoring is not available.")
            return None
        previous = self._active_user_id
        try:
            user = self.store.add_user(name, level)
        except ValueError as exc:
            self._say(str(exc))
            return None
        except StoreError as exc:
            self._failed(f"Scorer NOT ADDED: {exc}")
            return None
        self._fill_user_combo(select_id=previous)                 # list updated, scorer unchanged
        self.user_combo.setCurrentIndex(self.user_combo.findData(user.id))   # may ask about unsaved edits
        return user

    def _ask_add_user(self) -> None:
        name, ok = QInputDialog.getText(self, "Add scorer", "Name of the scorer:")
        if not ok:
            return
        level, ok = QInputDialog.getItem(self, "Add scorer", "Experience level:", list(LEVELS), 0, False)
        if ok:
            self.add_user(name, level)

    # ---- scoring ----
    def _selected_study(self) -> tuple[str, str] | None:
        """(study uid, MRN hash) of the selected series; raises ImportRejected if it cannot be read."""
        item = self.item_list.currentItem()
        if item is None:
            return None
        uid, mrn_hash = study_of(Path(item.data(PATH_ROLE)))
        return (uid, mrn_hash) if uid else None

    def _case_label(self) -> str:
        item = self.item_list.currentItem()
        path = Path(item.data(PATH_ROLE))
        header = read_header(path)
        return f"{item.data(LABEL_ROLE)}, study {header.study_date}, case ...{header.study_uid[-6:]}"

    def score_selected_case(self) -> bool:
        """Open the scoring form for the study of the selected series."""
        if self.store is None:
            self._say(self.store_error or "Scoring is not available.")
            return False
        if self.current_user() is None:
            self._say("Choose or add a scorer first (Scorer box in the toolbar).")
            return False
        try:
            study = self._selected_study()
            label = self._case_label() if study else ""
        except ImportRejected:
            self._say("This series cannot be read, so its case cannot be opened.")
            return False
        if study is None:
            self._say("Select a series of the case you want to score.")
            return False
        if self._dirty():
            if study == self._scoring_study:
                self.scoring_dock.show()                       # same case: keep the edits
                return True
            if not self._confirm("You have unsaved changes to the open score. Open another case "
                                 "and discard them?"):
                return False
        try:
            self.store.ensure_case(*study)
        except StoreError as exc:
            self._failed(f"The case could not be opened: {exc}")
            return False
        self._scoring_study = study
        self._open_label = label
        self._load_scoring_case()
        self.scoring_dock.show()
        return True

    def _load_scoring_case(self) -> None:
        uid, _hash = self._scoring_study
        user = self.current_user()
        blank = Case(dominance=None, scoring_dominance=None, lesions=[Lesion(segments=[])])
        self._form_unreadable = False
        try:
            mine = next((e for e in self.store.entries(uid) if user and e.user.id == user.id), None)
        except StoreError as exc:
            self._failed(f"The saved scores could not be read: {exc}")
            mine = None
        case = blank
        if mine is not None:
            try:
                case = case_from_json(json.dumps(mine.form))
            except ValueError:
                self._form_unreadable = True
        try:
            self.panel.set_case(case)
        except (ValueError, KeyError, TypeError):
            self._form_unreadable = True
            self.panel.set_case(blank)
        self._saved_json = case_to_json(self.panel.case())
        self.scoring_dock.setWindowTitle(f"Scoring - {user.name if user else ''} - {self._open_label}")
        self.refresh_entries()
        if self._form_unreadable:
            self._say("The saved score could not be read; starting a new one. "
                      "Saving will replace the saved one (you will be asked).")

    def entries_list_rows(self) -> list[str]:
        return [self.entries_list.item(i).text() for i in range(self.entries_list.count())]

    def refresh_entries(self) -> None:
        self.entries_list.clear()
        self.reference_label.setText("")
        if self.store is None or self._scoring_study is None:
            return
        uid = self._scoring_study[0]
        try:
            ref = self.store.confirmation(uid)
            entries = self.store.entries(uid)
        except StoreError as exc:
            self._say(str(exc))
            return
        for e in entries:
            total = f"{e.total:g} ({e.group})" if e.total is not None else "no score"
            mark = ""
            if ref and ref.entry_id == e.id:
                edited = e.total != ref.total or e.form != ref.form
                mark = " - REFERENCE (edited since; the reference is unchanged)" if edited else " - REFERENCE"
            row = QListWidgetItem(f"{e.user.name} ({e.user.level}): {e.status}, {total}, "
                                  f"{e.saved_at[:16].replace('T', ' ')}{mark}")
            row.setData(PATH_ROLE, e.id)
            row.setData(LABEL_ROLE, e.user.id)
            self.entries_list.addItem(row)
        if ref:
            self.reference_label.setText(
                f"Reference score: {ref.total:g} ({ref.group} risk group), confirmed by "
                f"{ref.confirmed_by.name} ({ref.confirmed_by.level}) at {ref.confirmed_at[:16].replace('T', ' ')}.")

    def save_entry(self) -> Entry | None:
        user = self.current_user()
        if self.store is None or self._scoring_study is None or user is None:
            self._say("Open a case and choose a scorer before saving.")
            return None
        if self._form_unreadable and not self._confirm(
                "The score saved earlier for this case could not be read. Saving now will replace "
                "it. Continue?"):
            return None
        result = self.panel.result()
        try:
            entry = self.store.save_entry(self._scoring_study[0], user.id,
                                          dataclasses.asdict(self.panel.case()), result)
        except (StoreError, ValueError) as exc:
            self._failed(f"Score NOT SAVED: {exc}")
            return None
        self._form_unreadable = False
        self._saved_json = case_to_json(self.panel.case())
        self.refresh_list()                                    # the series of this study get their flag
        if result.status == "complete":
            self._say(f"Saved: total {result.total:g} ({result.group} risk group).")
        else:
            self._say(f"Saved as a draft ({result.status}); it cannot be confirmed until it is complete.")
        self.refresh_entries()
        return entry

    def confirm_entry(self, entry_id: int) -> Confirmation | None:
        user = self.current_user()
        if self.store is None or self._scoring_study is None or user is None:
            self._say("Open a case and choose a scorer first.")
            return None
        if user.level != "cardiologist":
            self._say("Only a cardiologist can confirm a reference score.")
            return None
        uid = self._scoring_study[0]
        try:
            existing = self.store.confirmation(uid)
        except StoreError as exc:
            self._failed(f"Reference NOT CONFIRMED: {exc}")
            return None
        if existing is not None and existing.entry_id != entry_id and not self._confirm(
                f"This case already has a reference score ({existing.total:g}, confirmed by "
                f"{existing.confirmed_by.name}). Replace it?"):
            return None
        try:
            confirmation = self.store.confirm(uid, entry_id, user.id)
        except (PermissionError, ValueError) as exc:
            self._say(str(exc))
            return None
        except StoreError as exc:
            self._failed(f"Reference NOT CONFIRMED: {exc}")
            return None
        self._say(f"Confirmed as the reference score: {confirmation.total:g} ({confirmation.group}).")
        self.refresh_entries()
        self.refresh_list()
        return confirmation

    def confirm_selected_entry(self) -> Confirmation | None:
        item = self.entries_list.currentItem()
        if item is None:
            self._say("Select a saved score in the list first.")
            return None
        user = self.current_user()
        if user is not None and item.data(LABEL_ROLE) == user.id and self._dirty():
            self._say("Save your changes before confirming your own score "
                      "(the saved version is what would be confirmed).")
            return None
        return self.confirm_entry(item.data(PATH_ROLE))

    def closeEvent(self, event) -> None:
        if self._dirty() and not self._confirm("You have unsaved changes to a score. Close anyway?"):
            event.ignore()
            return
        if self.store is not None:
            self.store.close()
        event.accept()

    def show_disagreements(self) -> str:
        if self.store is None:
            return self.store_error or "Scoring is not available."
        rows = disagreement_report(self.store)
        if not rows:
            return "No confirmed cases with other scorers' scores to compare yet."
        lines = ["Scores compared with the confirmed reference, by scorer level:"]
        for r in rows:
            lines.append(f"{r.level}: {r.compared} compared; same total {r.same_total}; "
                         f"same risk group {r.same_group}; mean difference {r.mean_abs_diff:.1f}; "
                         f"largest difference {r.max_abs_diff:g}")
        return "\n".join(lines)

    def _show_disagreements_dialog(self) -> None:
        QMessageBox.information(self, "Disagreements", self.show_disagreements())

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
        rows = []
        for e in entries:
            if shown not in (ALL_FOLDERS, e.label):
                continue
            try:
                rows.append((e, read_header(e.path)))
            except ImportRejected:
                continue
        # Cine series are the primary data, so they come before stills within each folder.
        rows.sort(key=lambda r: (r[0].label.lower(), r[1].kind != "cine", r[0].path.name))
        status: dict[str, tuple[int, int, bool]] = {}
        if self.store is not None:
            try:
                status = self.store.scoring_status()
            except StoreError as exc:
                self._say(str(exc))
        self.item_list.blockSignals(True)
        self.item_list.clear()
        for e, h in rows:
            row = QListWidgetItem(row_text(h.view_label, h.series_description, h.study_date,
                                           h.burned_in_unclear, e.label, h.kind, h.frame_count,
                                           score_flag(status.get(h.study_uid))))
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
        self._maybe_follow_selection()

    def _maybe_follow_selection(self) -> None:
        """When the scoring panel is open and the selected series belongs to another study, switch
        the form to it if nothing is unsaved; otherwise say clearly which case is still open."""
        if (self.store is None or self._scoring_study is None or self.scoring_dock.isHidden()
                or self.current_user() is None):
            return
        try:
            study = self._selected_study()
        except ImportRejected:
            return
        if study is None or study == self._scoring_study:
            return
        if self._dirty():
            self._say("Scoring is still open on a different case (see the Scoring panel title). "
                      "Save it, then click Score case to switch.")
        else:
            self.score_selected_case()

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
    QTimer.singleShot(0, win.announce_startup_problems)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
