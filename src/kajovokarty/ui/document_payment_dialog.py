from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout

from ..application.pairing import DocumentRef, PairingError, SourceRef
from ..domain.enums import SourceType
from ..domain.money import Money
from ..application.payment_reconciliation import DocumentPaymentService
from ..infrastructure.persistence.database import Database
from .component_registry import ComponentId, bind_component


class DocumentPaymentDialog(QDialog):
    changed = Signal()

    def __init__(self, database: Database, payments: DocumentPaymentService, invoice_id: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.database = database
        self.payments = payments
        self.invoice_id = invoice_id
        self.setWindowTitle("Detail úhrady dokladu")
        self.setMinimumSize(980, 640)
        bind_component(self, ComponentId.MATCH_DETAIL_DRAWER)
        root = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        root.addWidget(self.heading)
        self.status = QLabel()
        self.status.setObjectName("paymentStatus")
        root.addWidget(self.status)
        self.tabs = QTabWidget()
        self.confirmations = QTableWidget()
        self.confirmations.setColumnCount(6)
        self.confirmations.setHorizontalHeaderLabels(["Zdroj", "ID potvrzení", "Přiřazeno", "Zbývá zdroji", "Společně uhrazené doklady", "Datum"])
        self.confirmations.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.confirmations.setColumnHidden(0, False)
        self.tabs.addTab(self.confirmations, "Přiřazená potvrzení")
        self.booking = QTableWidget()
        self.booking.setColumnCount(6)
        self.booking.setHorizontalHeaderLabels(["ID", "Booking číslo", "Datum", "Částka", "Měna", "Zbývá"])
        self.booking.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabs.addTab(self.booking, "Volné úhrady Booking.com")
        self.terminal = QTableWidget()
        self.terminal.setColumnCount(6)
        self.terminal.setHorizontalHeaderLabels(["ID", "SEQ", "Datum", "Částka", "Měna", "Zbývá"])
        self.terminal.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabs.addTab(self.terminal, "Volné úhrady terminál")
        root.addWidget(self.tabs, 1)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setPlaceholderText("Celá importovaná věta vybraného potvrzení")
        root.addWidget(self.raw, 1)
        actions = QHBoxLayout()
        self.pair = QPushButton("Spárovat vybranou volnou úhradu")
        self.pair.clicked.connect(self._pair_selected)
        self.manual_paid = QPushButton("Označit bez důkazu")
        self.manual_paid.clicked.connect(self._manual_paid)
        self.clear_manual = QPushButton("Zrušit ruční úhradu")
        self.clear_manual.clicked.connect(self._clear_manual)
        self.unlink = QPushButton("Rozpojit vybranou vazbu")
        self.unlink.clicked.connect(self._unlink_selected)
        actions.addWidget(self.pair)
        actions.addWidget(self.unlink)
        actions.addWidget(self.manual_paid)
        actions.addWidget(self.clear_manual)
        actions.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        actions.addWidget(close)
        root.addLayout(actions)
        self.booking.itemSelectionChanged.connect(lambda: self._show_raw(self.booking))
        self.terminal.itemSelectionChanged.connect(lambda: self._show_raw(self.terminal))
        self.refresh()

    def refresh(self) -> None:
        invoice = self.database.query("SELECT * FROM invoice WHERE external_id=?", (self.invoice_id,))
        if not invoice:
            self.reject()
            return
        row = invoice[0]
        status = self.payments.status(self.invoice_id).value
        self.heading.setText(f"Doklad {row['code']} • datum {str(row['document_date_utc'])[:10]} • {Money(row['total_minor'], row['currency_code']).format()} {row['currency_code']}")
        manual = self.database.query("SELECT manual_paid_at_utc,manual_paid_by FROM invoice_payment_status WHERE invoice_id=? AND manual_paid=1", (self.invoice_id,))
        suffix = f" — ručně označeno {manual[0]['manual_paid_at_utc']}" if manual else ""
        self.status.setText(f"Stav úhrady: {status}{suffix}")
        allocations = self.database.query("SELECT a.*,i.code FROM allocation a JOIN invoice i ON i.external_id=a.invoice_id WHERE a.invoice_id=? AND a.active=1 ORDER BY a.created_at_utc,a.id", (self.invoice_id,))
        self.confirmations.setRowCount(len(allocations))
        for index, allocation in enumerate(allocations):
            shared = self.database.query("SELECT i.code FROM allocation a JOIN invoice i ON i.external_id=a.invoice_id WHERE a.source_type=? AND a.source_id=? AND a.active=1 AND a.invoice_id<>? ORDER BY i.code", (allocation['source_type'], allocation['source_id'], self.invoice_id))
            values = [allocation['source_type'], allocation['source_id'], str(allocation['amount_minor']), self._source_remaining(allocation['source_type'], allocation['source_id']), ", ".join(str(x['code']) for x in shared), str(allocation['created_at_utc'])]
            self.confirmations.item_data = getattr(self.confirmations, 'item_data', {})
            self.confirmations.item_data[index] = dict(allocation)
            for column, value in enumerate(values): self.confirmations.setItem(index, column, QTableWidgetItem(str(value)))
        self._load_sources(self.booking, SourceType.BOOKING)
        self._load_sources(self.terminal, SourceType.CARD)
        self.confirmations.resizeColumnsToContents(); self.booking.resizeColumnsToContents(); self.terminal.resizeColumnsToContents()

    def _unlink_selected(self) -> None:
        selected = self.confirmations.selectionModel().selectedRows()
        if not selected:
            return
        allocation = getattr(self.confirmations, 'item_data', {}).get(selected[0].row(), {})
        allocation_id = str(allocation.get('id') or '')
        if not allocation_id:
            return
        answer = QMessageBox.question(self, "Rozpojit vazbu", "Opravdu rozpojit vybranou vazbu? Potvrzení úhrady se vrátí mezi volné úhrady.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.payments.unlink_allocation(allocation_id)
        self.changed.emit()
        self.refresh()

    def _load_sources(self, table: QTableWidget, source_type: SourceType) -> None:
        if source_type == SourceType.BOOKING:
            rows = self.database.query("SELECT b.*,b.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='BOOKING' AND a.source_id=b.row_hash AND a.active=1),0) AS remaining_minor FROM booking_payment_line b WHERE b.active_source=1 AND b.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='BOOKING' AND a.source_id=b.row_hash AND a.active=1),0)<>0 ORDER BY b.payout_date,b.row_hash")
            values = lambda row: [row['row_hash'], row['booking_reference'], row['payout_date'], row['amount_minor'], row['currency_code'], row['remaining_minor']]
        else:
            rows = self.database.query("SELECT c.*,c.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='CARD' AND a.source_id=c.id AND a.active=1),0) AS remaining_minor FROM card_transaction c WHERE c.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='CARD' AND a.source_id=c.id AND a.active=1),0)<>0 ORDER BY c.occurred_at,c.id")
            values = lambda row: [row['id'], row['seq_id'], row['occurred_at'], row['amount_minor'], row['currency_code'], row['remaining_minor']]
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            table.item_data = getattr(table, 'item_data', {})
            table.item_data[index] = dict(row)
            for column, value in enumerate(values(row)): table.setItem(index, column, QTableWidgetItem(str(value)))

    def _source_remaining(self, source_type: str, source_id: str) -> int:
        if source_type == "BOOKING":
            row = self.database.query("SELECT amount_minor FROM booking_payment_line WHERE row_hash=?", (source_id,))
        elif source_type == "CARD":
            row = self.database.query("SELECT amount_minor FROM card_transaction WHERE id=?", (source_id,))
        else:
            row = self.database.query("SELECT amount_minor FROM manual_settlement WHERE id=?", (source_id,))
        used = self.database.scalar("SELECT COALESCE(SUM(amount_minor),0) FROM allocation WHERE source_type=? AND source_id=? AND active=1", (source_type, source_id))
        return int(row[0][0]) - int(used or 0) if row else 0

    def _show_raw(self, table: QTableWidget) -> None:
        selected = table.selectionModel().selectedRows()
        if not selected: return
        row = getattr(table, 'item_data', {}).get(selected[0].row(), {})
        try: self.raw.setPlainText(json.dumps(json.loads(row.get('raw_json') or '{}'), ensure_ascii=False, indent=2))
        except (TypeError, ValueError): self.raw.setPlainText(str(row.get('raw_json') or ''))

    def _pair_selected(self) -> None:
        table = self.booking if self.tabs.currentWidget() is self.booking else self.terminal
        selected = table.selectionModel().selectedRows()
        if not selected: return
        row = getattr(table, 'item_data', {}).get(selected[0].row(), {})
        source_type = SourceType.BOOKING if table is self.booking else SourceType.CARD
        invoice = self.database.query("SELECT total_minor FROM invoice WHERE external_id=?", (self.invoice_id,))[0]
        used = self.database.scalar("SELECT COALESCE(SUM(amount_minor),0) FROM allocation WHERE invoice_id=? AND active=1", (self.invoice_id,)) or 0
        remaining = int(invoice['total_minor']) - int(used)
        if int(row.get('remaining_minor', 0)) < abs(remaining):
            QMessageBox.warning(self, "Potvrzení nestačí", "Ruční párování částečné úhrady není dovoleno. Vyberte potvrzení s dostatečným zůstatkem.")
            return
        try:
            self.payments.pairing.pair_one(DocumentRef(self.invoice_id), SourceRef(source_type, str(row.get('row_hash') or row.get('id'))), amount_minor=remaining)
        except PairingError as exc:
            QMessageBox.warning(self, "Párování se nezdařilo", str(exc)); return
        self.changed.emit(); self.refresh()

    def _manual_paid(self) -> None:
        self.payments.mark_manual_paid(self.invoice_id); self.changed.emit(); self.refresh()

    def _clear_manual(self) -> None:
        self.payments.clear_manual_paid(self.invoice_id); self.changed.emit(); self.refresh()
