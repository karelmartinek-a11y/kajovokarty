from __future__ import annotations

import re
import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..application.operations import OperationManager
from .component_registry import ComponentId, bind_component


class OperationProgressDialog(QDialog):
    """Non-blocking progress popup with heartbeat, safe cancellation and minimize."""

    finishedState = Signal(str, str)

    def __init__(
        self,
        operations: OperationManager,
        operation_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.operations = operations
        self.operation_id = operation_id
        self.setWindowTitle("Průběh operace")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(520)
        bind_component(self, ComponentId.GLOBAL_PROGRESS)
        root = QVBoxLayout(self)
        self.title = QLabel("Operace se připravuje…")
        self.title.setWordWrap(True)
        root.addWidget(self.title)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        root.addWidget(self.progress)
        self.message = QLabel("Čekám na první heartbeat…")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        self.record_progress = QLabel("Záznamy: čekám na první zpracovaný záznam…")
        self.record_progress.setWordWrap(True)
        root.addWidget(self.record_progress)
        self.eta = QLabel("Zbývající čas: počítám odhad…")
        self.eta.setWordWrap(True)
        root.addWidget(self.eta)
        self.heartbeat = QLabel("Heartbeat: —")
        self.heartbeat.setWordWrap(True)
        root.addWidget(self.heartbeat)
        self.elapsed = QLabel("Uplynulý čas: 0 s")
        self.elapsed.setWordWrap(True)
        root.addWidget(self.elapsed)
        buttons = QHBoxLayout()
        self.minimize_button = QPushButton("Minimalizovat do Centra operací")
        self.minimize_button.clicked.connect(self.hide)
        self.cancel_button = QPushButton("Bezpečně zrušit")
        self.cancel_button.clicked.connect(self._cancel)
        buttons.addWidget(self.minimize_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)
        self.poll = QTimer(self)
        self.started_monotonic = time.monotonic()
        self.last_progress: float | None = None
        self.last_progress_monotonic: float | None = None
        self.last_phase: str | None = None
        self.poll.setInterval(250)
        self.poll.timeout.connect(self.refresh)
        self.poll.start()
        self.refresh()
        self.activateWindow()

    def refresh(self) -> None:
        snapshot = self.operations.snapshot(self.operation_id)
        record_message = snapshot.message if snapshot is not None else ""
        record_match = re.search(r"(?:Doklady|Rezervace|Záznamy)\s+(\d+)\s*/\s*(\d+)", record_message, re.IGNORECASE)
        phase_match = re.match(r"(Doklady|Rezervace|Záznamy)", record_message, re.IGNORECASE)
        if record_match:
            self.record_progress.setText(f"Záznamy: {record_match.group(1)}/{record_match.group(2)} ({phase_match.group(1) if phase_match else 'zpracování'})")
            if phase_match and phase_match.group(1).casefold() != (self.last_phase or '').casefold():
                self.last_progress = None
                self.last_progress_monotonic = None
                self.last_phase = phase_match.group(1)
                self.started_monotonic = time.monotonic()
        elif snapshot is not None and snapshot.operation_type == "API_SYNC":
            self.record_progress.setText("Záznamy: načítám první stránku Better Hotel API…")
        if snapshot is None:
            self.message.setText("Operace nebyla nalezena.")
            self.cancel_button.setEnabled(False)
            self.poll.stop()
            return
        self.title.setText(f"{snapshot.operation_type} • {snapshot.step}")
        self.message.setText(snapshot.message or "Operace běží.")
        self.heartbeat.setText(f"Heartbeat: {snapshot.heartbeat_utc}")
        elapsed_seconds = max(0.0, time.monotonic() - self.started_monotonic)
        self.elapsed.setText(f"Uplynulý čas: {_format_duration(elapsed_seconds)}")
        if snapshot.total not in (None, 0):
            self.progress.setRange(0, 1000)
            current = float(snapshot.current or 0)
            total = float(snapshot.total)
            self.progress.setValue(int(1000 * min(1.0, max(0.0, current / total))))
            self.progress.setFormat(f"{snapshot.current or 0}/{snapshot.total} • %p %")
            self._update_eta(current, total)
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat("Probíhá - celkový počet zatím není znám")
            self.eta.setText("Zbývající čas: čekám na první měřitelný krok…")
        running = snapshot.state.value in {"QUEUED", "RUNNING", "CANCELLING"}
        self.cancel_button.setEnabled(running and snapshot.state.value != "CANCELLING")
        if not running:
            self.poll.stop()
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if snapshot.state.value == "SUCCEEDED" else 0)
            self.eta.setText(
                "Zbývající čas: dokončeno."
                if snapshot.state.value == "SUCCEEDED"
                else "Zbývající čas: —"
            )
            self.cancel_button.setEnabled(False)
            self.minimize_button.setText("Zavřít")
            try:
                self.minimize_button.clicked.disconnect()
            except RuntimeError:
                pass
            self.minimize_button.clicked.connect(self.accept)
            self.finishedState.emit(snapshot.state.value, snapshot.message)

    def _update_eta(self, current: float, total: float) -> None:
        if current <= 0 or total <= current:
            if total <= current and current > 0:
                self.eta.setText("Zbývající čas: dokončuji…")
            else:
                self.eta.setText("Zbývající čas: počítám odhad…")
            return
        now = time.monotonic()
        if self.last_progress is None:
            self.last_progress = current
            self.last_progress_monotonic = now
        elif current > self.last_progress:
            self.last_progress = current
            self.last_progress_monotonic = now
        elapsed = max(0.0, now - self.started_monotonic)
        seconds_left = elapsed * (total - current) / current
        self.eta.setText(f"Zbývající čas: přibližně {_format_duration(seconds_left)} (odhad se zpřesňuje)")

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.message.setText("Požadavek na bezpečné zrušení byl předán. Čekám na ukončení atomické dávky…")
        self.operations.cancel(self.operation_id)

    def closeEvent(self, event: object) -> None:
        snapshot = self.operations.snapshot(self.operation_id)
        if snapshot is not None and snapshot.state.value in {"QUEUED", "RUNNING", "CANCELLING"}:
            self.hide()
            if hasattr(event, "ignore"):
                event.ignore()
            return
        if hasattr(event, "accept"):
            event.accept()


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {remainder:02d} s"
    return f"{remainder} s"
