import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def close_leftover_windows():
    """Tests open many MainWindows and never close them. Changing the theme re-styles every live widget,
    so leftovers make later tests slower and slower. Delete them after each test."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.hide()                 # not close(): closing a window with unsaved scores opens a prompt
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
