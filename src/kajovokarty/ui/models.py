from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QByteArray, QItemSelectionModel, QMimeData, QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QLabel,
    QStyle,
    QStyleOptionViewItem,
    QPushButton,
    QTableView,
)
from PySide6.QtCore import QAbstractTableModel

from .action_registry import ActionId, ObjectActionRegistry, ObjectContext
from .component_registry import ComponentId, bind_component

MIME_TYPE = "application/x-kajovokarty-items+json"


def build_items_payload(contexts: Sequence[ObjectContext], *, source_view: str | None = None) -> dict[str, Any]:
    # The MIME contract intentionally contains references and optimistic-lock versions only.
    # Authoritative amounts, currencies and personal data are always reloaded from SQLite on drop.
    payload = {
        "schema_version": 1,
        "selection_id": uuid4().hex,
        "entity_refs": [
            {"entity_type": context.object_type, "entity_id": context.object_id, "row_version": context.row_version}
            for context in contexts
        ],
        "source_view": source_view if source_view is not None else (contexts[0].view if contexts else ""),
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    return payload


def build_items_mime(contexts: Sequence[ObjectContext], *, source_view: str | None = None) -> QMimeData:
    payload = build_items_payload(contexts, source_view=source_view)
    mime = QMimeData()
    mime.setData(MIME_TYPE, QByteArray(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
    return mime


class ObjectTableModel(QAbstractTableModel):
    def __init__(self, headers: Sequence[str], keys: Sequence[str], rows: list[dict[str, Any]] | None = None, parent: Any = None) -> None:
        super().__init__(parent)
        self.headers = list(headers)
        self.keys = list(keys)
        self.rows = rows or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        key = self.keys[index.column()]
        value = row.get(key, "")
        if role == Qt.ItemDataRole.DisplayRole:
            return value
        if role == Qt.ItemDataRole.ToolTipRole:
            context = row.get("_context")
            tooltip = row.get(f"_{key}_tooltip") or row.get("_tooltip")
            if tooltip:
                return tooltip
            if isinstance(context, ObjectContext):
                return f"{context.primary_label}\n{context.object_ref}\nStav: {context.status or '—'}"
        if role == Qt.ItemDataRole.TextAlignmentRole and key in {"amount", "remaining", "difference", "documents", "sources"}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            context = row.get("_context")
            return context.primary_label if isinstance(context, ObjectContext) else str(value)
        if role == Qt.ItemDataRole.UserRole:
            return row.get("_context")
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.headers):
            return self.headers[section]
        return super().headerData(section, orientation, role)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.isValid():
            base |= Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
        return base

    def mimeTypes(self) -> list[str]:
        return [MIME_TYPE]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        rows = sorted({index.row() for index in indexes if index.isValid()})
        contexts = [self.context_at(row) for row in rows]
        return build_items_mime(contexts)

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def context_at(self, row: int) -> ObjectContext:
        context = self.rows[row].get("_context")
        if not isinstance(context, ObjectContext):
            raise TypeError("Řádek nemá ObjectContext.")
        return context


class ObjectTableView(QTableView):
    contextsDropped = Signal(object, object)
    selectionContextsChanged = Signal(object)

    def __init__(self, registry: ObjectActionRegistry, parent: Any = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.drop_preview_provider: Callable[[dict[str, Any], ObjectContext | None], tuple[str, str]] | None = None
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.doubleClicked.connect(lambda _: self._invoke_default())
        self.selectionModelChanged = False
        self.setAccessibleName("Tabulka objektů KájovoKarty")
        self.setAccessibleDescription("Vyberte řádky, otevřete detail klávesou Enter nebo menu Shift+F10.")
        self.drop_preview = QLabel(self.viewport())
        bind_component(self.drop_preview, ComponentId.MATCH_DROP_PREVIEW)
        self.drop_preview.setFrameShape(QFrame.Shape.StyledPanel)
        self.drop_preview.setWordWrap(True)
        self.drop_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_preview.setMargin(10)
        self.drop_preview.hide()
        self.inline_action = QPushButton("Další akce", self.viewport())
        self.inline_action.setAccessibleName("Další akce vybraného řádku")
        self.inline_action.setToolTip(
            "Otevře stejné objektové menu jako pravé tlačítko nebo Shift+F10."
        )
        self.inline_action.clicked.connect(self._show_inline_action_menu)
        self.inline_action.hide()
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._inline_row = -1

    def set_drop_preview_provider(
        self,
        provider: Callable[[dict[str, Any], ObjectContext | None], tuple[str, str]],
    ) -> None:
        self.drop_preview_provider = provider

    def setModel(self, model: ObjectTableModel) -> None:
        previous = self.selectionModel()
        if previous is not None:
            try:
                previous.selectionChanged.disconnect(self._selection_changed)
            except RuntimeError:
                pass
        super().setModel(model)
        if self.selectionModel() is not None:
            self.selectionModel().selectionChanged.connect(self._selection_changed)
        self.horizontalHeader().setStretchLastSection(True)
        self.resizeColumnsToContents()

    def selected_contexts(self) -> list[ObjectContext]:
        model = self.model()
        if not isinstance(model, ObjectTableModel):
            return []
        return [model.context_at(row) for row in sorted({index.row() for index in self.selectionModel().selectedRows()})]

    def restore_selection(self, object_refs: set[str]) -> None:
        model = self.model()
        selection = self.selectionModel()
        if not isinstance(model, ObjectTableModel) or selection is None:
            return
        selection.clearSelection()
        first: QModelIndex | None = None
        for row in range(model.rowCount()):
            context = model.context_at(row)
            if context.object_ref not in object_refs:
                continue
            index = model.index(row, 0)
            selection.select(
                index,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            if first is None:
                first = index
        if first is not None:
            self.setCurrentIndex(first)

    def cancel_drop_preview(self) -> None:
        self._hide_drop_preview()

    def context_at_pos(self, point: QPoint) -> list[ObjectContext]:
        index = self.indexAt(point)
        if index.isValid() and not self.selectionModel().isRowSelected(index.row(), QModelIndex()):
            self.selectRow(index.row())
        return self.selected_contexts()

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        indexes = self.selectedIndexes()
        if not indexes:
            return
        mime = self.model().mimeData(indexes)
        drag = QDrag(self)
        bind_component(drag, ComponentId.MATCH_DRAG_GHOST)
        drag.setMimeData(mime)
        contexts = self.selected_contexts()
        currencies = sorted({ctx.currency for ctx in contexts if ctx.currency})
        totals = {
            currency: sum(ctx.amount_minor or 0 for ctx in contexts if ctx.currency == currency)
            for currency in currencies
        }
        if len(totals) == 1:
            currency, total = next(iter(totals.items()))
            from ..domain.money import Money

            total_text = Money(total, currency).format()
        elif totals:
            from ..domain.money import Money

            total_text = " | ".join(Money(total, currency).format() for currency, total in totals.items())
            total_text += " • více měn – společný drop je zakázaný"
        else:
            total_text = "bez měny"
        text = f"{len(contexts)} položek • {total_text}"
        pixmap = QPixmap(360, 58)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self.palette().window())
        painter.setPen(self.palette().highlight().color())
        painter.drawRoundedRect(1, 1, 356, 54, 8, 8)
        painter.setPen(self.palette().windowText().color())
        painter.drawText(pixmap.rect().adjusted(14, 0, -14, 0), Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()
        drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event: Any) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            payload, target = self._payload_and_target(event)
            if payload is None:
                self._hide_drop_preview()
                event.ignore()
                return
            if self.drop_preview_provider is not None:
                state, message = self.drop_preview_provider(payload, target)
            else:
                state, message = ("allowed", "✓ Uvolněte položky pro zpracování.")
            self._show_drop_preview(state, message)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            self._hide_drop_preview()
            event.ignore()

    def dragLeaveEvent(self, event: Any) -> None:
        self._hide_drop_preview()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: Any) -> None:
        self._hide_drop_preview()
        if not event.mimeData().hasFormat(MIME_TYPE):
            event.ignore()
            return
        try:
            payload = json.loads(bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            event.ignore()
            return
        index = self.indexAt(event.position().toPoint())
        target = None
        model = self.model()
        if index.isValid() and isinstance(model, ObjectTableModel):
            target = model.context_at(index.row())
        self.contextsDropped.emit(payload, target)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._position_drop_preview()
        self._position_inline_action(self._inline_row)

    def mouseMoveEvent(self, event: Any) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            self._position_inline_action(index.row())
        elif not self.hasFocus():
            self.inline_action.hide()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: Any) -> None:
        if self.hasFocus() and self.currentIndex().isValid():
            self._position_inline_action(self.currentIndex().row())
        else:
            self.inline_action.hide()
        super().leaveEvent(event)

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Menu or (event.key() == Qt.Key.Key_F10 and event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._show_context_menu(self.visualRect(self.currentIndex()).center())
            event.accept()
            return
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self._invoke_default()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event: Any) -> None:
        super().focusInEvent(event)
        index = self.currentIndex()
        if index.isValid():
            self._position_inline_action(index.row())
            tooltip = index.data(Qt.ItemDataRole.ToolTipRole)
            if tooltip:
                self.setToolTip(str(tooltip))

    def focusOutEvent(self, event: Any) -> None:
        super().focusOutEvent(event)
        if not self.inline_action.hasFocus():
            self.inline_action.hide()

    def _show_context_menu(self, point: QPoint) -> None:
        contexts = self.context_at_pos(point)
        menu = self.registry.build_menu(self, contexts)
        menu.exec(self.viewport().mapToGlobal(point))

    def _invoke_default(self) -> None:
        contexts = self.selected_contexts()
        if contexts:
            self.registry.handler(ActionId.OPEN_DETAIL, contexts)

    def _selection_changed(self, *_: Any) -> None:
        if self.currentIndex().isValid():
            self._position_inline_action(self.currentIndex().row())
        self.selectionContextsChanged.emit(self.selected_contexts())

    def _show_inline_action_menu(self) -> None:
        if self._inline_row < 0:
            return
        index = self.model().index(self._inline_row, 0)
        if index.isValid() and not self.selectionModel().isRowSelected(
            self._inline_row, QModelIndex()
        ):
            self.selectRow(self._inline_row)
        point = self.visualRect(index).bottomRight()
        self._show_context_menu(point)

    def _position_inline_action(self, row: int) -> None:
        model = self.model()
        if row < 0 or model is None or row >= model.rowCount():
            self.inline_action.hide()
            self._inline_row = -1
            return
        last_column = max(0, model.columnCount() - 1)
        rect = self.visualRect(model.index(row, last_column))
        if not rect.isValid() or rect.height() <= 0:
            self.inline_action.hide()
            return
        self._inline_row = row
        hint = self.inline_action.sizeHint()
        width = min(max(92, hint.width()), max(92, rect.width() - 8))
        height = min(max(24, hint.height()), max(24, rect.height() - 4))
        self.inline_action.setGeometry(
            max(rect.left() + 4, rect.right() - width - 4),
            rect.top() + max(2, (rect.height() - height) // 2),
            width,
            height,
        )
        self.inline_action.show()
        self.inline_action.raise_()

    def _payload_and_target(self, event: Any) -> tuple[dict[str, Any] | None, ObjectContext | None]:
        try:
            payload = json.loads(bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, None
        index = self.indexAt(event.position().toPoint())
        model = self.model()
        target = model.context_at(index.row()) if index.isValid() and isinstance(model, ObjectTableModel) else None
        return payload, target

    def _show_drop_preview(self, state: str, message: str) -> None:
        icons = {"allowed": "✓", "partial": "ℹ", "blocked": "⛔", "conflict": "⚠"}
        roles = {
            "allowed": "palette(highlight)",
            "partial": "palette(link)",
            "blocked": "palette(mid)",
            "conflict": "palette(dark)",
        }
        self.drop_preview.setText(f"{icons.get(state, 'ℹ')} {message}")
        self.drop_preview.setStyleSheet(
            "QLabel { background: palette(base); border: 3px solid "
            + roles.get(state, "palette(mid)")
            + "; border-radius: 8px; color: palette(text); font-weight: 600; }"
        )
        self.drop_preview.setAccessibleName(f"Náhled cíle přetažení: {message}")
        self._position_drop_preview()
        self.drop_preview.show()
        self.drop_preview.raise_()

    def _hide_drop_preview(self) -> None:
        self.drop_preview.hide()

    def _position_drop_preview(self) -> None:
        width = max(260, min(560, self.viewport().width() - 32))
        self.drop_preview.setGeometry(
            max(16, (self.viewport().width() - width) // 2),
            16,
            width,
            72,
        )
