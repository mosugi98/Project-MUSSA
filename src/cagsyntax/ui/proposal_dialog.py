from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from ..agent.reconcile import Reconciliation
from ..agent.schema import LesionInput
from .widgets import GlossyButton

ID_ROLE = Qt.ItemDataRole.UserRole


def describe(lesion: LesionInput, reasons: list[str], view_labels: dict[str, str]) -> str:
    """One line per proposed lesion: segment, model score, the views it was seen in, the best frame and why to look."""
    evidence = lesion.primary_evidence
    segment = lesion.involved_segments[0].segment_id
    views = sorted({view_labels.get(e.series_instance_uid, e.series_instance_uid)
                    for e in ([evidence] if evidence else []) + lesion.supporting_views})
    text = f"Possible narrowing in segment {segment}"
    if evidence is not None:
        text += f"  -  model score {round(evidence.confidence_score * 100)}%"
    if views:
        text += f"  -  seen in {', '.join(views)}"
    if evidence is not None:
        text += f"  -  best view: frame {evidence.frame_index + 1}"
    if reasons:
        text += f"  -  check: {'; '.join(reasons)}"
    return text


class ProposalDialog(QDialog):
    """Lists what the AI proposes for a whole study. Nothing is ticked: the scorer ticks the lesions they agree with
    and can jump the viewer to the exact series and frame behind each one first (`on_show` gets the lesion id)."""

    def __init__(self, reconciliation: Reconciliation, on_show: Callable[[str], None], notes: list[str] | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI proposed lesions")
        self.setMinimumWidth(620)
        self._on_show = on_show
        reasons = {m.lesion_id: m.attention_reasons for m in reconciliation.merges}
        layout = QVBoxLayout(self)
        self.notice_label = QLabel("AI proposal - not a diagnosis. Tick the narrowings you agree with; nothing is "
                                   "added to the form until you press the button. Select a row and press Show in "
                                   "viewer to see the frame it comes from. Dominance and every other answer stay "
                                   "yours to fill in.")
        self.notice_label.setWordWrap(True)
        layout.addWidget(self.notice_label)
        self.list = QListWidget()
        self._ids: list[str] = []
        for lesion in reconciliation.study.lesions:
            item = QListWidgetItem(describe(lesion, reasons.get(lesion.lesion_id, []), reconciliation.view_labels))
            item.setData(ID_ROLE, lesion.lesion_id)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)
            self._ids.append(lesion.lesion_id)
        self.list.itemChanged.connect(lambda _item: self._update_buttons())
        self.list.currentRowChanged.connect(lambda _row: self._update_buttons())
        layout.addWidget(self.list)
        self.info_label = QLabel("\n".join(list(reconciliation.warnings) + list(notes or [])))
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        buttons = QHBoxLayout()
        self.show_button = GlossyButton("Show in viewer")
        self.cancel_button = GlossyButton("Cancel")
        self.add_button = GlossyButton("", variant="primary")
        self.show_button.clicked.connect(lambda _c=False: self._show_selected())
        self.add_button.clicked.connect(lambda _c=False: self.accept())
        self.cancel_button.clicked.connect(lambda _c=False: self.reject())
        buttons.addWidget(self.show_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.add_button)
        layout.addLayout(buttons)
        self._update_buttons()

    def chosen(self) -> list[str]:
        """Ids of the ticked lessons, in the order they were proposed."""
        return [self._ids[row] for row in range(self.list.count())
                if self.list.item(row).checkState() == Qt.CheckState.Checked]

    def _show_selected(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self._ids):
            self._on_show(self._ids[row])

    def _update_buttons(self) -> None:
        self.add_button.setText(f"Add {len(self.chosen())} ticked to the form")
        self.add_button.updateGeometry()
        self.show_button.setEnabled(self.list.currentRow() >= 0)
