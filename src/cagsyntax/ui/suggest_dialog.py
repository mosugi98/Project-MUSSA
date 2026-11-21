from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from ..ai.suggest import Suggestion
from .widgets import GlossyButton


def describe(s: Suggestion) -> str:
    size = f"{s.pixels} px"
    if s.segment is None:
        return f"Possible narrowing, not in any outlined segment  -  confidence {round(s.score * 100)}%  -  {size}"
    return f"Possible narrowing in segment {s.segment}  -  confidence {round(s.score * 100)}%  -  {size}"


class SuggestDialog(QDialog):
    """Lists what the AI found on the shown frame. Nothing is ticked: the scorer ticks the ones they agree
    with. Candidates outside every outlined segment are listed for information but cannot be added."""

    def __init__(self, suggestions: list[Suggestion], parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI suggested narrowings")
        self.setMinimumWidth(520)
        self._suggestions = list(suggestions)
        layout = QVBoxLayout(self)
        self.notice_label = QLabel("AI suggestion - not a diagnosis. Tick the narrowings you agree with; nothing is "
                                   "added to the form until you press the button. Dominance and every other answer "
                                   "stay yours to fill in.")
        self.notice_label.setWordWrap(True)
        layout.addWidget(self.notice_label)
        self.list = QListWidget()
        for s in self._suggestions:
            item = QListWidgetItem(describe(s))
            if s.segment is None:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            else:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.itemChanged.connect(lambda _item: self._update_button())
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.add_button = GlossyButton("", variant="primary")
        self.cancel_button = GlossyButton("Cancel")
        self.add_button.clicked.connect(lambda _c=False: self.accept())
        self.cancel_button.clicked.connect(lambda _c=False: self.reject())
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.add_button)
        layout.addLayout(buttons)
        self._update_button()

    def chosen(self) -> list[Suggestion]:
        return [s for s, row in zip(self._suggestions, range(self.list.count()))
                if self.list.item(row).checkState() == Qt.CheckState.Checked
                and self.list.item(row).flags() & Qt.ItemFlag.ItemIsUserCheckable]

    def _update_button(self) -> None:
        self.add_button.setText(f"Add {len(self.chosen())} ticked to the form")
        self.add_button.updateGeometry()
