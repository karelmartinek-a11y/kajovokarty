import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from kajovokarty.app.container import ServiceContainer
from kajovokarty.ui.main_window import MainWindow


def test_main_window_opens_without_tokens(app_paths, monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    app = QApplication.instance() or QApplication([])
    container = ServiceContainer.build(app_paths)
    try:
        window = MainWindow(container)
        window.show()
        app.processEvents()
        assert window.isVisible()
        assert window.navigation.count() == 7
        assert window.stack.count() == 7
        window.close()
    finally:
        container.close()
