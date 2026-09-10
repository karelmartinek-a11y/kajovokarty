from __future__ import annotations

from datetime import date
from pathlib import Path
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QMimeData, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...app.container import ServiceContainer
from ...application.import_preflight import ImportFilePreview
from ...infrastructure.better_hotel.client import BetterHotelClient, Tokens
from ...infrastructure.importers.bank_file import MultipleMatchingSheets
from ..action_registry import ObjectActionRegistry, ObjectContext
from ..component_registry import ComponentId, bind_component
from ..quarantine_dialog import QuarantineDialog


class FileDropBox(QFrame):
    filesSelected = Signal(object)

    def __init__(
        self,
        title: str,
        extensions: tuple[str, ...],
        parent: QWidget | None = None,
        *,
        initial_directory: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.extensions = extensions
        self.initial_directory = initial_directory
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("dropZone", True)
        self.setMinimumHeight(110)
        layout = QVBoxLayout(self)
        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        button = QPushButton("Vybrat soubor")
        button.clicked.connect(self._choose)
        layout.addWidget(button)
        self.setAccessibleName(title)
        self.setAccessibleDescription("Soubor lze vybrat tlačítkem nebo přetáhnout z Průzkumníku Windows.")

    def dragEnterEvent(self, event: Any) -> None:
        paths = _paths_from_mime(event.mimeData())
        if paths and all(path.suffix.casefold() in self.extensions for path in paths):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: Any) -> None:
        paths = _paths_from_mime(event.mimeData())
        valid = [path for path in paths if path.suffix.casefold() in self.extensions]
        if valid:
            self.filesSelected.emit(valid)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _choose(self) -> None:
        pattern = " ".join(f"*{extension}" for extension in self.extensions)
        initial = "" if self.initial_directory is None else self.initial_directory()
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Vyberte soubor",
            initial,
            f"Podporované soubory ({pattern})",
        )
        if files:
            self.filesSelected.emit([Path(file) for file in files])


class ImportsScreen(QWidget):
    dataChanged = Signal()
    openSettings = Signal()
    contextsChanged = Signal(object)
    operationStarted = Signal(str)

    def __init__(self, container: ServiceContainer, registry: ObjectActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self.registry = registry
        self.booking_queue: list[Path] = []
        self.bank_queue: list[tuple[Path, str | None]] = []
        self.cashbook_queue: list[Path] = []
        self.queue_previews: dict[tuple[str, str, str | None], ImportFilePreview] = {}
        self.active_operation: str | None = None
        self.quarantine_dialog: QuarantineDialog | None = None
        self.poll = QTimer(self)
        self.poll.setInterval(250)
        self.poll.timeout.connect(self._poll_operation)
        root = QVBoxLayout(self)
        title = QLabel("Importy a synchronizace")
        title.setObjectName("screenTitle")
        root.addWidget(title)
        cards = QGridLayout()
        api = QGroupBox("Better Hotel")
        bind_component(api, ComponentId.IMPORT_API_CARD)
        api_layout = QVBoxLayout(api)
        api_layout.addWidget(QLabel("Read-only synchronizace faktur, rezervací, účtů a vazeb. Endpoint je pevně nastavený."))
        api_button = QPushButton("Stáhnout z Better Hotelu")
        api_button.clicked.connect(self.run_api)
        api_layout.addWidget(api_button)
        test_button = QPushButton("Test připojení")
        test_button.clicked.connect(self.test_connection)
        api_layout.addWidget(test_button)
        cards.addWidget(api, 0, 0)
        booking = QGroupBox("Booking.com CSV")
        booking_layout = QVBoxLayout(booking)
        self.booking_drop = FileDropBox(
            "Přetáhněte Booking.com CSV nebo zvolte soubor",
            (".csv",),
            initial_directory=lambda: str(
                self.container.settings.get("imports.booking_directory") or ""
            ),
        )
        bind_component(self.booking_drop, ComponentId.IMPORT_BOOKING_DROP)
        self.booking_drop.filesSelected.connect(self.queue_booking)
        booking_layout.addWidget(self.booking_drop)
        cards.addWidget(booking, 0, 1)
        bank = QGroupBox("Bankovní / terminálový soubor")
        bank_layout = QVBoxLayout(bank)
        self.bank_drop = FileDropBox(
            "Přetáhněte CSV, XLS nebo XLSX",
            (".csv", ".xls", ".xlsx"),
            initial_directory=lambda: str(
                self.container.settings.get("imports.bank_directory") or ""
            ),
        )
        bind_component(self.bank_drop, ComponentId.IMPORT_BANK_DROP)
        self.bank_drop.filesSelected.connect(self.queue_bank)
        bank_layout.addWidget(self.bank_drop)
        cashbook_button = QPushButton("Vybrat pokladní deník Better Hotel (XLS/XLSX/CSV)")
        cashbook_button.clicked.connect(self.choose_cashbook)
        bank_layout.addWidget(cashbook_button)
        cards.addWidget(bank, 0, 2)
        root.addLayout(cards)
        queue_box = QGroupBox("Fronta souborů")
        queue_layout = QVBoxLayout(queue_box)
        self.queue = QListWidget()
        bind_component(self.queue, ComponentId.IMPORT_QUEUE)
        queue_layout.addWidget(self.queue)
        queue_buttons = QHBoxLayout()
        import_booking = QPushButton("Importovat Booking.com")
        import_booking.clicked.connect(self.run_booking)
        import_bank = QPushButton("Importovat banku")
        import_bank.clicked.connect(self.run_bank)
        import_cashbook = QPushButton("Importovat pokladní deník")
        import_cashbook.clicked.connect(self.run_cashbook)
        remove = QPushButton("Odebrat vybrané")
        remove.clicked.connect(self.remove_selected)
        queue_buttons.addWidget(import_booking)
        queue_buttons.addWidget(import_bank)
        queue_buttons.addWidget(import_cashbook)
        queue_buttons.addWidget(remove)
        queue_buttons.addStretch(1)
        queue_layout.addLayout(queue_buttons)
        root.addWidget(queue_box)
        run_row = QHBoxLayout()
        self.run_all = QPushButton("Aktualizovat a spárovat")
        self.run_all.setObjectName("TOP_RUN_ALL")
        self.run_all.clicked.connect(self.run_full)
        self.cancel = QPushButton("Zrušit")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancel_operation)
        run_row.addWidget(self.run_all)
        run_row.addWidget(self.cancel)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        run_row.addWidget(self.progress, 1)
        self.progress_label = QLabel("Připraveno")
        run_row.addWidget(self.progress_label)
        root.addLayout(run_row)
        self.runs = QTableWidget(0, 6)
        bind_component(self.runs, ComponentId.IMPORT_RUNS)
        self.runs.setHorizontalHeaderLabels(["Zdroj", "Běh", "Stav", "Začátek", "Konec", "Počty / chyba"])
        self.runs.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.runs.itemSelectionChanged.connect(self._run_selected)
        root.addWidget(self.runs, 1)
        self.run_detail = QPlainTextEdit()
        bind_component(self.run_detail, ComponentId.IMPORT_RUN_DETAIL)
        self.run_detail.setReadOnly(True)
        self.run_detail.setMaximumHeight(170)
        self.run_detail.setPlaceholderText("Vyberte běh. Zde se zobrazí počty, součty, chyby a correlation ID.")
        root.addWidget(self.run_detail)
        quarantine_buttons = QHBoxLayout()
        open_quarantine = QPushButton("Otevřít karanténu")
        open_quarantine.clicked.connect(self.show_quarantine)
        retry = QPushButton("Zopakovat vybraný běh")
        retry.clicked.connect(self.retry_selected)
        quarantine_buttons.addWidget(open_quarantine)
        quarantine_buttons.addWidget(retry)
        quarantine_buttons.addStretch(1)
        root.addLayout(quarantine_buttons)
        self.refresh_runs()

    def queue_booking(self, paths: list[Path]) -> None:
        max_megabytes = int(self.container.settings.all()["imports.max_megabytes"])
        for path in paths:
            try:
                preview = self.container.import_preflight.booking_preview(path, max_megabytes=max_megabytes)
            except Exception as exc:
                QMessageBox.warning(self, "Soubor nelze zařadit", str(exc))
                continue
            normalized = preview.path
            if normalized not in self.booking_queue:
                self.booking_queue.append(normalized)
                key = ("BOOKING", str(normalized), None)
                self.queue_previews[key] = preview
                item = QListWidgetItem(preview.human_summary)
                item.setToolTip(preview.human_summary)
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.queue.addItem(item)

    def queue_bank(self, paths: list[Path]) -> None:
        max_megabytes = int(self.container.settings.all()["imports.max_megabytes"])
        for path in paths:
            sheet_name: str | None = None
            try:
                preview = self.container.import_preflight.bank_preview(path, max_megabytes=max_megabytes)
            except MultipleMatchingSheets as exc:
                selected, ok = QInputDialog.getItem(self, "Vyberte bankovní list", "Více viditelných listů odpovídá schématu:", exc.names, 0, False)
                if not ok:
                    continue
                sheet_name = selected
                try:
                    preview = self.container.import_preflight.bank_preview(
                        path,
                        max_megabytes=max_megabytes,
                        sheet_name=sheet_name,
                    )
                except Exception as inner_exc:
                    QMessageBox.warning(self, "Soubor nelze zařadit", str(inner_exc))
                    continue
            except Exception as exc:
                QMessageBox.warning(self, "Soubor nelze zařadit", str(exc))
                continue
            sheet_name = preview.selected_sheet
            key = (preview.path, sheet_name)
            if key not in self.bank_queue:
                self.bank_queue.append(key)
                item_key = ("BANK", str(preview.path), sheet_name)
                self.queue_previews[item_key] = preview
                item = QListWidgetItem(preview.human_summary)
                item.setToolTip(preview.human_summary)
                item.setData(Qt.ItemDataRole.UserRole, item_key)
                self.queue.addItem(item)

    def remove_selected(self) -> None:
        for item in self.queue.selectedItems():
            kind, path, sheet = item.data(Qt.ItemDataRole.UserRole)
            if kind == "BOOKING":
                self.booking_queue = [value for value in self.booking_queue if str(value) != path]
            elif kind == "CASHBOOK":
                self.cashbook_queue = [value for value in self.cashbook_queue if str(value) != path]
            else:
                self.bank_queue = [value for value in self.bank_queue if not (str(value[0]) == path and value[1] == sheet)]
            self.queue_previews.pop((kind, path, sheet), None)
            self.queue.takeItem(self.queue.row(item))

    def test_connection(self) -> None:
        tokens = self.container.secrets.load_tokens()
        if not tokens.complete:
            QMessageBox.information(self, "Tokeny nejsou nastavené", "Aplikace funguje i bez tokenů. Pro spojení je zadejte v Nastavení.")
            self.openSettings.emit()
            return
        settings = self.container.settings.all()
        try:
            with BetterHotelClient(Tokens(tokens.access_token, tokens.client_token), timeout_seconds=settings["sync.timeout_seconds"], retries=settings["sync.retry_count"], requests_per_second=settings["sync.requests_per_second"]) as client:
                client.get("/currency")
            QMessageBox.information(self, "Připojení", "Připojení k Better Hotelu je v pořádku.")
        except Exception as exc:
            QMessageBox.warning(self, "Připojení se nezdařilo", str(exc))

    def run_api(self) -> None:
        self._start_operation("API_SYNC", self._api_task, exclusive=True)

    def run_booking(self) -> None:
        if not self.booking_queue:
            QMessageBox.information(self, "Fronta je prázdná", "Nejprve přidejte Booking.com CSV.")
            return
        self._start_operation("BOOKING_IMPORT", self._booking_task, exclusive=True)

    def run_bank(self) -> None:
        if not self.bank_queue:
            QMessageBox.information(self, "Fronta je prázdná", "Nejprve přidejte bankovní soubor.")
            return
        self._start_operation("BANK_IMPORT", self._bank_task, exclusive=True)

    def choose_cashbook(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Vyberte pokladní deník Better Hotel", "", "Pokladní deník (*.xls *.xlsx *.csv)")
        self.cashbook_queue.extend(Path(value) for value in files if Path(value) not in self.cashbook_queue)
        self._rebuild_queue_widget()

    def run_cashbook(self) -> None:
        if not self.cashbook_queue:
            QMessageBox.information(self, "Fronta je prázdná", "Nejprve přidejte pokladní deník Better Hotel.")
            return
        self._start_operation("CASHBOOK_IMPORT", self._cashbook_task, exclusive=True)

    def run_full(self) -> None:
        self._start_operation("FULL_WORKFLOW", self._full_task, exclusive=True)

    def _start_operation(self, operation_type: str, task: Any, *, exclusive: bool) -> None:
        if self.active_operation:
            QMessageBox.information(self, "Operace už probíhá", "Počkejte na dokončení aktuální operace nebo ji bezpečně zrušte.")
            return
        self.active_operation = self.container.operations.submit(
            operation_type,
            task,
            exclusive_sources=exclusive,
            recovery=self._recovery_payload(operation_type),
        )
        self.operationStarted.emit(self.active_operation)
        self.cancel.setEnabled(True)
        self.run_all.setEnabled(False)
        self.poll.start()

    def recover_interrupted(self, operation_type: str, recovery: dict[str, Any]) -> bool:
        """Restore the exact source queue and resume from persisted safe checkpoints."""
        booking_paths = [Path(str(value)) for value in recovery.get("booking_paths", [])]
        bank_items = recovery.get("bank_items", [])
        missing = [path for path in booking_paths if not path.is_file()]
        for item in bank_items:
            path = Path(str(item.get("path", "")))
            if not path.is_file():
                missing.append(path)
        if missing:
            QMessageBox.warning(
                self,
                "Běh nelze obnovit",
                "Původní soubory už nejsou dostupné:\n" + "\n".join(str(path) for path in missing),
            )
            return False

        if booking_paths:
            self.queue_booking(booking_paths)
        for item in bank_items:
            path = Path(str(item.get("path", "")))
            sheet = item.get("sheet")
            preview = self.container.import_preflight.bank_preview(
                path,
                max_megabytes=int(self.container.settings.all()["imports.max_megabytes"]),
                sheet_name=str(sheet) if sheet else None,
            )
            key = (preview.path, preview.selected_sheet)
            if key not in self.bank_queue:
                self.bank_queue.append(key)
                item_key = ("BANK", str(preview.path), preview.selected_sheet)
                self.queue_previews[item_key] = preview
        self.cashbook_queue = [Path(str(value)) for value in recovery.get("cashbook_paths", []) if Path(str(value)).is_file()]
        self._rebuild_queue_widget()

        if operation_type == "API_SYNC":
            self.run_api()
        elif operation_type == "BOOKING_IMPORT":
            self.run_booking()
        elif operation_type == "BANK_IMPORT":
            self.run_bank()
        elif operation_type == "CASHBOOK_IMPORT":
            self.run_cashbook()
        elif operation_type == "FULL_WORKFLOW":
            self.run_full()
        else:
            QMessageBox.warning(self, "Běh nelze obnovit", f"Neznámý typ operace: {operation_type}")
            return False
        return True

    def _recovery_payload(self, operation_type: str) -> dict[str, Any]:
        return {
            "operation_type": operation_type,
            "booking_paths": [str(path) for path in self.booking_queue],
            "bank_items": [
                {"path": str(path), "sheet": sheet_name}
                for path, sheet_name in self.bank_queue
            ],
            "cashbook_paths": [str(path) for path in self.cashbook_queue],
        }

    def cancel_operation(self) -> None:
        if self.active_operation:
            self.container.operations.cancel(self.active_operation)

    def _api_task(self, context: Any) -> None:
        tokens = self.container.secrets.load_tokens()
        if not tokens.complete:
            raise RuntimeError("Better Hotel tokeny nejsou nastavené. Aplikace zůstává plně dostupná; tokeny zadejte v Nastavení.")
        settings = self.container.settings.all()
        def trace(event: dict[str, Any]) -> None:
            if event.get("event") != "api_response":
                return
            context.heartbeat()

        with BetterHotelClient(Tokens(tokens.access_token, tokens.client_token), timeout_seconds=settings["sync.timeout_seconds"], retries=settings["sync.retry_count"], requests_per_second=settings["sync.requests_per_second"], trace=trace) as client:
            self.container.better_hotel_sync.sync(client, first_day=settings["sync.first_controlled_day"], block_days=settings["sync.history_block_days"], overlap_hours=settings["sync.modified_overlap_hours"], include_extended_reservation_details=False, progress=lambda current, total, message: context.progress(current, total, message, "Better Hotel"), cancel=context.is_cancelled)

    def _booking_task(self, context: Any) -> None:
        queue = list(self.booking_queue)
        for index, path in enumerate(queue, start=1):
            self.container.booking_import.import_file(path, progress_callback=lambda current, total, message, i=index: context.progress(i - 1 + current / max(total, 1), len(queue), message, "Booking.com"), cancel_callback=context.is_cancelled)
        self.booking_queue.clear()

    def _bank_task(self, context: Any) -> None:
        queue = list(self.bank_queue)
        for index, (path, sheet_name) in enumerate(queue, start=1):
            self.container.bank_import.import_file(path, sheet_name=sheet_name, progress_callback=lambda current, total, message, i=index: context.progress(i - 1 + current / max(total, 1), len(queue), message, "Banka"), cancel_callback=context.is_cancelled)
        self.bank_queue.clear()

    def _cashbook_task(self, context: Any) -> None:
        queue = list(self.cashbook_queue)
        for index, path in enumerate(queue, start=1):
            self.container.cashbook_import.import_file(path, cancel_callback=context.is_cancelled)
            context.progress(index, len(queue), f"Pokladní deník: {path.name}", "Pokladna")
        self.cashbook_queue.clear()

    def _full_task(self, context: Any) -> None:
        tokens = self.container.secrets.load_tokens()
        if tokens.complete:
            self._api_task(context)
        else:
            context.heartbeat("Better Hotel přeskočen – tokeny nejsou nastavené.")
        if self.booking_queue:
            self._booking_task(context)
        if self.bank_queue:
            self._bank_task(context)
        if self.cashbook_queue:
            self._cashbook_task(context)
        context.heartbeat("Připravuji deterministické párování úhrad…")
        self.container.payments.auto_reconcile(
            cancel=context.is_cancelled,
            progress=lambda current, total, message: context.progress(current, total, message, "Párování úhrad"),
        )
        if context.is_cancelled():
            return
        self.container.search.rebuild_index()

    def _poll_operation(self) -> None:
        if not self.active_operation:
            self.poll.stop()
            return
        snapshot = self.container.operations.snapshot(self.active_operation)
        if snapshot is None:
            return
        count = ""
        if snapshot.total not in (None, 0):
            count = f" ({snapshot.current or 0}/{snapshot.total})"
        self.progress_label.setText(f"{snapshot.step}{count}: {snapshot.message}")
        if snapshot.total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(1000 * float(snapshot.current or 0) / float(snapshot.total)))
        else:
            self.progress.setRange(0, 0)
        if snapshot.state.value in {"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED", "DISCARDED"}:
            self.poll.stop()
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if snapshot.state.value == "SUCCEEDED" else 0)
            self.cancel.setEnabled(False)
            self.run_all.setEnabled(True)
            self.active_operation = None
            self.refresh_runs()
            self._rebuild_queue_widget()
            self.dataChanged.emit()
            if snapshot.state.value == "FAILED":
                QMessageBox.warning(self, "Operace selhala", snapshot.message)

    def refresh_runs(self) -> None:
        rows: list[tuple[str, Any]] = []
        for table, source in (("api_sync_run", "Better Hotel"), ("booking_import_run", "Booking.com"), ("bank_import_run", "Banka"), ("cashbook_import_run", "Pokladna")):
            rows.extend((source, row) for row in self.container.database.query(f"SELECT * FROM {table} ORDER BY started_at_utc DESC LIMIT 50"))
        rows.sort(key=lambda pair: pair[1]["started_at_utc"], reverse=True)
        self.runs.setRowCount(len(rows))
        for row_index, (source, row) in enumerate(rows):
            values = [source, row["id"], row["state"], row["started_at_utc"], row["finished_at_utc"] or "—", row["counts_json"] if row["error_json"] is None else row["error_json"]]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, (source, row["id"], row["state"]))
                self.runs.setItem(row_index, column, item)
        self.runs.resizeColumnsToContents()

    def focus_run(self, run_id: str) -> bool:
        """Select one persisted import/API run and expose its detail without guessing its source."""
        self.refresh_runs()
        for row in range(self.runs.rowCount()):
            item = self.runs.item(row, 0)
            if item is None:
                continue
            _source, candidate_id, _state = item.data(Qt.ItemDataRole.UserRole)
            if str(candidate_id) != str(run_id):
                continue
            self.runs.selectRow(row)
            self.runs.scrollToItem(item)
            self._run_selected()
            self.runs.setFocus()
            return True
        return False

    def _run_selected(self) -> None:
        items = self.runs.selectedItems()
        if not items:
            self.contextsChanged.emit([])
            self.run_detail.clear()
            return
        row = items[0].row()
        source, run_id, state = self.runs.item(row, 0).data(Qt.ItemDataRole.UserRole)
        context = ObjectContext("IMPORT_RUN", run_id, f"{source} {run_id[:8]}", None, None, None, state, "imports", {"source": source})
        self.contextsChanged.emit([context])
        if source == "Better Hotel":
            table = "api_sync_run"
        elif source == "Booking.com":
            table = "booking_import_run"
        elif source == "Pokladna":
            table = "cashbook_import_run"
        else:
            table = "bank_import_run"
        rows = self.container.database.query(f"SELECT * FROM {table} WHERE id=?", (run_id,))
        self.run_detail.setPlainText(
            "Běh už nebyl nalezen."
            if not rows
            else "\n".join(f"{key}: {value}" for key, value in dict(rows[0]).items())
        )

    def show_quarantine(self) -> None:
        if self.quarantine_dialog is None:
            self.quarantine_dialog = QuarantineDialog(self.container, self.registry, self)
        self.quarantine_dialog.refresh()
        self.quarantine_dialog.show()
        self.quarantine_dialog.raise_()
        self.quarantine_dialog.activateWindow()

    def retry_selected(self) -> None:
        items = self.runs.selectedItems()
        if not items:
            QMessageBox.information(self, "Vyberte běh", "Vyberte běh, který chcete zopakovat.")
            return
        source, _, _ = self.runs.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if source == "Better Hotel":
            self.run_api()
        elif source == "Booking.com":
            self.run_booking()
        else:
            self.run_bank()

    def _rebuild_queue_widget(self) -> None:
        self.queue.clear()
        for path in self.booking_queue:
            key = ("BOOKING", str(path), None)
            preview = self.queue_previews.get(key)
            item = QListWidgetItem(preview.human_summary if preview else f"Booking.com • {path.name}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.queue.addItem(item)
        for path, sheet in self.bank_queue:
            key = ("BANK", str(path), sheet)
            preview = self.queue_previews.get(key)
            item = QListWidgetItem(preview.human_summary if preview else f"Banka • {path.name}" + (f" • {sheet}" if sheet else ""))
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.queue.addItem(item)
        for path in self.cashbook_queue:
            key = ("CASHBOOK", str(path), None)
            item = QListWidgetItem(f"Pokladna • {path.name}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.queue.addItem(item)


def _paths_from_mime(mime: QMimeData) -> list[Path]:
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]
