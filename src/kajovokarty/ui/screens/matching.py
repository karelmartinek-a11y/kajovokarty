from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...app.container import ServiceContainer
from ...application.pairing import DocumentRef, PairingError, SourceRef
from ...domain.enums import SourceType
from ...domain.money import Money
from ..action_registry import ActionId, ObjectActionRegistry, ObjectContext
from ..allocation_plan import format_allocation_plan
from ..component_registry import ComponentId, bind_component
from ..models import MIME_TYPE, ObjectTableModel, ObjectTableView


@dataclass(slots=True)
class PaintedAllocation:
    rect: QRectF
    context: ObjectContext


class GroupCanvas(QWidget):
    contextSelected = Signal(object)
    allocationActivated = Signal(object)
    contextsDropped = Signal(object, object)

    def __init__(self, container: ServiceContainer, registry: ObjectActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self.registry = registry
        self.groups: list[dict[str, Any]] = []
        self.hit_groups: list[tuple[QRectF, ObjectContext]] = []
        self.hit_allocations: list[PaintedAllocation] = []
        self.drop_preview_provider: Callable[[dict[str, Any], ObjectContext | None], tuple[str, str]] | None = None
        self.drop_state = ""
        self.drop_message = ""
        self.drop_target: ObjectContext | None = None
        self.setAcceptDrops(True)
        bind_component(self, ComponentId.MATCH_CANVAS)
        self.setMinimumWidth(360)
        self.setMinimumHeight(500)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Vyrovnávací skupiny")
        self.setAccessibleDescription("Grafický přehled skupin. Číselný ekvivalent vazeb je v tabulce pod plátnem.")

    def set_groups(self, groups: list[dict[str, Any]]) -> None:
        self.groups = groups
        self.setMinimumHeight(max(500, 190 * len(groups) + 30))
        self.update()

    def set_drop_preview_provider(
        self, provider: Callable[[dict[str, Any], ObjectContext | None], tuple[str, str]]
    ) -> None:
        self.drop_preview_provider = provider

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.hit_groups.clear()
        self.hit_allocations.clear()
        y = 20.0
        for group in self.groups:
            card = QRectF(20, y, max(320, self.width() - 40), 160)
            painter.setPen(QPen(self.palette().mid().color(), 1.2))
            painter.setBrush(self.palette().base())
            painter.drawRoundedRect(card, 10, 10)
            status = group["status"]
            title = f"Skupina {group['id'][:8]} • {status} • {group['currency']}"
            painter.setPen(self.palette().text().color())
            painter.drawText(card.adjusted(14, 8, -14, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, title)
            summary = f"Doklady: {group['document_total']}   Zdroje: {group['source_total']}   Rozdíl: {group['difference']}"
            painter.drawText(card.adjusted(14, 34, -14, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, summary)
            group_context = group["_context"]
            self.hit_groups.append((card, group_context))
            left_x = card.left() + 20
            right_x = card.right() - 150
            row_y = card.top() + 72
            allocations = group.get("allocations", [])
            if group.get("allocation_mode") == "AGGREGATE":
                painter.drawText(card.adjusted(14, 72, -14, -12), Qt.AlignmentFlag.AlignTop, "≡ Vyrovnáno jako celek – bez neprokázaných párových vazeb")
            elif not allocations:
                painter.drawText(card.adjusted(14, 72, -14, -12), Qt.AlignmentFlag.AlignTop, "Skupina zatím nemá detailní vazby.")
            for allocation in allocations[:4]:
                left = QRectF(left_x, row_y, 130, 26)
                right = QRectF(right_x, row_y, 130, 26)
                painter.setBrush(self.palette().alternateBase())
                painter.drawRoundedRect(left, 4, 4)
                painter.drawRoundedRect(right, 4, 4)
                painter.drawText(left.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, allocation["invoice_label"])
                painter.drawText(right.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, allocation["source_label"])
                path = QPainterPath()
                path.moveTo(left.right(), left.center().y())
                path.cubicTo(left.right() + 30, left.center().y(), right.left() - 30, right.center().y(), right.left(), right.center().y())
                pen = QPen(self.palette().highlight().color(), 2)
                painter.setPen(pen)
                painter.drawPath(path)
                amount_rect = QRectF((left.right() + right.left()) / 2 - 55, row_y - 3, 110, 24)
                painter.setBrush(self.palette().base())
                painter.drawRoundedRect(amount_rect, 3, 3)
                painter.drawText(amount_rect, Qt.AlignmentFlag.AlignCenter, allocation["amount"])
                self.hit_allocations.append(PaintedAllocation(amount_rect.adjusted(-16, -8, 16, 8), allocation["_context"]))
                row_y += 30
            if len(allocations) > 4:
                painter.drawText(card.adjusted(14, 137, -14, -6), Qt.AlignmentFlag.AlignBottom, f"+ {len(allocations) - 4} dalších vazeb – kompletní tabulka je pod plátnem")
            y += 180
        if self.drop_message:
            preview = QRectF(24, max(20, self.height() - 86), max(300, self.width() - 48), 62)
            palette_role = self.palette().highlight().color() if self.drop_state == "allowed" else self.palette().link().color() if self.drop_state == "partial" else self.palette().dark().color()
            painter.setPen(QPen(palette_role, 3))
            painter.setBrush(self.palette().base())
            painter.drawRoundedRect(preview, 8, 8)
            icon = {"allowed": "✓", "partial": "ℹ", "blocked": "⛔", "conflict": "⚠"}.get(self.drop_state, "ℹ")
            painter.setPen(self.palette().text().color())
            painter.drawText(preview.adjusted(12, 6, -12, -6), Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, f"{icon} {self.drop_message}")
        painter.end()

    def _context_at_point(self, point: Any) -> ObjectContext | None:
        for rect, context in self.hit_groups:
            if rect.contains(point):
                return context
        return None

    @staticmethod
    def _decode_mime(event: Any) -> dict[str, Any] | None:
        if not event.mimeData().hasFormat(MIME_TYPE):
            return None
        try:
            payload = json.loads(bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def dragEnterEvent(self, event: Any) -> None:
        payload = self._decode_mime(event)
        if payload is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragMoveEvent(self, event: Any) -> None:
        payload = self._decode_mime(event)
        if payload is None:
            self.drop_message = ""
            self.update()
            event.ignore()
            return
        target = self._context_at_point(event.position())
        self.drop_target = target
        if self.drop_preview_provider is None:
            self.drop_state, self.drop_message = "allowed", "Uvolněte položky na skupinu nebo prázdné plátno."
        else:
            self.drop_state, self.drop_message = self.drop_preview_provider(payload, target)
        self.setAccessibleDescription(self.drop_message)
        self.update()
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event: Any) -> None:
        self.drop_state = ""
        self.drop_message = ""
        self.drop_target = None
        self.update()
        super().dragLeaveEvent(event)

    def cancel_drop_preview(self) -> None:
        self.drop_state = ""
        self.drop_message = ""
        self.drop_target = None
        self.setAccessibleDescription(
            "Grafický přehled skupin. Číselný ekvivalent vazeb je v tabulce pod plátnem."
        )
        self.update()

    def dropEvent(self, event: Any) -> None:
        payload = self._decode_mime(event)
        target = self._context_at_point(event.position())
        self.drop_state = ""
        self.drop_message = ""
        self.drop_target = None
        self.update()
        if payload is None:
            event.ignore()
            return
        self.contextsDropped.emit(payload, target)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def mousePressEvent(self, event: Any) -> None:
        point = event.position()
        for allocation in self.hit_allocations:
            if allocation.rect.contains(point):
                self.contextSelected.emit([allocation.context])
                if event.button() == Qt.MouseButton.RightButton:
                    self.registry.build_menu(self, [allocation.context]).exec(event.globalPosition().toPoint())
                return
        for rect, context in self.hit_groups:
            if rect.contains(point):
                self.contextSelected.emit([context])
                if event.button() == Qt.MouseButton.RightButton:
                    self.registry.build_menu(self, [context]).exec(event.globalPosition().toPoint())
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: Any) -> None:
        point = event.position()
        for allocation in self.hit_allocations:
            if allocation.rect.contains(point):
                self.allocationActivated.emit(allocation.context)
                return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        point = event.position()
        for allocation in self.hit_allocations:
            if allocation.rect.contains(point):
                self.setToolTip(allocation.context.data.get("tooltip", allocation.context.primary_label))
                return
        self.setToolTip("")
        super().mouseMoveEvent(event)


class MatchingScreen(QWidget):
    contextsChanged = Signal(object)
    toast = Signal(str)
    counterpartsRequested = Signal(object, object)

    STATUS_MAP = {
        "NEUHRAZEN": ("NEUHRAZEN",),
        "ČÁSTEČNÁ ÚHRADA": ("ČÁSTEČNÁ ÚHRADA",),
        "UHRAZEN": ("UHRAZEN",),
        "Vše": (),
    }

    def __init__(self, container: ServiceContainer, registry: ObjectActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self.registry = registry
        self.current_contexts: list[ObjectContext] = []
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Párování úhrad")
        title.setObjectName("screenTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.summary = QLabel("Bez výběru")
        header.addWidget(self.summary)
        root.addLayout(header)
        self.status_tabs = QTabBar()
        bind_component(self.status_tabs, ComponentId.MATCH_STATUS_TABS)
        for label in self.STATUS_MAP:
            self.status_tabs.addTab(label)
        self.status_tabs.currentChanged.connect(lambda _: self.refresh())
        root.addWidget(self.status_tabs)
        filter_bar = QFrame()
        bind_component(filter_bar, ComponentId.MATCH_FILTER_BAR)
        filters = QHBoxLayout(filter_bar)
        filters.setContentsMargins(0, 0, 0, 0)
        self.currency = QComboBox()
        self.currency.addItems(["Všechny měny", "CZK", "EUR"])
        self.currency.currentIndexChanged.connect(lambda _: self.refresh())
        self.period = QComboBox()
        self.period.addItem("Celé období", 0)
        self.period.addItem("Posledních 7 dní", 7)
        self.period.addItem("Posledních 14 dní", 14)
        self.period.addItem("Posledních 30 dní", 30)
        self.period.currentIndexChanged.connect(lambda _: self.refresh())
        self.document_type = QComboBox()
        self.document_type.addItem("Všechny doklady", "ALL")
        self.document_type.addItem("Faktury", "INVOICE")
        self.document_type.addItem("Dobropisy", "CREDIT")
        self.document_type.currentIndexChanged.connect(lambda _: self.refresh_documents())
        self.age = QComboBox()
        self.age.addItem("Všechna stáří", "all")
        for key, label in (("0_2", "0–2 dny"), ("3_7", "3–7 dní"), ("8_30", "8–30 dní"), ("31_90", "31–90 dní"), ("90_plus", "90+ dní")):
            self.age.addItem(label, key)
        self.age.currentIndexChanged.connect(lambda _: self.refresh_groups())
        self.search = QLineEdit()
        self.search.setPlaceholderText("Hledat v párování…")
        self.search.textChanged.connect(lambda _: self.refresh())
        clear = QPushButton("Vymazat filtry")
        clear.clicked.connect(self.clear_filters)
        filters.addWidget(QLabel("Měna:"))
        filters.addWidget(self.currency)
        filters.addWidget(QLabel("Období:"))
        filters.addWidget(self.period)
        filters.addWidget(QLabel("Typ:"))
        filters.addWidget(self.document_type)
        filters.addWidget(QLabel("Stáří:"))
        filters.addWidget(self.age)
        filters.addWidget(self.search, 1)
        filters.addWidget(clear)
        root.addWidget(filter_bar)
        self.review_banner = QFrame()
        bind_component(self.review_banner, ComponentId.MATCH_REVIEW_BANNER)
        review_layout = QHBoxLayout(self.review_banner)
        self.review_text = QLabel()
        self.review_text.setWordWrap(True)
        self.review_text.setAccessibleName("Přesný seznam změn zdrojových dat")
        review_layout.addWidget(self.review_text, 1)
        self.review_revalidate = QPushButton("Znovu ověřit")
        self.review_reopen = QPushButton("Znovu otevřít")
        self.review_history = QPushButton("Historie")
        self.review_revalidate.clicked.connect(
            lambda: self._trigger_review_action(ActionId.REVALIDATE_GROUP)
        )
        self.review_reopen.clicked.connect(
            lambda: self._trigger_review_action(ActionId.REOPEN_MANUAL_RESOLUTION)
        )
        self.review_history.clicked.connect(
            lambda: self._trigger_review_action(ActionId.SHOW_AUDIT)
        )
        review_layout.addWidget(self.review_revalidate)
        review_layout.addWidget(self.review_reopen)
        review_layout.addWidget(self.review_history)
        self.review_banner.hide()
        root.addWidget(self.review_banner)
        self.context_bar = QFrame()
        bind_component(self.context_bar, ComponentId.MATCH_CONTEXT_BAR)
        self.context_layout = QHBoxLayout(self.context_bar)
        self.context_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.context_bar)
        splitter = QSplitter()
        splitter.setObjectName("matchingSplitter")
        self.documents = ObjectTableView(registry)
        bind_component(self.documents, ComponentId.MATCH_DOC_TABLE)
        bind_component(self.documents.inline_action, ComponentId.MATCH_DOC_ACTIONS)
        self.documents.setAccessibleName("Doklady k vyřešení")
        self.documents.setModel(ObjectTableModel(["Stav", "Doklad", "Datum", "Rezervace", "Měna", "Celkem", "Zbývá pokrýt"], ["status", "label", "date", "reservation", "currency", "amount", "remaining"]))
        self.documents.selectionContextsChanged.connect(self._selection_changed)
        self.documents.contextsDropped.connect(self._drop_on_table)
        self.documents.set_drop_preview_provider(self._drop_preview)
        splitter.addWidget(self.documents)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = GroupCanvas(container, registry)
        self.canvas.contextSelected.connect(self._set_contexts)
        self.canvas.contextsDropped.connect(self._drop_on_canvas)
        self.canvas.set_drop_preview_provider(self._canvas_drop_preview)
        self.canvas.allocationActivated.connect(lambda ctx: registry.handler(ActionId.EDIT_ALLOCATION, [ctx]))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.canvas)
        center_layout.addWidget(scroll, 2)
        self.groups_table = ObjectTableView(registry)
        bind_component(self.groups_table, ComponentId.MATCH_GROUP_CARD)
        self.groups_table.setAccessibleName("Číselný seznam vyrovnávacích skupin")
        self.groups_table.setModel(
            ObjectTableModel(
                ["Skupina", "Stav", "Měna", "Doklady", "Zdroje", "Rozdíl"],
                ["group", "status", "currency", "documents", "sources", "difference"],
            )
        )
        self.groups_table.selectionContextsChanged.connect(self._selection_changed)
        self.groups_table.contextsDropped.connect(self._drop_on_canvas_table)
        self.groups_table.set_drop_preview_provider(self._group_table_drop_preview)
        center_layout.addWidget(self.groups_table, 1)
        self.allocations = ObjectTableView(registry)
        bind_component(self.allocations, ComponentId.MATCH_CONNECTOR)
        self.allocations.setAccessibleName("Číselný ekvivalent vazeb")
        self.allocations.setModel(ObjectTableModel(["Skupina", "Doklad", "Zdroj", "Částka", "Metoda"], ["group", "invoice", "source", "amount", "method"]))
        self.allocations.selectionContextsChanged.connect(self._selection_changed)
        center_layout.addWidget(self.allocations, 1)
        splitter.addWidget(center)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.source_tabs = QTabBar()
        bind_component(self.source_tabs, ComponentId.MATCH_SOURCE_TABS)
        for label in ("Vše", "Booking.com", "Karty", "Ruční zdroje"):
            self.source_tabs.addTab(label)
        self.source_tabs.currentChanged.connect(lambda _: self.refresh_sources())
        right_layout.addWidget(self.source_tabs)
        self.sources = ObjectTableView(registry)
        bind_component(self.sources, ComponentId.MATCH_SOURCE_TABLE)
        self.sources.setAccessibleName("Zdroje úhrad")
        self.sources.setModel(ObjectTableModel(["Stav", "Typ", "Datum", "Reference", "Měna", "Částka", "Zbývá přiřadit"], ["status", "type", "date", "label", "currency", "amount", "remaining"]))
        self.sources.selectionContextsChanged.connect(self._selection_changed)
        self.sources.contextsDropped.connect(self._drop_on_table)
        self.sources.set_drop_preview_provider(self._drop_preview)
        right_layout.addWidget(self.sources)
        splitter.addWidget(right)
        splitter.setSizes([430, 650, 430])
        root.addWidget(splitter, 1)
        candidate_bar = QFrame()
        bind_component(candidate_bar, ComponentId.MATCH_CANDIDATE_PANEL)
        candidate_layout = QHBoxLayout(candidate_bar)
        self.candidate_summary = QLabel("Návrhy: vyberte doklad nebo zdroj a zvolte Najít možné protějšky.")
        self.candidate_summary.setWordWrap(True)
        bind_component(self.candidate_summary, ComponentId.MATCH_SCORE_DETAIL)
        candidate_layout.addWidget(self.candidate_summary, 1)
        find_button = QPushButton("Najít možné protějšky")
        find_button.clicked.connect(self._request_counterparts)
        candidate_layout.addWidget(find_button)
        self.date_window = QComboBox()
        self.date_window.addItem("7 dní", 7)
        self.date_window.addItem("14 dní", 14)
        self.date_window.addItem("30 dní", 30)
        self.date_window.addItem("Celé období", 0)
        bind_component(self.date_window, ComponentId.MATCH_DATE_WINDOW_CONTROL)
        candidate_layout.addWidget(self.date_window)
        expand_button = QPushButton("Rozšířit hledání")
        expand_button.clicked.connect(self._expand_counterparts_window)
        candidate_layout.addWidget(expand_button)
        root.addWidget(candidate_bar)
        self.manual_bar = QFrame()
        bind_component(self.manual_bar, ComponentId.MATCH_MANUAL_SETTLEMENT)
        manual_layout = QHBoxLayout(self.manual_bar)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        self.manual_buttons: dict[ActionId, QPushButton] = {}
        cash = QPushButton("Doplnit jako hotovost")
        cash.clicked.connect(lambda: self.registry.handler(ActionId.MARK_CASH, list(self.current_contexts)))
        other = QPushButton("Doplnit jiným zdrojem")
        other.clicked.connect(lambda: self.registry.handler(ActionId.MARK_OTHER, list(self.current_contexts)))
        resolve = QPushButton("Označit jako ručně vyřešené")
        resolve.clicked.connect(lambda: self.registry.handler(ActionId.MANUAL_RESOLVE, list(self.current_contexts)))
        aggregate = QPushButton("Vyrovnat skupinu jako celek")
        bind_component(aggregate, ComponentId.MATCH_AGGREGATE_RECONCILIATION)
        aggregate.clicked.connect(lambda: self.registry.handler(ActionId.BALANCE_AS_GROUP, list(self.current_contexts)))
        undo = QPushButton("Vrátit poslední změnu")
        bind_component(undo, ComponentId.MATCH_UNDO)
        undo.clicked.connect(lambda: self.registry.handler(ActionId.UNDO, list(self.current_contexts)))
        redo = QPushButton("Znovu provést")
        bind_component(redo, ComponentId.MATCH_REDO)
        redo.clicked.connect(lambda: self.registry.handler(ActionId.REDO, list(self.current_contexts)))
        self.manual_buttons = {
            ActionId.MARK_CASH: cash,
            ActionId.MARK_OTHER: other,
            ActionId.MANUAL_RESOLVE: resolve,
            ActionId.BALANCE_AS_GROUP: aggregate,
            ActionId.UNDO: undo,
            ActionId.REDO: redo,
        }
        for button in self.manual_buttons.values():
            manual_layout.addWidget(button)
        manual_layout.addStretch(1)
        root.addWidget(self.manual_bar)
        self.refresh()


    def _request_counterparts(self) -> None:
        days_value = int(self.date_window.currentData() or 0)
        self.counterpartsRequested.emit(list(self.current_contexts), None if days_value == 0 else days_value)

    def _expand_counterparts_window(self) -> None:
        current = int(self.date_window.currentData() or 0)
        progression = {7: 14, 14: 30, 30: 0, 0: 0}
        target = progression.get(current, 14)
        index = self.date_window.findData(target)
        if index >= 0:
            self.date_window.setCurrentIndex(index)
        self.counterpartsRequested.emit(list(self.current_contexts), None if target == 0 else target)

    def clear_filters(self) -> None:
        self.currency.setCurrentIndex(0)
        self.period.setCurrentIndex(0)
        self.document_type.setCurrentIndex(0)
        self.age.setCurrentIndex(0)
        self.search.clear()
        self.status_tabs.setCurrentIndex(0)
        self.refresh()

    def apply_filter(self, currency: str, status_hint: str) -> None:
        if currency in {"CZK", "EUR"}:
            self.currency.setCurrentText(currency)
        else:
            self.currency.setCurrentIndex(0)
        if status_hint.startswith("age:"):
            index = self.age.findData(status_hint.split(":", 1)[1])
            if index >= 0:
                self.age.setCurrentIndex(index)
            self.status_tabs.setCurrentIndex(list(self.STATUS_MAP).index("Nespárované"))
        elif status_hint in {"conflicts"}:
            self.status_tabs.setCurrentIndex(list(self.STATUS_MAP).index("Konflikty"))
        elif status_hint in {"matched"}:
            self.status_tabs.setCurrentIndex(list(self.STATUS_MAP).index("Spárované"))
        else:
            self.status_tabs.setCurrentIndex(list(self.STATUS_MAP).index("Nespárované"))
        self.refresh()

    def focus_object(self, context: ObjectContext) -> None:
        self.status_tabs.setCurrentIndex(list(self.STATUS_MAP).index("Vše"))
        self.search.setText(context.primary_label)
        self.refresh()

    def refresh(self) -> None:
        selected = {
            table: {context.object_ref for context in table.selected_contexts()}
            for table in (self.documents, self.sources, self.groups_table, self.allocations)
        }
        focused = next(
            (
                table
                for table in (self.documents, self.sources, self.groups_table, self.allocations)
                if table.hasFocus()
            ),
            None,
        )
        self.refresh_documents()
        self.refresh_sources()
        self.refresh_groups()
        for table, refs in selected.items():
            table.restore_selection(refs)
        if focused is not None:
            focused.setFocus(Qt.FocusReason.OtherFocusReason)

    def cancel_transient(self) -> None:
        """Cancel drag/preview state without committing a domain command and restore logical focus."""
        self.documents.cancel_drop_preview()
        self.sources.cancel_drop_preview()
        self.groups_table.cancel_drop_preview()
        self.canvas.cancel_drop_preview()
        focused = next(
            (
                table
                for table in (self.documents, self.sources, self.groups_table, self.allocations)
                if table.hasFocus()
            ),
            None,
        )
        if focused is None:
            focused = self.documents if self.documents.model().rowCount() else self.sources
        focused.setFocus(Qt.FocusReason.OtherFocusReason)

    def refresh_documents(self) -> None:
        status_label = self.status_tabs.tabText(self.status_tabs.currentIndex())
        statuses = self.STATUS_MAP[status_label]
        currency = self.currency.currentText()
        text = self.search.text().strip()
        clauses = ["i.included=1"]
        params: list[Any] = []
        status_expression = "CASE WHEN COALESCE((SELECT manual_paid FROM invoice_payment_status WHERE invoice_id=i.external_id),0)=1 OR ABS(COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.invoice_id=i.external_id AND a.active=1),0)) >= ABS(i.total_minor) THEN 'UHRAZEN' WHEN COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.invoice_id=i.external_id AND a.active=1),0)=0 THEN 'NEUHRAZEN' ELSE 'ČÁSTEČNÁ ÚHRADA' END"
        if statuses:
            clauses.append(status_expression + " IN (" + ",".join("?" for _ in statuses) + ")")
            params.extend(statuses)
        if currency != "Všechny měny":
            clauses.append("i.currency_code=?")
            params.append(currency)
        period_days = int(self.period.currentData() or 0)
        if period_days:
            clauses.append("julianday('now')-julianday(substr(i.document_date_utc,1,10))<=?")
            params.append(period_days)
        document_type = str(self.document_type.currentData())
        if document_type == "CREDIT":
            clauses.append("i.print_format=3")
        elif document_type == "INVOICE":
            clauses.append("COALESCE(i.print_format,0)<>3")
        if text:
            clauses.append("(i.code LIKE ? OR i.external_id LIKE ? OR r.internal_code LIKE ? OR r.booking_reference LIKE ?)")
            params.extend([f"%{text}%"] * 4)
        sql = "SELECT i.*,r.internal_code,r.booking_reference,COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.invoice_id=i.external_id AND a.active=1),0) AS used," + status_expression + " AS settlement_status FROM invoice i LEFT JOIN reservation_invoice_link l ON l.invoice_id=i.external_id LEFT JOIN reservation r ON r.uuid=l.reservation_id WHERE " + " AND ".join(clauses) + " GROUP BY i.external_id ORDER BY i.document_date_utc DESC LIMIT 2000"
        rows = []
        for row in self.container.database.query(sql, params):
            remaining = row["total_minor"] - row["used"]
            context = ObjectContext("INVOICE", row["external_id"], row["code"], row["currency_code"], remaining, row["row_version"], row["settlement_status"], "matching", {"included": bool(row["included"]), "total_minor": row["total_minor"], "remaining_minor": remaining, "raw_json": row["raw_json"]})
            paid_label = "Úhrada potvrzena" if row["paid_at_utc"] else "Karta uvedena, úhrada nepotvrzena" if row["pay_method"] == 2 else "Úhrada nepotvrzena"
            rows.append({"status": row["settlement_status"], "label": row["code"], "date": row["document_date_utc"][:10], "reservation": f"{row['internal_code'] or '—'} / {row['booking_reference'] or '—'}", "currency": row["currency_code"], "amount": Money(row["total_minor"], row["currency_code"]).format(), "remaining": Money(remaining, row["currency_code"]).format(), "_context": context, "_tooltip": f"{paid_label}\nTechnické ID: {row['external_id']}"})
        self.documents.model().set_rows(rows)

    def refresh_sources(self) -> None:
        source_filter = self.source_tabs.tabText(self.source_tabs.currentIndex())
        currency = self.currency.currentText()
        text = self.search.text().strip()
        rows: list[dict[str, Any]] = []
        if source_filter in {"Vše", "Booking.com"}:
            clauses = ["1=1"]
            params: list[Any] = []
            if currency != "Všechny měny":
                clauses.append("b.currency_code=?")
                params.append(currency)
            period_days = int(self.period.currentData() or 0)
            if period_days:
                clauses.append("julianday('now')-julianday(b.payout_date)<=?")
                params.append(period_days)
            if text:
                clauses.append("(b.booking_reference LIKE ? OR p.payment_id LIKE ?)")
                params.extend([f"%{text}%", f"%{text}%"])
            clauses.append("b.active_source=1")
            sql = "SELECT b.*,p.payment_id,COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='BOOKING' AND a.source_id=b.row_hash AND a.active=1),0) AS used FROM booking_payment_line b JOIN booking_payout_batch p ON p.id=b.batch_id WHERE " + " AND ".join(clauses) + " ORDER BY b.payout_date DESC LIMIT 2000"
            for row in self.container.database.query(sql, params):
                remaining = row["amount_minor"] - row["used"]
                context = ObjectContext("BOOKING", row["row_hash"], row["booking_reference"], row["currency_code"], remaining, row["row_version"], row["status"], "matching", {"payment_id": row["payment_id"], "remaining_minor": remaining, "raw_json": row["raw_json"]})
                rows.append({"status": row["status"], "type": "Booking.com", "date": row["payout_date"], "label": f"{row['booking_reference']}\nVýplata {row['payment_id']}", "currency": row["currency_code"], "amount": Money(row["amount_minor"], row["currency_code"]).format(), "remaining": Money(remaining, row["currency_code"]).format(), "_context": context})
        if source_filter in {"Vše", "Karty"}:
            clauses = ["1=1"]
            params = []
            if currency != "Všechny měny":
                clauses.append("c.currency_code=?")
                params.append(currency)
            period_days = int(self.period.currentData() or 0)
            if period_days:
                clauses.append("julianday('now')-julianday(substr(c.occurred_at,1,10))<=?")
                params.append(period_days)
            if text:
                clauses.append("(c.seq_id LIKE ? OR c.arn LIKE ? OR c.authorization_code LIKE ? OR c.masked_card LIKE ?)")
                params.extend([f"%{text}%"] * 4)
            sql = "SELECT c.*,COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='CARD' AND a.source_id=c.id AND a.active=1),0) AS used FROM card_transaction c WHERE " + " AND ".join(clauses) + " ORDER BY c.occurred_at DESC LIMIT 2000"
            for row in self.container.database.query(sql, params):
                remaining = row["amount_minor"] - row["used"]
                context = ObjectContext("CARD", row["id"], row["seq_id"], row["currency_code"], remaining, row["row_version"], row["status"], "matching", {"terminal_id": row["terminal_id"], "seq_id": row["seq_id"], "remaining_minor": remaining, "raw_json": row["raw_json"], "arn": row["arn"], "authorization_code": row["authorization_code"]})
                rows.append({"status": row["status"], "type": "Karta", "date": row["occurred_at"], "label": f"SEQ {row['seq_id']}\n{row['masked_card'] or '—'}", "currency": row["currency_code"], "amount": Money(row["amount_minor"], row["currency_code"]).format(), "remaining": Money(remaining, row["currency_code"]).format(), "_context": context, "_tooltip": f"ARN: {row['arn'] or '—'}\nAutorizační kód: {row['authorization_code'] or '—'}"})
        if source_filter in {"Vše", "Ruční zdroje"}:
            for row in self.container.database.query("SELECT * FROM manual_settlement WHERE active=1 ORDER BY created_at_utc DESC"):
                context = ObjectContext("MANUAL", row["id"], row["name"] or ("Hotovost" if row["type"] == "CASH" else "Jiný zdroj"), row["currency_code"], row["amount_minor"], row["row_version"], "MANUAL", "matching", {"group_id": row["group_id"], "note": row["note"], "type": row["type"]})
                rows.append({"status": "Ručně", "type": "Hotovost" if row["type"] == "CASH" else "Jiný", "date": row["created_at_utc"], "label": context.primary_label, "currency": row["currency_code"], "amount": Money(row["amount_minor"], row["currency_code"]).format(), "remaining": "ve skupině", "_context": context})
        if source_filter in {"Vše", "Karty"}:
            cashbook_rows = self.container.database.query(
                "SELECT * FROM cashbook_card_transaction ORDER BY occurred_at DESC LIMIT 2000"
            )
            for row in cashbook_rows:
                if currency in {"CZK", "EUR"} and row["currency_code"] != currency:
                    continue
                if text and not any(text.casefold() in str(row[key] or "").casefold() for key in ("receipt_number", "variable_symbol", "client")):
                    continue
                context = ObjectContext(
                    "CASHBOOK_CARD", row["id"], row["receipt_number"], row["currency_code"],
                    row["amount_minor"], row["row_version"], row["status"], "matching",
                    {"raw_json": row["raw_json"], "cashbook_identity": row["cashbook_identity"]},
                )
                rows.append({
                    "status": row["status"], "type": "Pokladna", "date": row["occurred_at"],
                    "label": f"{row['receipt_number']}\n{row['label']}",
                    "currency": row["currency_code"], "amount": Money(row["amount_minor"], row["currency_code"]).format(),
                    "remaining": Money(row["amount_minor"], row["currency_code"]).format(), "_context": context,
                })
        self.sources.model().set_rows(rows)

    def refresh_groups(self) -> None:
        groups: list[dict[str, Any]] = []
        group_rows: list[dict[str, Any]] = []
        allocations_rows: list[dict[str, Any]] = []
        clauses = ["status<>'REVERSED'"]
        params: list[Any] = []
        currency = self.currency.currentText()
        if currency != "Všechny měny":
            clauses.append("currency_code=?")
            params.append(currency)
        age_key = str(self.age.currentData() or "all")
        age_ranges = {"0_2": (0, 2), "3_7": (3, 7), "8_30": (8, 30), "31_90": (31, 90), "90_plus": (91, None)}
        if age_key in age_ranges:
            minimum, maximum = age_ranges[age_key]
            clauses.append("julianday('now')-julianday(substr(created_at_utc,1,10))>=?")
            params.append(minimum)
            if maximum is not None:
                clauses.append("julianday('now')-julianday(substr(created_at_utc,1,10))<=?")
                params.append(maximum)
        sql = "SELECT * FROM match_group WHERE " + " AND ".join(clauses) + " ORDER BY updated_at_utc DESC LIMIT 100"
        for group in self.container.database.query(sql, params):
            context = ObjectContext("MATCH_GROUP", group["id"], f"Skupina {group['id'][:8]}", group["currency_code"], group["difference_minor"], group["row_version"], group["status"], "matching", {"allocation_mode": group["allocation_mode"], "review_required_reason": group["review_required_reason"]})
            allocations: list[dict[str, Any]] = []
            for allocation in self.container.database.query("SELECT a.*,i.code FROM allocation a JOIN invoice i ON i.external_id=a.invoice_id WHERE a.group_id=? AND a.active=1 ORDER BY a.created_at_utc", (group["id"],)):
                source_label = self._source_label(allocation["source_type"], allocation["source_id"])
                acontext = ObjectContext("ALLOCATION", allocation["id"], f"{allocation['code']} ↔ {source_label}", group["currency_code"], allocation["amount_minor"], allocation["row_version"], "ACTIVE", "matching", {"group_id": group["id"], "invoice_id": allocation["invoice_id"], "source_type": allocation["source_type"], "source_id": allocation["source_id"], "tooltip": f"{Money(allocation['amount_minor'], group['currency_code']).format()} ze zdroje {source_label} je přiřazeno k dokladu {allocation['code']}"})
                item = {"invoice_label": allocation["code"], "source_label": source_label, "amount": Money(allocation["amount_minor"], group["currency_code"]).format(), "_context": acontext}
                allocations.append(item)
                allocations_rows.append({"group": group["id"][:8], "invoice": allocation["code"], "source": source_label, "amount": item["amount"], "method": allocation["method"], "_context": acontext})
            document_total = Money(group["document_total_minor"], group["currency_code"]).format()
            source_total = Money(group["source_total_minor"], group["currency_code"]).format()
            difference = Money(group["difference_minor"], group["currency_code"]).format()
            groups.append({"id": group["id"], "status": group["status"], "currency": group["currency_code"], "document_total": document_total, "source_total": source_total, "difference": difference, "allocation_mode": group["allocation_mode"], "allocations": allocations, "_context": context})
            group_rows.append(
                {
                    "group": f"Skupina {group['id'][:8]}",
                    "status": group["status"],
                    "currency": group["currency_code"],
                    "documents": document_total,
                    "sources": source_total,
                    "difference": difference,
                    "_context": context,
                    "_tooltip": (
                        "Skupinově vyrovnáno bez jednotlivých vazeb."
                        if group["allocation_mode"] == "AGGREGATE"
                        else f"Detailních vazeb: {len(allocations)}"
                    ),
                }
            )
        self.canvas.set_groups(groups)
        self.groups_table.model().set_rows(group_rows)
        self.allocations.model().set_rows(allocations_rows)

    def _source_label(self, source_type: str, source_id: str) -> str:
        if source_type == "BOOKING":
            row = self.container.database.query("SELECT booking_reference FROM booking_payment_line WHERE row_hash=?", (source_id,))
            return f"Booking {row[0][0]}" if row else source_id[:12]
        if source_type == "CARD":
            row = self.container.database.query("SELECT seq_id FROM card_transaction WHERE id=?", (source_id,))
            return f"SEQ {row[0][0]}" if row else source_id[:12]
        row = self.container.database.query("SELECT name,type FROM manual_settlement WHERE id=?", (source_id,))
        return (row[0]["name"] or row[0]["type"]) if row else source_id[:12]

    def _selection_changed(self, contexts: list[ObjectContext]) -> None:
        sender = self.sender()
        selected: list[ObjectContext] = []
        for table in (self.documents, self.sources, self.groups_table, self.allocations):
            if table is sender:
                selected.extend(contexts)
            else:
                selected.extend(table.selected_contexts())
        self._set_contexts(selected)

    def _set_contexts(self, contexts: list[ObjectContext]) -> None:
        self.current_contexts = contexts
        currencies = sorted({context.currency for context in contexts if context.currency})
        totals = {currency: sum(context.amount_minor or 0 for context in contexts if context.currency == currency) for currency in currencies}
        self.summary.setText(f"Vybráno {len(contexts)} • " + " • ".join(f"{Money(total, currency).format()}" for currency, total in totals.items()))
        review_contexts = [context for context in contexts if context.status == "REVIEW_REQUIRED"]
        if review_contexts:
            context = review_contexts[0]
            changed = self._review_details(context.object_id)
            self.review_text.setText(
                "⚠ Vyžaduje kontrolu. Změněná pole: "
                + changed
                + ". Původní rozhodnutí a vazby zůstaly zachovány, ale případ není aktuálně ověřený."
            )
            for button, action_id in (
                (self.review_revalidate, ActionId.REVALIDATE_GROUP),
                (self.review_reopen, ActionId.REOPEN_MANUAL_RESOLUTION),
                (self.review_history, ActionId.SHOW_AUDIT),
            ):
                enabled, reason = self.registry.availability(action_id, [context])
                button.setEnabled(enabled)
                button.setToolTip(reason or self.registry.specs[action_id].tooltip)
            self.review_banner.show()
        else:
            self.review_banner.hide()
        self._update_candidate_summary(contexts)
        for action_id, button in self.manual_buttons.items():
            enabled, reason = self.registry.availability(action_id, contexts)
            button.setEnabled(enabled)
            button.setToolTip(reason or self.registry.specs[action_id].tooltip)
        self.contextsChanged.emit(contexts)
        while self.context_layout.count():
            item = self.context_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for action_id in (ActionId.OPEN_DETAIL, ActionId.ADD_TO_TRAY, ActionId.PAIR_SELECTED, ActionId.BALANCE_AS_GROUP, ActionId.MARK_CASH, ActionId.MANUAL_RESOLVE, ActionId.REVALIDATE_GROUP):
            action = self.registry.create_action(self, action_id, contexts)
            button = QPushButton(action.text())
            button.setEnabled(action.isEnabled())
            button.setToolTip(action.toolTip())
            button.clicked.connect(action.trigger)
            self.context_layout.addWidget(button)
        self.context_layout.addStretch(1)

    def _review_details(self, group_id: str) -> str:
        rows = self.container.database.query(
            "SELECT changed_fields_json,object_ref,previous_hash,current_hash "
            "FROM source_revision_alert WHERE affected_group_ids_json LIKE ? AND state='OPEN' "
            "ORDER BY detected_at_utc",
            (f"%{group_id}%",),
        )
        details: list[str] = []
        for row in rows:
            try:
                changed = json.loads(row["changed_fields_json"] or "[]")
            except (TypeError, ValueError):
                changed = []
            if isinstance(changed, dict):
                fields = sorted(str(key) for key in changed)
            elif isinstance(changed, list):
                fields = sorted(str(value) for value in changed)
            else:
                fields = [str(changed)] if changed else []
            object_ref = str(row["object_ref"] or "zdroj")
            if fields:
                details.append(f"{object_ref}: {', '.join(fields)}")
            else:
                details.append(f"{object_ref}: obsah zdrojového záznamu")
        if details:
            return "; ".join(details)
        contexts = [context for context in self.current_contexts if context.object_id == group_id]
        fallback = contexts[0].data.get("review_required_reason") if contexts else None
        return str(fallback or "částka, měna, stav, archivace nebo identita zdroje")

    def _trigger_review_action(self, action_id: ActionId) -> None:
        contexts = [
            context
            for context in self.current_contexts
            if context.object_type == "MATCH_GROUP" and context.status == "REVIEW_REQUIRED"
        ]
        if contexts:
            self.registry.handler(action_id, contexts[:1])

    def _source_ref_from_drop(
        self,
        entity_type: str,
        entity_id: str,
        row_version: int | None,
        data: dict[str, Any] | None = None,
    ) -> SourceRef:
        if entity_type != "MANUAL":
            return SourceRef(SourceType(entity_type), entity_id, row_version)
        manual_type = (data or {}).get("type")
        if not manual_type:
            rows = self.container.database.query("SELECT type FROM manual_settlement WHERE id=?", (entity_id,))
            if not rows:
                raise PairingError("Ruční zdroj nebyl nalezen.")
            manual_type = rows[0]["type"]
        return SourceRef(SourceType(str(manual_type)), entity_id, row_version)

    def _decode_drop(
        self, payload: dict[str, Any], target: ObjectContext | None
    ) -> tuple[list[DocumentRef], list[SourceRef]]:
        if target is None:
            raise PairingError("Uvolněte položky na konkrétním dokladu nebo zdroji úhrady.")
        refs = payload.get("entity_refs") or []
        if not refs:
            raise PairingError("Přetažený výběr je prázdný.")
        dragged_types = {str(ref.get("entity_type")) for ref in refs}
        source_types = {"BOOKING", "CARD", "MANUAL"}
        if target.object_type in source_types and dragged_types == {"INVOICE"}:
            documents = [
                DocumentRef(str(ref.get("entity_id")), ref.get("row_version")) for ref in refs
            ]
            source = self._source_ref_from_drop(
                target.object_type, target.object_id, target.row_version, target.data
            )
            return documents, [source]
        if target.object_type == "INVOICE" and dragged_types.issubset(source_types):
            document = DocumentRef(target.object_id, target.row_version)
            sources = [
                self._source_ref_from_drop(
                    str(ref.get("entity_type")),
                    str(ref.get("entity_id")),
                    ref.get("row_version"),
                )
                for ref in refs
            ]
            return [document], sources
        raise PairingError("Nelze spojit: vyberte doklad a zdroj úhrady na opačných stranách.")

    def _refs_from_payload(self, payload: dict[str, Any]) -> tuple[list[DocumentRef], list[SourceRef]]:
        documents: list[DocumentRef] = []
        sources: list[SourceRef] = []
        for ref in payload.get("entity_refs") or []:
            entity_type = str(ref.get("entity_type"))
            entity_id = str(ref.get("entity_id"))
            row_version = ref.get("row_version")
            if entity_type == "INVOICE":
                documents.append(DocumentRef(entity_id, row_version))
            elif entity_type in {"BOOKING", "CARD", "MANUAL"}:
                sources.append(self._source_ref_from_drop(entity_type, entity_id, row_version))
        return documents, sources

    def _canvas_drop_preview(self, payload: dict[str, Any], target: ObjectContext | None) -> tuple[str, str]:
        try:
            documents, sources = self._refs_from_payload(payload)
            if target is None:
                if not documents or not sources:
                    return "blocked", "Prázdné plátno vytvoří skupinu pouze ze smíšeného výběru dokladů a zdrojů."
                preview = self.container.drop_validation.preview_many(documents, sources)
                if not preview.allowed:
                    return "blocked", preview.reason
                amount = Money(preview.assign_minor, preview.currency or "CZK").format()
                return ("allowed" if preview.exact else "partial", f"Vytvořit novou skupinu z {len(documents)} dokladů a {len(sources)} zdrojů • {amount}.")
            if target.object_type != "MATCH_GROUP":
                return "blocked", "Cílem musí být vyrovnávací skupina nebo prázdné plátno."
            if not documents and not sources:
                return "blocked", "Přetažený výběr neobsahuje podporované položky."
            if target.status == "REVIEW_REQUIRED":
                return "conflict", "Skupina vyžaduje kontrolu změněných zdrojových dat; nejprve ji znovu ověřte."
            if target.data.get("allocation_mode") == "AGGREGATE":
                return "blocked", "Skupinově vyrovnaný případ je nutné nejprve znovu otevřít; nevytváříme falešné párové vazby."
            return "allowed", f"Přidat {len(documents) + len(sources)} položek do {target.primary_label} a před uložením ukázat navržený rozpis."
        except (PairingError, ValueError) as exc:
            return "blocked", str(exc)

    def _group_table_drop_preview(
        self, payload: dict[str, Any], target: ObjectContext | None
    ) -> tuple[str, str]:
        if target is None:
            return "blocked", "Uvolněte položky na konkrétní vyrovnávací skupině."
        return self._canvas_drop_preview(payload, target)

    def _drop_on_canvas_table(
        self, payload: dict[str, Any], target: ObjectContext | None
    ) -> None:
        if target is None:
            self.toast.emit("Uvolněte položky na konkrétní vyrovnávací skupině.")
            return
        self._drop_on_canvas(payload, target)

    def _drop_on_canvas(self, payload: dict[str, Any], target: ObjectContext | None) -> None:
        try:
            documents, sources = self._refs_from_payload(payload)
            state, message = self._canvas_drop_preview(payload, target)
            if state in {"blocked", "conflict"}:
                self.toast.emit(message)
                return
            if target is None:
                plan = self.container.pairing.propose_allocations(documents, sources)
            else:
                plan = self.container.pairing.propose_group_additions(
                    target.object_id, documents, sources
                )
            currency = self._selection_currency(documents, sources, target)
            confirmation = (
                message
                + "\n\n"
                + format_allocation_plan(plan, currency)
                + "\n\nZkontrolujte rozpis. Změna bude auditovaná a vratná pomocí Ctrl+Z."
            )
            if QMessageBox.question(self, "Potvrdit drop", confirmation) != QMessageBox.StandardButton.Yes:
                return
            if target is None:
                self.container.pairing.pair(
                    documents,
                    sources,
                    allocations=plan,
                    human_label="Vytvoření skupiny dropem na plátno",
                )
            else:
                self.container.pairing.add_to_group(
                    target.object_id, documents, sources, allocations=plan
                )
            self.toast.emit("Drop byl uložen jako doménový command. Změnu lze vrátit pomocí Ctrl+Z.")
            self.refresh()
        except (PairingError, ValueError) as exc:
            QMessageBox.warning(self, "Párování nelze provést", str(exc))

    def _update_candidate_summary(self, contexts: list[ObjectContext]) -> None:
        if not contexts:
            self.candidate_summary.setText("Návrhy: vyberte doklad nebo zdroj a zvolte Najít možné protějšky.")
            return
        identifiers = [context.object_id for context in contexts]
        clauses = ["(document_ids_json LIKE ? OR source_refs_json LIKE ?)"] * len(identifiers)
        params: list[str] = []
        for identifier in identifiers:
            params.extend([f"%{identifier}%", f"%{identifier}%"])
        rows = self.container.database.query(
            "SELECT score,margin,evidence_json,alternatives_json,status FROM auto_match_candidate WHERE "
            + " OR ".join(clauses)
            + " ORDER BY score DESC,margin DESC LIMIT 1",
            params,
        ) if identifiers else []
        if not rows:
            self.candidate_summary.setText("Pro výběr není uložený návrh. Použijte Najít možné protějšky a zvolte rozsah 7/14/30 dní nebo celé období.")
            return
        row = rows[0]
        self.candidate_summary.setText(f"Nejlepší návrh: score {row['score']}, margin {row['margin']}, stav {row['status']}. Důkazy: {row['evidence_json']}")

    def _drop_on_table(self, payload: dict[str, Any], target: ObjectContext | None) -> None:
        try:
            documents, sources = self._decode_drop(payload, target)
            preview = self.container.drop_validation.preview_many(documents, sources)
            if not preview.allowed:
                self.toast.emit(preview.reason)
                return
            if preview.partial and (len(documents) > 1 or len(sources) > 1):
                self.toast.emit(
                    "Částečný vícepoložkový výběr vyžaduje kontrolu rozpisu; "
                    "použijte pracovní výběr a akci Spárovat vybrané."
                )
                return
            if len(documents) == 1 and len(sources) == 1:
                amount = preview.assign_minor
                if preview.partial:
                    currency = preview.currency or "CZK"
                    suggested = f"{Money(amount, currency).decimal:.2f}".replace(".", ",")
                    value, accepted = QInputDialog.getText(
                        self,
                        "Přiřadit část",
                        "Zadejte částku v měně dokladu.\n"
                        f"Doklad zbývá: {Money(preview.document_remaining_minor, currency).format()}\n"
                        f"Zdroj zbývá: {Money(preview.source_remaining_minor, currency).format()}",
                        QLineEdit.EchoMode.Normal,
                        suggested,
                    )
                    if not accepted:
                        return
                    amount = Money.parse(value, currency).amount_minor
                self.container.pairing.pair_one(documents[0], sources[0], amount)
            else:
                plan = self.container.pairing.propose_allocations(documents, sources)
                currency = preview.currency or "CZK"
                if QMessageBox.question(
                    self,
                    "Potvrdit detailní rozpis",
                    format_allocation_plan(plan, currency)
                    + "\n\nTento konkrétní rozpis bude uložen jako auditovaná ruční vazba.",
                ) != QMessageBox.StandardButton.Yes:
                    return
                self.container.pairing.pair(
                    documents,
                    sources,
                    allocations=plan,
                    human_label="Vícepoložkové párování přetažením",
                )
            self.toast.emit("Položky byly spárovány. Akci lze vrátit pomocí Ctrl+Z.")
            self.refresh()
        except (PairingError, ValueError) as exc:
            QMessageBox.warning(self, "Párování nelze provést", str(exc))

    def _selection_currency(
        self,
        documents: list[DocumentRef],
        sources: list[SourceRef],
        target: ObjectContext | None,
    ) -> str:
        if target is not None and target.currency:
            return target.currency
        if documents:
            rows = self.container.database.query(
                "SELECT currency_code FROM invoice WHERE external_id=?", (documents[0].invoice_id,)
            )
            if rows:
                return str(rows[0]["currency_code"])
        if sources:
            ref = sources[0]
            table, key = (
                ("booking_payment_line", "row_hash")
                if ref.source_type == SourceType.BOOKING
                else ("card_transaction", "id")
            )
            if ref.source_type in {SourceType.BOOKING, SourceType.CARD}:
                rows = self.container.database.query(
                    f"SELECT currency_code FROM {table} WHERE {key}=?", (ref.source_id,)
                )
            else:
                rows = self.container.database.query(
                    "SELECT currency_code FROM manual_settlement WHERE id=?", (ref.source_id,)
                )
            if rows:
                return str(rows[0]["currency_code"])
        return "CZK"

    def _drop_preview(self, payload: dict[str, Any], target: ObjectContext | None) -> tuple[str, str]:
        try:
            documents, sources = self._decode_drop(payload, target)
            preview = self.container.drop_validation.preview_many(documents, sources)
            if not preview.allowed:
                return "blocked", preview.reason
            currency = preview.currency or ""
            amount = Money(preview.assign_minor, currency).format() if currency else str(preview.assign_minor)
            if preview.partial:
                if len(documents) > 1 or len(sources) > 1:
                    return (
                        "blocked",
                        "Částečný vícepoložkový výběr vyžaduje kontrolu rozpisu v pracovním výběru.",
                    )
                return "partial", f"Přiřadit část {amount} – po uvolnění zvolíte přesnou částku."
            item_count = len(documents) + len(sources)
            if item_count > 2:
                return "allowed", f"Spárovat {item_count} položky – přesná souhrnná shoda {amount}."
            return "allowed", f"Spárovat – přesná shoda {amount}. Rozdíl po přiřazení bude 0."
        except (PairingError, ValueError) as exc:
            return "blocked", str(exc)
