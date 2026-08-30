from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...app.container import ServiceContainer
from ..action_registry import ActionId, ObjectActionRegistry, ObjectContext
from ..component_registry import ComponentId, bind_component


class AuditScreen(QWidget):
    contextsChanged = Signal(object)
    openCurrent = Signal(str)

    def __init__(self, container: ServiceContainer, registry: ObjectActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self.registry = registry
        root = QVBoxLayout(self)
        title = QLabel("Auditní historie")
        title.setObjectName("screenTitle")
        root.addWidget(title)

        filters_widget = QWidget()
        bind_component(filters_widget, ComponentId.AUDIT_FILTERS)
        filters = QHBoxLayout(filters_widget)
        filters.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Operace, objekt, command nebo correlation ID…")
        self.search.returnPressed.connect(self.refresh)
        self.event_filter = QComboBox()
        self.event_filter.addItem("Všechny události", "")
        for event in ("MANUAL", "IMPORT", "MATCH", "SETTING", "BACKUP", "ERROR", "UNDO", "REDO"):
            self.event_filter.addItem(event, event)
        self.event_filter.currentIndexChanged.connect(self.refresh)
        refresh = QPushButton("Obnovit")
        refresh.clicked.connect(self.refresh)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.event_filter)
        filters.addWidget(refresh)
        root.addWidget(filters_widget)

        splitter = QSplitter()
        self.table = QTableWidget(0, 8)
        bind_component(self.table, ComponentId.AUDIT_TIMELINE)
        self.table.setHorizontalHeaderLabels(
            ["Čas", "Operace", "Objekt", "Command ID", "Correlation ID", "Účet", "Událost", "Akce"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.setAccessibleName("Časová osa auditu")
        splitter.addWidget(self.table)

        detail = QWidget()
        bind_component(detail, ComponentId.AUDIT_BEFORE_AFTER)
        detail_layout = QVBoxLayout(detail)
        self.detail_title = QLabel("Vyberte auditní událost")
        self.detail_title.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        self.before = QPlainTextEdit()
        self.before.setReadOnly(True)
        self.before.setPlaceholderText("Stav před změnou")
        self.before.setAccessibleName("Stav před změnou")
        self.after = QPlainTextEdit()
        self.after.setReadOnly(True)
        self.after.setPlaceholderText("Stav po změně")
        self.after.setAccessibleName("Stav po změně")
        detail_layout.addWidget(QLabel("Před změnou"))
        detail_layout.addWidget(self.before, 1)
        detail_layout.addWidget(QLabel("Po změně"))
        detail_layout.addWidget(self.after, 1)
        actions = QHBoxLayout()
        open_current = QPushButton("Otevřít aktuální stav")
        bind_component(open_current, ComponentId.AUDIT_OPEN_CURRENT)
        open_current.clicked.connect(self._open_current)
        undo = QPushButton("Vrátit tento příkaz")
        bind_component(undo, ComponentId.AUDIT_UNDO)
        undo.clicked.connect(self._undo)
        actions.addWidget(open_current)
        actions.addWidget(undo)
        actions.addStretch(1)
        detail_layout.addLayout(actions)
        splitter.addWidget(detail)
        splitter.setSizes([850, 500])
        root.addWidget(splitter, 1)
        self.refresh()

    def refresh(self) -> None:
        text = self.search.text().strip()
        event = str(self.event_filter.currentData())
        where: list[str] = []
        params: list[Any] = []
        if text:
            where.append("(operation_label LIKE ? OR object_ref LIKE ? OR command_id LIKE ? OR correlation_id LIKE ?)")
            params.extend([f"%{text}%"] * 4)
        if event:
            where.append("(event_code LIKE ? OR operation_label LIKE ?)")
            params.extend([f"%{event}%", f"%{event}%"])
        sql = "SELECT * FROM audit_event" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at_utc DESC LIMIT 5000"
        rows = self.container.database.query(sql, params)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            context = ObjectContext("AUDIT", row["event_id"], row["operation_label"], None, None, None, None, "audit", {"object_ref": row["object_ref"], "command_id": row["command_id"], "correlation_id": row["correlation_id"], "before_json": row["before_json"], "after_json": row["after_json"], "event_code": row["event_code"]})
            values = (row["created_at_utc"], row["operation_label"], row["object_ref"], row["command_id"] or "", row["correlation_id"], row["windows_user"], row["event_code"])
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.ItemDataRole.UserRole, context)
                item.setToolTip(str(value or ""))
                self.table.setItem(row_index, column, item)
            action_button = QPushButton("Další akce")
            action_button.setAccessibleName(f"Další akce auditní události: {context.primary_label}")
            action_button.setToolTip(
                "Otevře stejné auditní objektové menu jako pravé tlačítko nebo Shift+F10."
            )
            action_button.clicked.connect(
                lambda _checked=False, ctx=context, button=action_button: self._menu_for_context(
                    button, ctx
                )
            )
            self.table.setCellWidget(row_index, 7, action_button)
        self.table.resizeColumnsToContents()

    def focus_object(self, object_ref: str) -> None:
        self.search.setText(object_ref)
        self.refresh()

    def selected_context(self) -> ObjectContext | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        context = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        return context if isinstance(context, ObjectContext) else None

    def _selected(self) -> None:
        context = self.selected_context()
        self.contextsChanged.emit([] if context is None else [context])
        if context is None:
            self.before.clear()
            self.after.clear()
            return
        self.detail_title.setText(f"{context.primary_label}\n{context.data.get('object_ref', '')}")
        self.before.setPlainText(_pretty(context.data.get("before_json")))
        self.after.setPlainText(_pretty(context.data.get("after_json")))

    def _menu(self, point: Any) -> None:
        context = self.selected_context()
        menu = self.registry.build_menu(self.table, [] if context is None else [context])
        menu.exec(self.table.viewport().mapToGlobal(point))

    def _menu_for_context(self, button: QPushButton, context: ObjectContext) -> None:
        self.registry.build_menu(self.table, [context]).exec(
            button.mapToGlobal(button.rect().bottomLeft())
        )

    def _open_current(self) -> None:
        context = self.selected_context()
        if context is not None and context.data.get("object_ref"):
            self.openCurrent.emit(str(context.data["object_ref"]))

    def _undo(self) -> None:
        context = self.selected_context()
        if context is not None:
            self.registry.handler(ActionId.UNDO, [context])


def _pretty(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        return json.dumps(json.loads(str(value)), ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError, json.JSONDecodeError):
        return str(value)
