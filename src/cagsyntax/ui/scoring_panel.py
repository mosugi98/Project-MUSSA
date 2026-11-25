from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from ..form_state import (applicable_questions, case_from_json, case_to_json, change_dominance,
                          clean_lesion, removed_segments)
from ..scoring import Case, CaseResult, Lesion, score_case
from ..scoring.tables import MEDINA, SEGMENT_IDS, weight
from ..scoring.validate import MAX_LESIONS, beyond_candidates
from .artery_map import ArteryMap
from .segment_tree import SegmentTree
from .widgets import GlossyButton

MIN_CONTENT_HEIGHT = 560
BOOL = [("No", False), ("Yes", True)]
DYNAMIC = "dynamic"
QUESTIONS = [
    ("occlusion", "Total occlusion?", BOOL),
    ("first_segment", "First segment of the occlusion", DYNAMIC),
    ("age_over_3_months", "Age of the occlusion over 3 months?", [("No", "no"), ("Yes", "yes"), ("Unknown", "unknown")]),
    ("blunt_stump", "Blunt stump?", BOOL),
    ("bridging", "Bridging collaterals?", BOOL),
    ("beyond_first_visualized", "First segment visualized beyond the occlusion", DYNAMIC),
    ("side_branch", "Side branch at the origin of the occlusion",
     [("No", "no"), ("under 1.5 mm", "small"), ("1.5 mm or more", "large"), ("Both sizes", "both")]),
    ("trifurcation", "Trifurcation: diseased segments involved",
     [("No", 0), ("1", 1), ("2", 2), ("3", 3), ("4", 4)]),
    ("bifurcation", "Bifurcation (Medina)",
     [("No", "none")] + [(f"{k} {m[0]},{m[1]},{m[2]}", k) for k, m in MEDINA.items()]),
    ("bifurcation_angle_lt70", "Bifurcation angle under 70 degrees?", BOOL),
    ("aorto_ostial", "Aorto-ostial lesion?", BOOL),
    ("severe_tortuosity", "Severe tortuosity?", BOOL),
    ("length_gt20", "Length over 20 mm?", BOOL),
    ("heavy_calcification", "Heavy calcification?", BOOL),
    ("thrombus", "Thrombus?", BOOL),
]
FIELDS = {q[0] for q in QUESTIONS}
DISCLAIMER = "Educational tool, not a certified medical device. Decision support for research and teaching."


def _same(a, b) -> bool:
    return a is b or (type(a) is type(b) and a == b)


class _PageScroll(QScrollArea):
    """Scrolls its content when the window is shorter than MIN_CONTENT_HEIGHT, and otherwise fills the window.

    The content is sized here instead of by `setWidgetResizable`, because with word-wrapped labels inside Qt takes the
    layout's preferred height as a minimum, which would stop the panel from ever shrinking to the window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def sizeHint(self):
        inner = self.widget()
        width = inner.sizeHint().width() if inner is not None else 0
        return QSize(width, MIN_CONTENT_HEIGHT)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        inner = self.widget()
        if inner is None:
            return
        room_h = self.height() - 2 * self.frameWidth()
        bar = self.verticalScrollBar().sizeHint().width() if MIN_CONTENT_HEIGHT > room_h else 0
        inner.resize(max(1, self.width() - 2 * self.frameWidth() - bar), max(room_h, MIN_CONTENT_HEIGHT))


class ScoringPanel(QWidget):
    """The SYNTAX form: dominance, lesions, segment picker, questions, live engine result.
    All rules live in form_state and the engine; the widgets only reflect them."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._case = Case(dominance=None, scoring_dominance=None, lesions=[Lesion(segments=[])])
        self._current = 0
        self._notice = ""
        self._syncing = False
        self._rows: dict[str, tuple[QWidget, list[tuple[object, QPushButton]], QGridLayout]] = {}
        self._build()
        self._sync()

    # ------------------------------------------------------------------ public API
    def case(self) -> Case:
        return case_from_json(case_to_json(self._case))

    def set_case(self, case: Case) -> list[str]:
        """Load a case. Segments that do not exist for its dominance (or at all) are dropped and
        reported; every lesion is cleaned. Returns the dropped segments."""
        loaded = case_from_json(case_to_json(case))
        pruned = change_dominance(loaded, loaded.dominance, loaded.scoring_dominance)
        removed = removed_segments(loaded, pruned)
        self._case = pruned
        self._current = 0 if self._case.lesions else -1
        dom = self._dom()
        self._notice = (f"Removed segments that do not exist for {dom or 'this'} dominance: "
                        f"{', '.join(removed)}." if removed else "")
        self._sync()
        return removed

    def result(self) -> CaseResult:
        return score_case(self._case)

    def current_lesion(self) -> int:
        return self._current

    def set_dominance(self, dominance: str | None, scoring_dominance: str | None = None) -> list[str]:
        new = change_dominance(self._case, dominance, scoring_dominance)
        removed = removed_segments(self._case, new)
        self._case = new
        dom = self._dom()
        self._notice = (f"Removed segments that do not exist for {dom} dominance: {', '.join(removed)}."
                        if removed else "")
        self._sync()
        return removed

    def add_lesion(self) -> None:
        if len(self._case.lesions) >= MAX_LESIONS:
            return
        self._case.lesions.append(Lesion(segments=[]))
        self._current = len(self._case.lesions) - 1
        self._sync()

    def remove_lesion(self, index: int) -> None:
        if not 0 <= index < len(self._case.lesions):
            return
        del self._case.lesions[index]
        if index < self._current:
            self._current -= 1
        self._current = min(self._current, len(self._case.lesions) - 1)
        self._sync()

    def select_lesion(self, index: int) -> None:
        if 0 <= index < len(self._case.lesions):
            self._current = index
            self._sync()

    def toggle_segment(self, segment: str) -> None:
        dom = self._dom()
        if self._current < 0 or dom is None or weight(segment, dom) is None:
            return
        les = self._case.lesions[self._current]
        chosen = [s for s in les.segments if s != segment] if segment in les.segments else les.segments + [segment]
        les.segments = [s for s in SEGMENT_IDS if s in chosen]
        self._case.lesions[self._current] = clean_lesion(les, dom)
        self._sync()

    def answer(self, field: str, value) -> bool:
        """Set one answer on the current lesion. Returns False when the question does not apply."""
        if self._current < 0 or field not in FIELDS:
            return False
        dom = self._dom()
        les = self._case.lesions[self._current]
        if field not in applicable_questions(les, dom):
            return False
        setattr(les, field, value)
        cleaned = clean_lesion(les, dom)
        self._case.lesions[self._current] = cleaned
        self._sync()
        return _same(getattr(cleaned, field), value)

    def toggle_diffuse(self, segment: str) -> None:
        dom = self._dom()
        if dom is None or weight(segment, dom) is None:
            return
        chosen = self._case.diffuse_segments
        chosen = [s for s in chosen if s != segment] if segment in chosen else chosen + [segment]
        self._case.diffuse_segments = [s for s in SEGMENT_IDS if s in chosen]
        self._sync()

    def is_enabled(self, field: str) -> bool:
        if self._current < 0:
            return False
        return field in applicable_questions(self._case.lesions[self._current], self._dom())

    def option_button(self, field: str, value) -> QPushButton | None:
        for v, button in self._rows[field][1]:
            if _same(v, value):
                return button
        return None

    # ------------------------------------------------------------------ internals
    def _dom(self) -> str | None:
        c = self._case
        return c.dominance if c.dominance in ("right", "left") else c.scoring_dominance

    def _build(self) -> None:
        # The panel never gets squeezed below MIN_CONTENT_HEIGHT: a short window scrolls the panel instead, so the
        # picker stays large and the question form stays usable.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        page = _PageScroll()
        content = QWidget()
        page.setWidget(content)
        outer.addWidget(page)
        root = QVBoxLayout(content)
        top = QHBoxLayout()
        self.dominance_combo = QComboBox()
        for text, value in [("Choose dominance", None), ("Right dominance", "right"),
                            ("Left dominance", "left"), ("Co-dominant", "co-dominant")]:
            self.dominance_combo.addItem(text, value)
        self.scoring_combo = QComboBox()
        for text, value in [("Choose scoring table", None), ("Score with right table", "right"),
                            ("Score with left table", "left")]:
            self.scoring_combo.addItem(text, value)
        self.dominance_combo.currentIndexChanged.connect(self._on_dominance_combo)
        self.scoring_combo.currentIndexChanged.connect(self._on_dominance_combo)
        top.addWidget(self.dominance_combo)
        top.addWidget(self.scoring_combo)
        top.addStretch(1)

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.lesion_list = QListWidget()
        self.lesion_list.setMaximumHeight(72)
        self.lesion_list.currentRowChanged.connect(self._on_lesion_row)
        buttons = QHBoxLayout()
        add = GlossyButton("Add lesion", variant="primary")
        add.clicked.connect(self.add_lesion)
        remove = GlossyButton("Remove lesion")
        remove.clicked.connect(lambda: self.remove_lesion(self._current))
        buttons.addWidget(add)
        buttons.addWidget(remove)
        self.enlarged_dialog: QDialog | None = None    # the big diagram window, made the first time it is asked for
        self.enlarged_map: ArteryMap | None = None
        self.tree = SegmentTree()
        self.map = ArteryMap()
        for picker in (self.map, self.tree):
            picker.selection_changed.connect(self._on_tree)
        self.picker_stack = QStackedWidget()
        self.picker_stack.addWidget(self.map)          # index 0: Diagram
        self.picker_stack.addWidget(self.tree)         # index 1: Schematic
        self.diagram_button = QPushButton("Diagram")
        self.schematic_button = QPushButton("Schematic")
        switch = QHBoxLayout()
        self._picker_group = QButtonGroup(self)
        self._picker_group.setExclusive(True)
        for button, name in ((self.diagram_button, "diagram"), (self.schematic_button, "schematic")):
            button.setCheckable(True)
            self._picker_group.addButton(button)
            button.clicked.connect(lambda _checked=False, n=name: self.show_picker(n))
            switch.addWidget(button)
        switch.addStretch(1)
        self.enlarge_button = QPushButton("Enlarge")
        self.enlarge_button.setToolTip("Open the diagram in its own window")
        self.enlarge_button.clicked.connect(lambda _checked=False: self.open_enlarged())
        self.enlarge_button.setEnabled(self.map.image_available())
        switch.addWidget(self.enlarge_button)
        self.diagram_button.setEnabled(self.map.image_available())
        self.show_picker("diagram" if self.map.image_available() else "schematic")
        left.addLayout(switch)                         # the picker gets the whole left column
        left.addWidget(self.picker_stack, 1)
        body.addLayout(left, 9)
        right = QVBoxLayout()                          # dominance, lesions, questions and result share the right column
        right.addLayout(top)
        right.addWidget(self.lesion_list)
        right.addLayout(buttons)

        form = QWidget()
        form_layout = QVBoxLayout(form)
        for field, label, options in QUESTIONS:
            row = QGroupBox(label)
            layout = QGridLayout(row)
            self._rows[field] = (row, [], layout)
            if options != DYNAMIC:
                self._fill_row(field, options)
            form_layout.addWidget(row)
        self.diffuse_box = QGroupBox("Diffuse disease / small vessels (more than 75% of the segment is 2 mm or less)")
        self.diffuse_grid = QGridLayout(self.diffuse_box)
        form_layout.addWidget(self.diffuse_box)
        form_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(form)
        right.addWidget(scroll, 1)
        body.addLayout(right, 11)
        root.addLayout(body, 1)

        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setTextFormat(Qt.TextFormat.PlainText)
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll_result = QScrollArea()
        scroll_result.setWidgetResizable(True)
        scroll_result.setMaximumHeight(110)
        scroll_result.setWidget(self.result_label)
        right.addWidget(scroll_result)
        self.disclaimer_label = QLabel(DISCLAIMER)
        self.disclaimer_label.setWordWrap(True)
        right.addWidget(self.disclaimer_label)

    def _fill_row(self, field: str, options) -> None:
        _row, buttons, layout = self._rows[field]
        for value, button in buttons:
            layout.removeWidget(button)
            button.deleteLater()
        buttons.clear()
        columns = 5 if len(options) > 5 else max(1, len(options))   # long option lists wrap
        for i, (text, value) in enumerate(options):
            button = GlossyButton(text)
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, f=field, v=value: self.answer(f, v))
            layout.addWidget(button, i // columns, i % columns)
            buttons.append((value, button))

    def _on_dominance_combo(self, _index: int) -> None:
        if self._syncing:
            return
        dominance = self.dominance_combo.currentData()
        scoring = self.scoring_combo.currentData() if dominance == "co-dominant" else None
        self.set_dominance(dominance, scoring)

    def _on_lesion_row(self, row: int) -> None:
        if not self._syncing and row >= 0:
            self.select_lesion(row)

    def show_picker(self, name: str) -> None:
        """Show the realistic Diagram or the stick-figure Schematic. The Diagram needs its image."""
        if name == "diagram" and self.map.image_available():
            self.picker_stack.setCurrentWidget(self.map)
            self.diagram_button.setChecked(True)
        else:
            self.picker_stack.setCurrentWidget(self.tree)
            self.schematic_button.setChecked(True)

    def open_enlarged(self) -> None:
        """Show the diagram in its own resizable window. It edits the same lesion as the panel and stays in sync."""
        if not self.map.image_available():
            return
        if self.enlarged_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Coronary artery diagram")
            layout = QVBoxLayout(dialog)
            big = ArteryMap()
            big.selection_changed.connect(self._on_tree)
            layout.addWidget(big)
            screen = self.screen()
            height = min(980, int((screen.availableGeometry().height() if screen else 900) * 0.9))
            dialog.resize(round(height * 0.95), height)
            self.enlarged_dialog, self.enlarged_map = dialog, big
        self._sync()
        self.enlarged_dialog.show()
        self.enlarged_dialog.raise_()
        self.enlarged_dialog.activateWindow()

    def current_picker(self) -> str:
        return "diagram" if self.picker_stack.currentWidget() is self.map else "schematic"

    def _on_tree(self, ids: list) -> None:
        if self._syncing or self._current < 0:
            return
        les = self._case.lesions[self._current]
        les.segments = list(ids)
        self._case.lesions[self._current] = clean_lesion(les, self._dom())
        self._sync()

    def _sync(self) -> None:
        self._syncing = True
        try:
            case, dom = self._case, self._dom()
            self.dominance_combo.setCurrentIndex(max(0, self.dominance_combo.findData(case.dominance)))
            self.scoring_combo.setEnabled(case.dominance == "co-dominant")
            self.scoring_combo.setCurrentIndex(max(0, self.scoring_combo.findData(case.scoring_dominance)))
            self.lesion_list.clear()
            for i, les in enumerate(case.lesions):
                self.lesion_list.addItem(f"Lesion {i + 1}: {', '.join(les.segments) or 'no segments yet'}")
            if self._current >= 0:
                self.lesion_list.setCurrentRow(self._current)
            les = case.lesions[self._current] if self._current >= 0 else None
            pickers = [self.tree, self.map] + ([self.enlarged_map] if self.enlarged_map is not None else [])
            for picker in pickers:
                picker.set_scoring_dominance(dom)
                picker.set_selected(les.segments if les else [])
                picker.set_first_segment(les.first_segment if les else None)
                picker.setEnabled(les is not None)
            applicable = applicable_questions(les, dom) if les else set()
            for field, _label, options in QUESTIONS:
                row, _buttons, _layout = self._rows[field]
                if field == "first_segment":
                    self._fill_row(field, [(s, s) for s in (les.segments if les else [])])
                elif field == "beyond_first_visualized":
                    cands = beyond_candidates(les.first_segment, dom) if (
                        les and dom and les.first_segment in les.segments) else []
                    self._fill_row(field, [(c, c) for c in cands] + [("None", "none")])
                value = getattr(les, field) if les else None
                for v, button in self._rows[field][1]:
                    button.setChecked(value is not None and _same(v, value))
                    button.setEnabled(field in applicable)
                row.setEnabled(field in applicable)
            self._fill_diffuse(dom)
            self.result_label.setText(self._result_text())
        finally:
            self._syncing = False
        self.changed.emit()

    def _fill_diffuse(self, dom: str | None) -> None:
        while self.diffuse_grid.count():
            item = self.diffuse_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        segments = [s for s in SEGMENT_IDS if dom and weight(s, dom) is not None]
        for i, seg in enumerate(segments):
            button = GlossyButton(seg)
            button.setCheckable(True)
            button.setChecked(seg in self._case.diffuse_segments)
            button.clicked.connect(lambda _c=False, s=seg: self.toggle_diffuse(s))
            self.diffuse_grid.addWidget(button, i // 9, i % 9)

    def _result_text(self) -> str:
        r = self.result()
        lines: list[str] = []
        if r.status == "complete":
            lines.append(f"Total score {r.total:g} - {r.group} risk group")
            if r.dominance == "co-dominant":
                lines.append(f"Co-dominant: scored with the {r.scoring_dominance} table.")
            for i, lr in enumerate(r.lesions):
                lines.append(f"Lesion {i + 1}: {lr.total:g}")
                lines += [f"    {p.label}: {p.points:g}" for p in lr.parts]
            if r.diffuse_points:
                lines.append(f"Diffuse disease: {r.diffuse_points:g}")
        else:
            lines.append("Incomplete: no score yet." if r.status == "incomplete"
                         else "Invalid combination: no score.")
            for issue in r.issues:
                prefix = f"Lesion {issue.lesion + 1}: " if issue.lesion is not None else ""
                lines.append(f"  - {prefix}{issue.message}")
        if self._notice:
            lines.append(self._notice)
        return "\n".join(lines)
