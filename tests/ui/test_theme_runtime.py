from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QPushButton

from kajovokarty.app.container import ServiceContainer
from kajovokarty.ui.main_window import MainWindow
from kajovokarty.ui.theme import contrast_ratio


def _hex(color: object) -> str:
    return color.name().upper()  # type: ignore[no-any-return,union-attr]


def _assert_visible_button_palette(window: MainWindow, app: QApplication) -> None:
    for row in range(window.navigation.count()):
        window.navigation.setCurrentRow(row)
        app.processEvents()
        for button in window.findChildren(QPushButton):
            if not button.isVisible():
                continue
            palette = button.palette()
            foreground = _hex(palette.color(QPalette.ColorRole.ButtonText))
            background = _hex(palette.color(QPalette.ColorRole.Button))
            assert contrast_ratio(foreground, background) >= 4.5, button.objectName() or button.text()


def test_all_visible_buttons_are_readable_in_both_themes(app_paths, monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    app = QApplication.instance() or QApplication([])
    container = ServiceContainer.build(app_paths)
    try:
        window = MainWindow(container)
        window.show()
        app.processEvents()
        _assert_visible_button_palette(window, app)
        container.settings.save({"ui.high_contrast": True})
        window._apply_ui_settings()
        app.processEvents()
        _assert_visible_button_palette(window, app)
        window.close()
    finally:
        container.close()
