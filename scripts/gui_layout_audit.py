from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QRect, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from kajovokarty.app.container import ServiceContainer
from kajovokarty.app.paths import AppPaths
from kajovokarty.ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parents[1]




def _relative_luminance(color: QColor) -> float:
    channels = (color.redF(), color.greenF(), color.blueF())
    linear = tuple(
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: QColor, background: QColor) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)

def _interactive(widget: QWidget) -> bool:
    return isinstance(widget, (QAbstractButton, QAbstractItemView, QComboBox, QLineEdit, QSpinBox))


def _inside_visible_ancestor(widget: QWidget, window: MainWindow) -> bool:
    parent = widget.parentWidget()
    while parent is not None and parent is not window:
        if not parent.isVisible():
            return False
        parent = parent.parentWidget()
    return True


def audit_window(window: MainWindow, app: QApplication) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    pages: list[dict[str, Any]] = []
    for row in range(window.navigation.count()):
        window.navigation.setCurrentRow(row)
        app.processEvents()
        page = window.stack.currentWidget()
        page_name = page.objectName() or type(page).__name__
        visible_widgets = [
            widget
            for widget in page.findChildren(QWidget)
            if widget.isVisible() and _inside_visible_ancestor(widget, window)
        ]
        for widget in visible_widgets:
            geometry = widget.geometry()
            if geometry.width() <= 0 or geometry.height() <= 0:
                failures.append({"page": page_name, "widget": widget.objectName() or type(widget).__name__, "reason": "nulová velikost"})
            if _interactive(widget):
                if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
                    failures.append({"page": page_name, "widget": widget.objectName() or type(widget).__name__, "reason": "interaktivní prvek není dosažitelný focusem"})
                if not widget.accessibleName() and not getattr(widget, "text", lambda: "")():
                    warnings.append({"page": page_name, "widget": widget.objectName() or type(widget).__name__, "reason": "chybí accessibleName nebo viditelný text"})
                if isinstance(widget, QAbstractButton):
                    palette = widget.palette()
                    foreground = palette.color(QPalette.ColorRole.ButtonText)
                    background = palette.color(QPalette.ColorRole.Button)
                    ratio = _contrast_ratio(foreground, background)
                    if ratio < 4.5:
                        failures.append({
                            "page": page_name,
                            "widget": widget.objectName() or widget.text() or type(widget).__name__,
                            "reason": f"kontrast tlačítka je pouze {ratio:.2f}:1",
                        })
        pages.append({"name": page_name, "visible_widgets": len(visible_widgets)})

    client = QRect(0, 0, window.width(), window.height())
    for widget in window.findChildren(QWidget):
        if not widget.isVisible() or widget.window() is not window:
            continue
        top_left = widget.mapTo(window, widget.rect().topLeft())
        mapped = QRect(top_left, widget.size())
        if not client.intersects(mapped):
            failures.append({"page": "shell", "widget": widget.objectName() or type(widget).__name__, "reason": "viditelný prvek je mimo klientskou oblast"})

    return {
        "status": "PASS" if not failures else "FAIL",
        "platform": os.name,
        "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR", "1"),
        "window_size": [window.width(), window.height()],
        "pages": pages,
        "failures": failures,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    QCoreApplication.setOrganizationName("Kájovo")
    QCoreApplication.setApplicationName("KajovoKartyAudit")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = args.output or ROOT / "build" / f"gui-audit-{os.environ.get('QT_SCALE_FACTOR', '1').replace('.', '_')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="kajovokarty-gui-audit-") as temporary:
        paths = AppPaths.discover(Path(temporary))
        container = ServiceContainer.build(paths)
        try:
            window = MainWindow(container)
            window.resize(args.width, args.height)
            window.show()
            app.processEvents()
            result = audit_window(window, app)
            screenshot = output.with_suffix(".png")
            window.grab().save(str(screenshot))
            result["screenshot"] = str(screenshot)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            window.close()
        finally:
            container.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
