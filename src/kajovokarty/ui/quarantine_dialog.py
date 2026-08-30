from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..app.container import ServiceContainer
from .action_registry import ActionId, ObjectActionRegistry, ObjectContext
from .component_registry import ComponentId, bind_component
from .models import ObjectTableModel, ObjectTableView


class QuarantineDialog(QDialog):
    """Live quarantine workbench backed by the central ObjectActionRegistry."""

    def __init__(
        self,
        container: ServiceContainer,
        registry: ObjectActionRegistry,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.container = container
        self.registry = registry
        self.setWindowTitle("Karanténa importů")
        self.setModal(False)
        self.resize(1180, 720)
        self.setMinimumSize(900, 560)
        self.setAccessibleName("Karanténa importů")
        self.setAccessibleDescription(
            "Řádky, které nebylo možné bezpečně importovat. Vyberte řádek, zobrazte původní data a zvolte auditované rozhodnutí."
        )
        bind_component(self, ComponentId.IMPORT_QUARANTINE)

        root = QVBoxLayout(self)
        title = QLabel("Karanténa importů")
        title.setObjectName("screenTitle")
        root.addWidget(title)

        filters = QHBoxLayout()
        self.state_filter = QComboBox()
        self.state_filter.addItem("Všechny stavy", "")
        for state in ("OPEN", "READY_FOR_RETRY", "RESOLVED", "IGNORED"):
            self.state_filter.addItem(state, state)
        self.state_filter.currentIndexChanged.connect(self.refresh)
        self.reason_filter = QComboBox()
        self.reason_filter.addItem("Všechny důvody", "")
        self.reason_filter.currentIndexChanged.connect(self.refresh)
        refresh = QPushButton("Obnovit")
        refresh.clicked.connect(self.refresh)
        filters.addWidget(QLabel("Stav:"))
        filters.addWidget(self.state_filter)
        filters.addWidget(QLabel("Důvod:"))
        filters.addWidget(self.reason_filter, 1)
        filters.addWidget(refresh)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = ObjectTableView(registry)
        self.table.setObjectName("quarantineTable")
        self.table.setAccessibleName("Karanténní řádky")
        self.table.setModel(
            ObjectTableModel(
                ["Zdroj", "Řádek", "Důvod", "Popis", "Stav", "Pokusy", "Vytvořeno"],
                ["source", "row", "reason", "description", "state", "retries", "created"],
            )
        )
        self.table.selectionContextsChanged.connect(self._selection_changed)
        splitter.addWidget(self.table)

        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setAccessibleName("Původní karanténní řádek a rozhodnutí")
        self.raw.setPlaceholderText("Vyberte řádek. Zde se zobrazí kanonizovaný původní řádek, důvod a dosavadní rozhodnutí.")
        splitter.addWidget(self.raw)
        splitter.setSizes([440, 220])
        root.addWidget(splitter, 1)

        action_row = QHBoxLayout()
        self.resolve = QPushButton("Vyřešit řádek")
        bind_component(self.resolve, ComponentId.IMPORT_TYPE_MAPPING)
        self.resolve.setEnabled(False)
        self.resolve.clicked.connect(self._resolve_selected)
        self.show_source = QPushButton("Zobrazit původní zdrojový řádek")
        self.show_source.setEnabled(False)
        self.show_source.clicked.connect(self._show_source_action)
        self.show_audit = QPushButton("Zobrazit historii změn")
        self.show_audit.setEnabled(False)
        self.show_audit.clicked.connect(self._show_audit_action)
        action_row.addWidget(self.resolve)
        action_row.addWidget(self.show_source)
        action_row.addWidget(self.show_audit)
        action_row.addStretch(1)
        root.addLayout(action_row)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)
        self.refresh()

    def selected_contexts(self) -> list[ObjectContext]:
        return self.table.selected_contexts()

    def refresh(self) -> None:
        previous_id = self.selected_contexts()[0].object_id if self.selected_contexts() else None
        params: list[Any] = []
        clauses = ["1=1"]
        state = str(self.state_filter.currentData() or "")
        reason = str(self.reason_filter.currentData() or "")
        if state:
            clauses.append("state=?")
            params.append(state)
        if reason:
            clauses.append("reason_code=?")
            params.append(reason)
        rows = self.container.database.query(
            "SELECT id,run_type,run_id,row_no,reason_code,reason_text,state,retry_count,raw_json,resolution_json,"
            "resolution_method,created_at_utc,updated_at_utc,resolved_at_utc "
            f"FROM quarantined_source_row WHERE {' AND '.join(clauses)} "
            "ORDER BY CASE state WHEN 'OPEN' THEN 0 WHEN 'READY_FOR_RETRY' THEN 1 ELSE 2 END, created_at_utc DESC LIMIT 5000",
            params,
        )
        reasons = sorted({str(row["reason_code"]) for row in rows})
        current_reason = str(self.reason_filter.currentData() or "")
        self.reason_filter.blockSignals(True)
        self.reason_filter.clear()
        self.reason_filter.addItem("Všechny důvody", "")
        for value in reasons:
            self.reason_filter.addItem(value, value)
        index = self.reason_filter.findData(current_reason)
        self.reason_filter.setCurrentIndex(max(0, index))
        self.reason_filter.blockSignals(False)

        model_rows: list[dict[str, Any]] = []
        restore_row = -1
        for index, row in enumerate(rows):
            context = ObjectContext(
                "QUARANTINE",
                str(row["id"]),
                f"{row['run_type']} řádek {row['row_no']}",
                None,
                None,
                None,
                str(row["state"]),
                "imports",
                {
                    "run_id": row["run_id"],
                    "reason_code": row["reason_code"],
                    "object_ref": f"QUARANTINE:{row['id']}",
                },
            )
            model_rows.append(
                {
                    "source": row["run_type"],
                    "row": row["row_no"],
                    "reason": row["reason_code"],
                    "description": row["reason_text"],
                    "state": row["state"],
                    "retries": row["retry_count"],
                    "created": row["created_at_utc"],
                    "_context": context,
                    "_tooltip": f"Běh: {row['run_id']}\nAktualizováno: {row['updated_at_utc']}\nMetoda: {row['resolution_method'] or '—'}",
                    "_raw": dict(row),
                }
            )
            if previous_id == row["id"]:
                restore_row = index
        self.table.model().set_rows(model_rows)
        if restore_row >= 0:
            self.table.selectRow(restore_row)
        self.summary.setText(
            f"Zobrazeno {len(model_rows)} řádků. Neznámé hodnoty se nikdy tiše neignorují; každé rozhodnutí je auditované a vratné."
        )
        self._selection_changed(self.table.selected_contexts())

    def _selection_changed(self, contexts: list[ObjectContext]) -> None:
        enabled = bool(contexts)
        self.resolve.setEnabled(enabled)
        self.show_source.setEnabled(enabled)
        self.show_audit.setEnabled(enabled)
        if not contexts:
            self.raw.clear()
            return
        context = contexts[0]
        rows = self.container.database.query("SELECT * FROM quarantined_source_row WHERE id=?", (context.object_id,))
        if not rows:
            self.raw.setPlainText("Řádek už neexistuje.")
            return
        row = dict(rows[0])
        try:
            raw = json.loads(str(row.get("raw_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = row.get("raw_json")
        try:
            resolution = json.loads(str(row.get("resolution_json") or "null"))
        except (TypeError, ValueError, json.JSONDecodeError):
            resolution = row.get("resolution_json")
        self.raw.setPlainText(
            json.dumps(
                {
                    "důvod": {"kód": row.get("reason_code"), "popis": row.get("reason_text")},
                    "stav": row.get("state"),
                    "pokusy": row.get("retry_count"),
                    "rozhodnutí": resolution,
                    "původní_řádek": raw,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    def _trigger(self, action_id: ActionId) -> None:
        contexts = self.selected_contexts()
        if not contexts:
            return
        self.registry.handler(action_id, contexts)
        QTimer.singleShot(0, self.refresh)

    def _resolve_selected(self) -> None:
        self._trigger(ActionId.RESOLVE_QUARANTINE)

    def _show_source_action(self) -> None:
        self._trigger(ActionId.SHOW_SOURCE_ROW)

    def _show_audit_action(self) -> None:
        self._trigger(ActionId.SHOW_AUDIT)
