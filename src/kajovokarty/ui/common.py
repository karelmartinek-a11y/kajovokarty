from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyState(QFrame):
    primaryClicked = Signal()
    secondaryClicked = Signal()

    def __init__(self, title: str, message: str, primary: str | None = None, secondary: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("emptyState", True)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = QLabel(title)
        font = heading.font()
        font.setPointSizeF(font.pointSizeF() + 2)
        font.setBold(True)
        heading.setFont(font)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(message)
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        layout.addWidget(text)
        buttons = QHBoxLayout()
        if primary:
            button = QPushButton(primary)
            button.clicked.connect(self.primaryClicked)
            buttons.addWidget(button)
        if secondary:
            button = QPushButton(secondary)
            button.clicked.connect(self.secondaryClicked)
            buttons.addWidget(button)
        layout.addLayout(buttons)


class KpiCard(QFrame):
    clicked = Signal(str)

    def __init__(self, key: str, label: str, value: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("interactiveCard", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        self.label = QLabel(label)
        self.value = QLabel(value)
        font = self.value.font()
        font.setPointSizeF(font.pointSizeF() + 6)
        font.setBold(True)
        self.value.setFont(font)
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        self.setAccessibleName(label)
        self.setAccessibleDescription("Aktivuje filtrovaný pohled párování.")

    def set_value(self, value: str) -> None:
        self.value.setText(value)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: Any) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.clicked.emit(self.key)
            event.accept()
            return
        super().keyPressEvent(event)
