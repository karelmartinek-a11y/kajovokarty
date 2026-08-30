from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...app.container import ServiceContainer
from ...application.reporting import REPORTS
from ...domain.money import Money
from ..action_registry import ObjectActionRegistry, ObjectContext
from ..component_registry import ComponentId, bind_component


class ReportsScreen(QWidget):
    """Interactive live reports with non-blocking exports and object actions."""

    contextsChanged = Signal(object)
    operationStarted = Signal(str)

    def __init__(self, container: ServiceContainer, registry: ObjectActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self.registry = registry
        self.active_operation: str | None = None
        self.poll = QTimer(self)
        self.poll.setInterval(250)
        self.poll.timeout.connect(self._poll_export)

        root = QVBoxLayout(self)
        title = QLabel("Sestavy")
        title.setObjectName("screenTitle")
        root.addWidget(title)

        controls = QHBoxLayout()
        self.report = QComboBox()
        bind_component(self.report, ComponentId.REPORT_SELECTOR)
        for key, definition in REPORTS.items():
            self.report.addItem(definition.label, key)
        self.report.currentIndexChanged.connect(self.refresh)
        refresh = QPushButton("Obnovit")
        refresh.clicked.connect(self.refresh)
        export_csv = QPushButton("Export CSV")
        bind_component(export_csv, ComponentId.REPORT_EXPORT)
        export_csv.clicked.connect(lambda: self._choose_export("csv"))
        export_xlsx = QPushButton("Export XLSX")
        export_xlsx.clicked.connect(lambda: self._choose_export("xlsx"))
        export_pdf = QPushButton("Export PDF")
        export_pdf.clicked.connect(lambda: self._choose_export("pdf"))
        controls.addWidget(self.report, 1)
        controls.addWidget(refresh)
        controls.addWidget(export_csv)
        controls.addWidget(export_xlsx)
        controls.addWidget(export_pdf)
        root.addLayout(controls)

        saved_row = QHBoxLayout()
        self.saved = QComboBox()
        bind_component(self.saved, ComponentId.REPORT_FILTERS)
        self.saved.setAccessibleName("Uložené filtry sestav")
        self.saved.currentIndexChanged.connect(self._apply_saved_filter)
        save_filter = QPushButton("Uložit filtr")
        save_filter.clicked.connect(self._save_filter)
        remove_filter = QPushButton("Odstranit uložený filtr")
        remove_filter.clicked.connect(self._remove_filter)
        saved_row.addWidget(QLabel("Uložený filtr:"))
        saved_row.addWidget(self.saved, 1)
        saved_row.addWidget(save_filter)
        saved_row.addWidget(remove_filter)
        root.addLayout(saved_row)

        self.summary = QLabel("Živá sestava používá aktuální databázi a stejné objektové akce jako ostatní pohledy.")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.table = QTableWidget()
        bind_component(self.table, ComponentId.REPORT_TABLE)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.setAccessibleName("Živá tabulka sestavy")
        root.addWidget(self.table, 1)

        self._reload_saved_filters()
        self.refresh()

    def _reload_saved_filters(self, select_id: str | None = None) -> None:
        self.saved.blockSignals(True)
        self.saved.clear()
        self.saved.addItem("— vyberte —", None)
        for saved_filter in self.container.saved_filters.list("reports"):
            self.saved.addItem(saved_filter.name, saved_filter)
            if saved_filter.id == select_id:
                self.saved.setCurrentIndex(self.saved.count() - 1)
        self.saved.blockSignals(False)

    def _apply_saved_filter(self) -> None:
        saved_filter = self.saved.currentData()
        if saved_filter is None:
            return
        key = str(saved_filter.values.get("report_key", ""))
        index = self.report.findData(key)
        if index >= 0:
            self.report.setCurrentIndex(index)
        self.refresh()

    def _save_filter(self) -> None:
        name, accepted = QInputDialog.getText(self, "Uložit filtr sestavy", "Lidský název filtru:")
        if not accepted:
            return
        saved_filter = self.container.saved_filters.save(
            "reports",
            name,
            {"report_key": str(self.report.currentData())},
        )
        self._reload_saved_filters(saved_filter.id)

    def _remove_filter(self) -> None:
        saved_filter = self.saved.currentData()
        if saved_filter is None:
            QMessageBox.information(self, "Vyberte filtr", "Vyberte uložený filtr, který chcete odstranit.")
            return
        self.container.saved_filters.remove(saved_filter.id)
        self._reload_saved_filters()

    def refresh(self) -> None:
        report_key = str(self.report.currentData())
        headers, rows = self.container.reporting.rows(report_key, limit=5000)
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(headers) + 1)
        self.table.setHorizontalHeaderLabels([*headers, "Akce"])
        self.table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            context = self._context_for(report_key, headers, values)
            for column, value in enumerate(values):
                display_value = value
                header = headers[column] if column < len(headers) else ""
                if "Částka" in header and value is not None:
                    currency_header = "Měna částky úhrady" if "úhrady" in header else "Měna"
                    currency_index = headers.index(currency_header) if currency_header in headers else -1
                    if currency_index >= 0:
                        display_value = Money(int(value), str(values[currency_index])).format()
                item = QTableWidgetItem("" if display_value is None else str(display_value))
                item.setToolTip("" if display_value is None else str(display_value))
                if context is not None:
                    item.setData(Qt.ItemDataRole.UserRole, context)
                self.table.setItem(row_index, column, item)
            if context is not None:
                action_button = QPushButton("Další akce")
                action_button.setAccessibleName(
                    f"Další akce: {context.primary_label}"
                )
                action_button.setToolTip(
                    "Stejné objektové akce jako pravé tlačítko nebo Shift+F10."
                )
                action_button.clicked.connect(
                    lambda _checked=False, ctx=context, button=action_button: self._menu_for_context(
                        button, ctx
                    )
                )
                self.table.setCellWidget(row_index, len(headers), action_button)
            else:
                self.table.setItem(row_index, len(headers), QTableWidgetItem("—"))
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self.summary.setText(f"{REPORTS[report_key].label}: {len(rows)} řádků. Export respektuje zvolenou sestavu a uvádí měnu v každém finančním řádku.")

    def focus_report(self, key: str) -> None:
        index = self.report.findData(key)
        if index >= 0:
            self.report.setCurrentIndex(index)
        self.refresh()

    def _selection_changed(self) -> None:
        self.contextsChanged.emit(self.selected_contexts())

    def selected_contexts(self) -> list[ObjectContext]:
        contexts: list[ObjectContext] = []
        seen: set[str] = set()
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            context = None if item is None else item.data(Qt.ItemDataRole.UserRole)
            if isinstance(context, ObjectContext) and context.object_ref not in seen:
                contexts.append(context)
                seen.add(context.object_ref)
        return contexts

    def _context_menu(self, point: Any) -> None:
        contexts = self.selected_contexts()
        menu = self.registry.build_menu(self.table, contexts)
        menu.exec(self.table.viewport().mapToGlobal(point))

    def _menu_for_context(self, button: QPushButton, context: ObjectContext) -> None:
        self.registry.build_menu(self.table, [context]).exec(
            button.mapToGlobal(button.rect().bottomLeft())
        )

    def _choose_export(self, suffix: str) -> None:
        key = str(self.report.currentData())
        configured = str(self.container.settings.get("data.export_directory") or "").strip()
        export_root = Path(configured).expanduser() if configured else self.container.paths.exports
        default = export_root / f"{key}.{suffix}"
        path, _ = QFileDialog.getSaveFileName(self, "Exportovat sestavu", str(default), f"{suffix.upper()} (*.{suffix})")
        if not path:
            return
        destination = Path(path)

        def task(context: Any) -> None:
            context.progress(5, 100, "Připravuji data sestavy", "Export")
            if context.is_cancelled():
                return
            exporter = {
                "csv": self.container.reporting.export_csv,
                "xlsx": self.container.reporting.export_xlsx,
                "pdf": self.container.reporting.export_pdf,
            }[suffix]
            exporter(key, destination)
            context.progress(100, 100, f"Export uložen: {destination}", "Dokončeno")

        self.active_operation = self.container.operations.submit(f"EXPORT_{suffix.upper()}", task)
        self.operationStarted.emit(self.active_operation)
        self.poll.start()
        self.summary.setText("Probíhá export. Aplikaci můžete dál používat.")

    def _poll_export(self) -> None:
        if self.active_operation is None:
            self.poll.stop()
            return
        snapshot = self.container.operations.snapshot(self.active_operation)
        if snapshot is None:
            return
        self.summary.setText(f"{snapshot.step}: {snapshot.message}")
        if snapshot.state.value in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            self.poll.stop()
            self.active_operation = None
            if snapshot.state.value == "FAILED":
                QMessageBox.warning(self, "Export se nezdařil", snapshot.message)
            elif snapshot.state.value == "SUCCEEDED":
                QMessageBox.information(self, "Export dokončen", snapshot.message)

    @staticmethod
    def _context_for(report_key: str, headers: list[str], values: list[Any]) -> ObjectContext | None:
        row = dict(zip(headers, values, strict=True))
        if report_key == "card_paid_invoices":
            return None
        if report_key == "matching_overview" or report_key in {"partial", "manual"}:
            identifier = str(row.get("Skupina", ""))
            return ObjectContext("MATCH_GROUP", identifier, f"Skupina {identifier[:8]}", str(row.get("Měna", "")) or None, _as_int(row.get("Rozdíl")), None, str(row.get("Stav", "")) or None, "reports")
        if report_key in {"unmatched_invoices"}:
            identifier = str(row.get("ID", ""))
            return ObjectContext("INVOICE", identifier, str(row.get("Doklad", identifier)), str(row.get("Měna", "")) or None, _as_int(row.get("Částka")), None, str(row.get("Stav", "")) or None, "reports", {"included": True})
        if report_key in {"unmatched_booking", "booking_payments"}:
            identifier = str(row.get("ID", ""))
            label = str(row.get("Booking.com", row.get("Číslo rezervace zdroje", identifier)))
            return ObjectContext("BOOKING", identifier, label, str(row.get("Měna", "")) or None, _as_int(row.get("Částka")), None, str(row.get("Stav", "")) or None, "reports")
        if report_key in {"unmatched_cards", "terminal_payments"}:
            identifier = str(row.get("ID", ""))
            label = str(row.get("SEQ ID", identifier))
            return ObjectContext("CARD", identifier, label, str(row.get("Měna", "")) or None, _as_int(row.get("Částka")), None, str(row.get("Stav", "")) or None, "reports")
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
