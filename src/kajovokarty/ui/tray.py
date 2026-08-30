from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QWidget

from .action_registry import ObjectContext
from .models import build_items_mime


class WorkingTrayList(QListWidget):
    contextsChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setMaximumHeight(72)
        self.itemSelectionChanged.connect(self._emit_selection)
        self.setAccessibleName("Položky pracovního výběru")
        self.setAccessibleDescription("Vyberte doklady a zdroje a přetáhněte je na plátno párování.")

    def set_contexts(self, contexts: Sequence[ObjectContext]) -> None:
        self.clear()
        for context in contexts:
            item = QListWidgetItem(context.primary_label)
            item.setData(Qt.ItemDataRole.UserRole, context)
            details = [context.object_type, context.currency or "bez měny"]
            if context.status:
                details.append(context.status)
            item.setToolTip(" • ".join(details) + f"\n{context.object_ref}")
            self.addItem(item)

    def selected_contexts(self) -> list[ObjectContext]:
        contexts: list[ObjectContext] = []
        for item in self.selectedItems():
            context = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(context, ObjectContext):
                contexts.append(context)
        return contexts

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        contexts = self.selected_contexts()
        if not contexts:
            contexts = [
                context
                for index in range(self.count())
                if isinstance((context := self.item(index).data(Qt.ItemDataRole.UserRole)), ObjectContext)
            ]
        if not contexts:
            return
        drag = QDrag(self)
        drag.setMimeData(build_items_mime(contexts, source_view="working_tray"))
        drag.exec(Qt.DropAction.CopyAction)

    def _emit_selection(self) -> None:
        self.contextsChanged.emit(self.selected_contexts())
