from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QByteArray, QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..app.container import ServiceContainer
from ..domain.enums import SourceType
from ..domain.money import Money
from ..infrastructure.better_hotel.client import BetterHotelClient, Tokens
from ..infrastructure.importers.common import utc_now
from .action_registry import ActionId, ObjectActionRegistry, ObjectContext
from .allocation_plan import format_allocation_plan
from .counterparts_dialog import CounterpartsDialog
from .component_registry import ComponentId, bind_component
from .money_dialog import MoneyAmountDialog
from .operation_progress import OperationProgressDialog
from .document_payment_dialog import DocumentPaymentDialog
from .tray import WorkingTrayList
from .theme import HIGH_CONTRAST_THEME, NORMAL_THEME, build_palette, build_stylesheet
from .screens.audit import AuditScreen
from .screens.dashboard import DashboardScreen
from .screens.imports import ImportsScreen
from .screens.matching import MatchingScreen
from .screens.reports import ReportsScreen
from .screens.search import SearchScreen
from .screens.settings import SettingsScreen
from ..application.pairing import DocumentRef, PairingError, SourceRef


_PAGE_ORDER = (
    ("dashboard", "Dashboard"),
    ("matching", "Párování"),
    ("search", "Vyhledávání"),
    ("imports", "Importy a synchronizace"),
    ("reports", "Sestavy"),
    ("audit", "Auditní historie"),
    ("settings", "Nastavení"),
)


class MainWindow(QMainWindow):
    """Primary window; every live view uses one central ObjectActionRegistry."""

    def __init__(self, container: ServiceContainer) -> None:
        super().__init__()
        application = QApplication.instance()
        if application is not None and application.style().objectName().casefold() != "fusion":
            application.setStyle("Fusion")
        if application is not None:
            application.setFont(QFont("Arial", 10))
        self.container = container
        self.registry = ObjectActionRegistry(self.handle_action, self._action_label)
        self.pages: dict[str, QWidget] = {}
        self.current_contexts: list[ObjectContext] = []
        self.tray_contexts: dict[str, ObjectContext] = {}
        self._finished_operations_seen: set[str] = set()
        self._progress_dialogs: dict[str, OperationProgressDialog] = {}
        self.setWindowTitle("KájovoKarty")
        bind_component(self, ComponentId.APP_WINDOW)
        self.setMinimumSize(1280, 720)
        self.resize(1480, 920)
        self.setAccessibleName("KájovoKarty – kontrola úhrad hotelu")
        self._build_ui()
        self._build_shortcuts()
        self._load_tray()
        self._restore_window_state()
        self.refresh_all()
        self.operation_poll = QTimer(self)
        self.operation_poll.setInterval(500)
        self.operation_poll.timeout.connect(self._refresh_operations)
        self.operation_poll.start()
        QTimer.singleShot(0, self._offer_interrupted_recovery)
        if bool(self.container.settings.get("backup.daily")):
            QTimer.singleShot(1000, self._daily_backup)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QWidget()
        top.setObjectName("topBar")
        top_layout = QHBoxLayout(top)
        brand = QLabel("KájovoKarty")
        brand.setObjectName("brand")
        top_layout.addWidget(brand)
        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("Hledat doklad, Booking.com, SEQ ID, ARN, částku…")
        self.global_search.setClearButtonEnabled(True)
        self.global_search.returnPressed.connect(self._global_search)
        bind_component(self.global_search, ComponentId.TOP_GLOBAL_SEARCH)
        top_layout.addWidget(self.global_search, 1)
        self.source_status = QPushButton("Stav zdrojů")
        bind_component(self.source_status, ComponentId.TOP_SOURCE_STATUS)
        self.source_status.setToolTip("Otevře Importy a synchronizaci s přehledem posledních zdrojových běhů.")
        self.source_status.clicked.connect(lambda: self.navigate("imports"))
        top_layout.addWidget(self.source_status)
        self.last_run = QPushButton("Poslední běh")
        bind_component(self.last_run, ComponentId.TOP_LAST_RUN)
        self.last_run.setToolTip("Dosud nebyl dokončen žádný běh.")
        self.last_run.clicked.connect(self._open_last_run)
        self._last_operation_id: str | None = None
        top_layout.addWidget(self.last_run)
        operations = QPushButton("Centrum operací")
        bind_component(operations, ComponentId.TOP_OPERATION_CENTER)
        operations.clicked.connect(lambda: self.operations_dock.setVisible(not self.operations_dock.isVisible()))
        top_layout.addWidget(operations)
        run_all = QPushButton("Aktualizovat a spárovat")
        bind_component(run_all, ComponentId.TOP_RUN_ALL)
        run_all.setProperty("primary", True)
        run_all.setShortcut(QKeySequence("Ctrl+R"))
        run_all.clicked.connect(lambda: self.imports.run_full())
        top_layout.addWidget(run_all)
        root.addWidget(top)

        self.main_splitter = QSplitter()
        self.main_splitter.setObjectName("mainSplitter")
        splitter = self.main_splitter
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setFixedWidth(210)
        self.navigation.setAccessibleName("Hlavní navigace")
        nav_ids = {
            "dashboard": ComponentId.NAV_DASH,
            "matching": ComponentId.NAV_MATCH,
            "search": ComponentId.NAV_SEARCH,
            "imports": ComponentId.NAV_IMPORT,
            "reports": ComponentId.NAV_REPORT,
            "audit": ComponentId.NAV_AUDIT,
            "settings": ComponentId.NAV_SETTINGS,
        }
        for key, label in _PAGE_ORDER:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setData(Qt.ItemDataRole.UserRole + 1, nav_ids[key].value)
            item.setToolTip(f"{label} – aktivovat klávesou Enter")
            self.navigation.addItem(item)
        self.navigation.currentItemChanged.connect(self._navigation_changed)
        splitter.addWidget(self.navigation)

        self.stack = QStackedWidget()
        self.dashboard = DashboardScreen(self.container, self.registry)
        self.matching = MatchingScreen(self.container, self.registry)
        self.search = SearchScreen(self.container, self.registry)
        self.imports = ImportsScreen(self.container, self.registry)
        self.reports = ReportsScreen(self.container, self.registry)
        self.audit = AuditScreen(self.container, self.registry)
        self.settings = SettingsScreen(self.container)
        screen_objects = (self.dashboard, self.matching, self.search, self.imports, self.reports, self.audit, self.settings)
        for (key, _), screen in zip(_PAGE_ORDER, screen_objects, strict=True):
            self.pages[key] = screen
            self.stack.addWidget(screen)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self.tray = QWidget()
        bind_component(self.tray, ComponentId.GLOBAL_SELECTION_TRAY)
        tray_layout = QHBoxLayout(self.tray)
        self.tray_summary = QLabel("Pracovní výběr je prázdný")
        self.tray_summary.setWordWrap(True)
        tray_layout.addWidget(self.tray_summary)
        self.tray_list = WorkingTrayList()
        self.tray_list.contextsChanged.connect(self._set_contexts)
        tray_layout.addWidget(self.tray_list, 1)
        open_matching = QPushButton("Otevřít v párování")
        open_matching.clicked.connect(self._open_tray_matching)
        pair = QPushButton("Spárovat vybrané")
        pair.clicked.connect(lambda: self.handle_action(ActionId.PAIR_SELECTED, list(self.tray_contexts.values())))
        clear = QPushButton("Vyprázdnit")
        clear.clicked.connect(lambda: self.handle_action(ActionId.CLEAR_TRAY, []))
        tray_layout.addWidget(open_matching)
        tray_layout.addWidget(pair)
        tray_layout.addWidget(clear)
        root.addWidget(self.tray)
        self.setCentralWidget(central)

        self.detail_dock = QDockWidget("Detail a historie", self)
        bind_component(self.detail_dock, ComponentId.MATCH_DETAIL_DRAWER)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setAccessibleName("Detail aktuálního objektu")
        self.detail_dock.setWidget(self.detail_text)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.detail_dock)
        self.detail_dock.hide()

        self.operations_dock = QDockWidget("Centrum operací", self)
        self.operations_dock.setObjectName("operationsDock")
        op_widget = QWidget()
        op_layout = QVBoxLayout(op_widget)
        self.operations_table = QTableWidget(0, 6)
        self.operations_table.setHorizontalHeaderLabels(["Operace", "Stav", "Krok", "Průběh", "Heartbeat", "Zpráva"])
        self.operations_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        op_layout.addWidget(self.operations_table)
        cancel = QPushButton("Bezpečně zrušit vybranou operaci")
        cancel.clicked.connect(self._cancel_selected_operation)
        op_layout.addWidget(cancel)
        self.operations_dock.setWidget(op_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.operations_dock)
        self.operations_dock.hide()

        self.focus_help = QLabel()
        bind_component(self.focus_help, ComponentId.GLOBAL_TOOLTIP)
        self.focus_help.setWordWrap(True)
        self.focus_help.setMaximumWidth(520)
        self.statusBar().addPermanentWidget(self.focus_help, 1)
        self.toast_label = QLabel()
        bind_component(self.toast_label, ComponentId.GLOBAL_TOAST)
        self.toast_label.setWordWrap(True)
        self.toast_label.setMaximumWidth(520)
        self.statusBar().addWidget(self.toast_label, 1)
        QApplication.instance().focusChanged.connect(self._focus_help_changed)

        for screen in (self.matching, self.search, self.imports, self.reports, self.audit):
            screen.contextsChanged.connect(self._set_contexts)
        self.dashboard.openMatching.connect(self._dashboard_drilldown)
        self.dashboard.documentActivated.connect(lambda context: self._show_detail([context]))
        self.dashboard.autoMatchRequested.connect(self._run_payment_matching)
        self.dashboard.openImportRun.connect(self._open_import_run)
        self.matching.toast.connect(self._toast)
        self.matching.counterpartsRequested.connect(lambda contexts, days: self._find_counterparts(list(contexts), initial_days=days))
        self.imports.dataChanged.connect(self.refresh_all)
        self.imports.openSettings.connect(lambda: self.navigate("settings"))
        self.imports.operationStarted.connect(self._show_progress_dialog)
        self.reports.operationStarted.connect(self._show_progress_dialog)
        self.settings.settingsChanged.connect(self._apply_ui_settings)
        self.audit.openCurrent.connect(self._open_object_ref)
        self._apply_ui_settings()

    def _build_shortcuts(self) -> None:
        shortcuts = {
            "Ctrl+F": lambda: self.global_search.setFocus(),
            "Ctrl+Z": lambda: self.handle_action(ActionId.UNDO, self.current_contexts),
            "Ctrl+Y": lambda: self.handle_action(ActionId.REDO, self.current_contexts),
            "Delete": self._delete_current,
            "F2": self._edit_current,
            "Escape": self._escape,
        }
        for sequence, callback in shortcuts.items():
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def navigate(self, key: str) -> None:
        for row in range(self.navigation.count()):
            item = self.navigation.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                self.navigation.setCurrentRow(row)
                return

    def refresh_all(self) -> None:
        self.dashboard.refresh()
        self.matching.refresh()
        self.reports.refresh()
        self.audit.refresh()
        self.imports.refresh_runs()
        self.container.search.rebuild_index()
        self._refresh_source_status()

    def handle_action(self, action_id: ActionId, contexts: list[ObjectContext]) -> None:
        try:
            self._handle_action(action_id, contexts)
        except Exception as exc:
            box = QMessageBox(
                QMessageBox.Icon.Warning,
                "Akci nelze provést",
                str(exc),
                parent=self,
            )
            bind_component(box, ComponentId.GLOBAL_ERROR_DIALOG)
            box.exec()

    def _handle_action(self, action_id: ActionId, contexts: list[ObjectContext]) -> None:
        if action_id == ActionId.OPEN_DETAIL:
            self._show_detail(contexts)
        elif action_id == ActionId.OPEN_IN_MATCHING:
            self.navigate("matching")
            if contexts:
                self.matching.focus_object(contexts[0])
        elif action_id == ActionId.ADD_TO_TRAY:
            for context in contexts:
                if context.object_type in {"INVOICE", "BOOKING", "CARD", "CASHBOOK_CARD", "MANUAL"}:
                    self.tray_contexts[context.object_ref] = context
            self._update_tray()
        elif action_id == ActionId.REMOVE_FROM_TRAY:
            for context in contexts:
                self.tray_contexts.pop(context.object_ref, None)
            self._update_tray()
        elif action_id == ActionId.CLEAR_TRAY:
            self.tray_contexts.clear()
            self._update_tray()
        elif action_id in {ActionId.PAIR_SELECTED, ActionId.CREATE_GROUP, ActionId.BALANCE_AS_GROUP}:
            self._pair_contexts(contexts or list(self.tray_contexts.values()), aggregate=action_id == ActionId.BALANCE_AS_GROUP)
        elif action_id in {ActionId.SPLIT_DOCUMENT, ActionId.SPLIT_SOURCE}:
            for context in contexts:
                self.tray_contexts[context.object_ref] = context
            self._update_tray()
            self.navigate("matching")
            if contexts:
                self.matching.focus_object(contexts[0])
            self.statusBar().showMessage("Položka je v pracovním výběru. Přidejte protějšky a zvolte Spárovat vybrané.", 8000)
        elif action_id == ActionId.FIND_COUNTERPARTS:
            self._find_counterparts(contexts)
        elif action_id == ActionId.EDIT_ALLOCATION:
            self._edit_allocation(contexts)
        elif action_id == ActionId.REMOVE_ALLOCATION:
            self._remove_allocation(contexts)
        elif action_id == ActionId.REMOVE_GROUP:
            self._remove_groups(contexts)
        elif action_id == ActionId.ACCEPT_CANDIDATE:
            for context in contexts:
                if context.object_type == "BOOKING_REFERENCE":
                    self.container.reference_resolution.confirm(context.object_id)
                else:
                    self.container.reconciliation.accept_candidate(context.object_id)
            self.refresh_all()
        elif action_id == ActionId.REJECT_CANDIDATE:
            for context in contexts:
                if context.object_type == "BOOKING_REFERENCE":
                    self.container.reference_resolution.reject(context.object_id)
                else:
                    self.container.reconciliation.reject_candidate(context.object_id, uuid4().hex)
            self.refresh_all()
        elif action_id in {ActionId.MARK_CASH, ActionId.MARK_OTHER}:
            self._add_manual_source(contexts, SourceType.CASH if action_id == ActionId.MARK_CASH else SourceType.OTHER)
        elif action_id == ActionId.MANUAL_RESOLVE:
            self._manual_resolve(contexts)
        elif action_id == ActionId.MARK_DOCUMENT_PAID:
            for context in contexts:
                self.container.payments.mark_manual_paid(context.object_id)
            self.refresh_all()
        elif action_id == ActionId.CLEAR_DOCUMENT_MANUAL_PAID:
            for context in contexts:
                self.container.payments.clear_manual_paid(context.object_id)
            self.refresh_all()
        elif action_id in {ActionId.INCLUDE, ActionId.EXCLUDE}:
            included = action_id == ActionId.INCLUDE
            for context in contexts:
                self.container.pairing.include_invoice(context.object_id, included)
            self.refresh_all()
        elif action_id == ActionId.SHOW_RELATIONS:
            if contexts:
                if contexts[0].object_type == "AUDIT" and contexts[0].data.get("object_ref"):
                    self._open_object_ref(str(contexts[0].data["object_ref"]))
                else:
                    self.navigate("search")
                    self.search.input.setText(contexts[0].primary_label)
                    self.search.search_now()
        elif action_id == ActionId.SHOW_AUDIT:
            if contexts:
                object_ref = str(contexts[0].data.get("object_ref", contexts[0].object_ref))
                self.navigate("audit")
                self.audit.focus_object(object_ref)
        elif action_id == ActionId.SHOW_SOURCE_ROW:
            self._show_source(contexts)
        elif action_id == ActionId.COPY_PRIMARY_ID:
            QApplication.clipboard().setText("\n".join(context.primary_label for context in contexts))
        elif action_id == ActionId.COPY_ALL_IDS:
            QApplication.clipboard().setText("\n\n".join(self._context_identifiers(context) for context in contexts))
        elif action_id == ActionId.EXPORT_SELECTION:
            self._export_contexts(contexts)
        elif action_id == ActionId.UNDO:
            self._undo(contexts)
        elif action_id == ActionId.REDO:
            self._redo()
        elif action_id == ActionId.RETRY_RUN:
            self.navigate("imports")
            if contexts:
                if not self.imports.focus_run(contexts[0].object_id):
                    raise ValueError("Importní běh už nebyl nalezen.")
            self.imports.retry_selected()
        elif action_id == ActionId.OPEN_QUARANTINE:
            self.navigate("imports")
            self.imports.show_quarantine()
        elif action_id == ActionId.RESOLVE_QUARANTINE:
            self._resolve_quarantine(contexts)
        elif action_id == ActionId.REFRESH_OBJECT:
            self._refresh_object(contexts)
        elif action_id == ActionId.EXPAND_SEARCH_WINDOW:
            self._expand_search_window(contexts)
        elif action_id == ActionId.REVALIDATE_GROUP:
            for context in contexts:
                for group_id in self._group_ids_for_context(context):
                    self.container.pairing.revalidate_group(group_id)
            self.refresh_all()
        elif action_id == ActionId.EDIT_MANUAL_SETTLEMENT:
            self._edit_manual(contexts)
        elif action_id == ActionId.REMOVE_MANUAL_SETTLEMENT:
            for context in contexts:
                self.container.pairing.remove_manual_settlement(context.object_id)
            self.refresh_all()
        elif action_id == ActionId.REOPEN_MANUAL_RESOLUTION:
            for context in contexts:
                for group_id in self._group_ids_for_context(context):
                    status_rows = self.container.database.query(
                        "SELECT status FROM match_group WHERE id=?", (group_id,)
                    )
                    if status_rows and status_rows[0]["status"] == "REVIEW_REQUIRED":
                        self.container.pairing.reopen_review_required(group_id)
                    else:
                        self.container.pairing.reopen_manual_resolution(group_id)
            self.refresh_all()
        else:
            raise ValueError(f"Akce {action_id.value} není dostupná v tomto kontextu.")

    def _pair_contexts(self, contexts: list[ObjectContext], *, aggregate: bool) -> None:
        documents = [self._document_ref(context) for context in contexts if context.object_type == "INVOICE"]
        sources = [self._source_ref(context) for context in contexts if context.object_type in {"BOOKING", "CARD", "CASHBOOK_CARD", "MANUAL"}]
        if not documents and sources:
            self.container.pairing.pair_sources(sources)
            self.refresh_all()
            return
        if not documents or not sources:
            raise PairingError("Vyberte alespoň jeden doklad a jeden zdroj úhrady.")
        currencies = {context.currency for context in contexts if context.currency}
        if len(currencies) != 1:
            raise PairingError("Položky nelze spárovat, protože používají různé měny.")
        currency = next(iter(currencies))
        doc_total = sum(context.amount_minor or 0 for context in contexts if context.object_type == "INVOICE")
        source_total = sum(context.amount_minor or 0 for context in contexts if context.object_type != "INVOICE")
        mode = "skupinově bez fiktivního rozpisu" if aggregate else "s detailním rozpisem"
        plan = [] if aggregate else self.container.pairing.propose_allocations(documents, sources)
        if not aggregate:
            planned: dict[str, int] = {}
            for invoice_id, _source, amount_minor in plan:
                planned[invoice_id] = planned.get(invoice_id, 0) + int(amount_minor)
            incomplete = [ref.external_id for ref in documents if planned.get(ref.external_id, 0) != abs(self._invoice_remaining(ref.external_id))]
            if incomplete:
                raise PairingError("Ruční částečná úhrada dokladu není dovolena. Vyberte potvrzení nebo kombinaci potvrzení, která pokryje celý zbývající doklad.")
        plan_text = (
            "Přesný rozpis mezi položkami nebude vytvořen."
            if aggregate
            else format_allocation_plan(plan, currency)
        )
        answer = QMessageBox.question(
            self,
            "Potvrdit párování",
            f"Doklady: {Money(doc_total, currency).format()}\n"
            f"Zdroje: {Money(source_total, currency).format()}\n"
            f"Rozdíl: {Money(doc_total-source_total, currency).format()}\n"
            f"Režim: {mode}\n\n{plan_text}\n\n"
            "Uložit tuto reverzibilní změnu?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.container.pairing.pair(
            documents,
            sources,
            allocations=None if aggregate else plan,
            aggregate=aggregate,
        )
        self.tray_contexts.clear()
        self._update_tray()
        self.refresh_all()
        self._toast("Párování bylo uloženo a je dostupné v auditní historii. Ctrl+Z změnu vrátí.")

    def _add_manual_source(self, contexts: list[ObjectContext], source_type: SourceType) -> None:
        for context in contexts:
            if context.object_type == "INVOICE":
                group_id, _ = self.container.pairing.create_invoice_case(context.object_id)
                amount = context.amount_minor or self._invoice_remaining(context.object_id)
            elif context.object_type == "MATCH_GROUP":
                group_id = context.object_id
                amount = self._group_difference(group_id)
            else:
                continue
            if amount == 0:
                raise PairingError("Případ nemá žádný zbývající rozdíl.")
            amount, accepted = MoneyAmountDialog.get_amount(
                title="Doplnit jako hotovost" if source_type == SourceType.CASH else "Doplnit jiným zdrojem",
                currency=context.currency or "CZK",
                initial_minor=int(amount),
                explanation="Částka je předvyplněná aktuálním rozdílem. Můžete ji upravit; změna bude auditovaná a vratná.",
                parent=self,
            )
            if not accepted:
                return
            name = None
            note = None
            if source_type == SourceType.OTHER:
                name, accepted = QInputDialog.getText(self, "Jiný zdroj", "Lidský název zdroje:")
                if not accepted or not name.strip():
                    return
            note, accepted = QInputDialog.getText(self, "Poznámka", "Volitelná auditní poznámka:")
            if not accepted:
                return
            self.container.pairing.add_manual_settlement(group_id, source_type, amount, name=name or None, note=note or None)
        self.refresh_all()

    def _manual_resolve(self, contexts: list[ObjectContext]) -> None:
        for context in contexts:
            group_id = context.object_id
            if context.object_type == "INVOICE":
                group_id, _ = self.container.pairing.create_invoice_case(context.object_id)
            self.container.pairing.manual_resolve(group_id)
        self.refresh_all()

    def _edit_allocation(self, contexts: list[ObjectContext]) -> None:
        if not contexts:
            return
        context = contexts[0]
        currency = context.currency or "CZK"
        amount, accepted = MoneyAmountDialog.get_amount(
            title="Upravit přiřazenou částku",
            currency=currency,
            initial_minor=int(context.amount_minor or 0),
            explanation="Zadejte částku v běžném formátu měny. Program ji uloží přesně v minor units bez použití float.",
            parent=self,
        )
        if accepted:
            self.container.pairing.edit_allocation(context.object_id, amount, expected_row_version=context.row_version)
            self.refresh_all()

    def _remove_allocation(self, contexts: list[ObjectContext]) -> None:
        for context in contexts:
            self.container.pairing.remove_allocation(context.object_id)
        self.refresh_all()

    def _remove_groups(self, contexts: list[ObjectContext]) -> None:
        if QMessageBox.question(self, "Rozpojit skupinu", f"Rozpojit {len(contexts)} vybraných skupin? Akci lze vrátit.") != QMessageBox.StandardButton.Yes:
            return
        for context in contexts:
            self.container.pairing.remove_group(context.object_id)
        self.refresh_all()

    def _edit_manual(self, contexts: list[ObjectContext]) -> None:
        if not contexts:
            return
        context = contexts[0]
        row = self.container.database.query("SELECT * FROM manual_settlement WHERE id=?", (context.object_id,))
        if not row:
            raise PairingError("Ruční zdroj neexistuje.")
        current = row[0]
        amount, accepted = MoneyAmountDialog.get_amount(
            title="Upravit ruční zdroj",
            currency=str(current["currency_code"]),
            initial_minor=int(current["amount_minor"]),
            explanation="Zadejte částku v měně zdroje. Změna je auditovaná a vratná.",
            parent=self,
        )
        if not accepted:
            return
        name, accepted = QInputDialog.getText(self, "Upravit ruční zdroj", "Název:", text=current["name"] or "")
        if not accepted:
            return
        note, accepted = QInputDialog.getText(self, "Upravit ruční zdroj", "Poznámka:", text=current["note"] or "")
        if accepted:
            self.container.pairing.edit_manual_settlement(context.object_id, amount, name=name or None, note=note or None)
            self.refresh_all()

    def _action_label(self, action_id: ActionId, default: str) -> str:
        if action_id == ActionId.UNDO:
            rows = self.container.database.query(
                "SELECT human_label FROM action_command WHERE reversible=1 AND state='APPLIED' "
                "AND command_type NOT IN ('UNDO','REDO') ORDER BY applied_at_utc DESC LIMIT 1"
            )
            return f"Vrátit: {rows[0]['human_label']}" if rows else "Vrátit: není dostupná změna"
        if action_id == ActionId.REDO:
            rows = self.container.database.query(
                "SELECT human_label FROM action_command WHERE reversible=1 AND state='REVERSED' "
                "ORDER BY reversed_at_utc DESC LIMIT 1"
            )
            return f"Znovu: {rows[0]['human_label']}" if rows else "Znovu: není dostupná změna"
        return default

    def _undo(self, contexts: list[ObjectContext]) -> None:
        command_id = ""
        command_type = ""
        if contexts and contexts[0].object_type == "AUDIT":
            command_id = str(contexts[0].data.get("command_id") or "")
        if not command_id:
            row = self.container.database.query("SELECT command_id,command_type FROM action_command WHERE reversible=1 AND state='APPLIED' AND command_type NOT IN ('UNDO','REDO') ORDER BY applied_at_utc DESC LIMIT 1")
            if row:
                command_id = str(row[0]["command_id"])
                command_type = str(row[0]["command_type"])
        elif command_id:
            row = self.container.database.query("SELECT command_type FROM action_command WHERE command_id=?", (command_id,))
            command_type = str(row[0]["command_type"]) if row else ""
        if not command_id:
            raise PairingError("Není dostupná žádná bezpečně vratná změna.")
        if command_type in {"QUARANTINE_MAP", "QUARANTINE_IGNORE"}:
            self.container.quarantine.undo(command_id)
        elif command_type in {"BOOKING_REFERENCE_CONFIRM", "BOOKING_REFERENCE_REJECT"}:
            self.container.reference_resolution.undo(command_id)
        else:
            self.container.pairing.undo(command_id)
        self.refresh_all()

    def _redo(self) -> None:
        row = self.container.database.query("SELECT command_id,command_type FROM action_command WHERE reversible=1 AND state='REVERSED' ORDER BY reversed_at_utc DESC LIMIT 1")
        if not row:
            raise PairingError("Není dostupná žádná změna pro opakování.")
        command_type = str(row[0]["command_type"])
        command_id = str(row[0]["command_id"])
        if command_type in {"QUARANTINE_MAP", "QUARANTINE_IGNORE"}:
            self.container.quarantine.redo(command_id)
        elif command_type in {"BOOKING_REFERENCE_CONFIRM", "BOOKING_REFERENCE_REJECT"}:
            self.container.reference_resolution.redo(command_id)
        else:
            self.container.pairing.redo(command_id)
        self.refresh_all()

    def _resolve_quarantine(self, contexts: list[ObjectContext]) -> None:
        for context in contexts:
            choice, accepted = QInputDialog.getItem(
                self,
                "Vyřešit karanténní řádek",
                "Zvolte rozhodnutí:",
                ["Namapovat hodnotu a znovu zpracovat", "Zkusit znovu", "Vědomě ignorovat"],
                0,
                False,
            )
            if not accepted:
                return
            if choice.startswith("Namapovat"):
                fields = self.container.quarantine.available_fields(context.object_id)
                if not fields:
                    raise PairingError("Tento typ karanténního řádku nemá mapovatelnou hodnotu.")
                labels = list(fields.values())
                label, accepted = QInputDialog.getItem(self, "Namapovat hodnotu", "Pole:", labels, 0, False)
                if not accepted:
                    return
                field_name = next(key for key, value in fields.items() if value == label)
                meanings = list(self.container.quarantine.available_meanings(context.object_id, field_name))
                meaning, accepted = QInputDialog.getItem(self, "Namapovat hodnotu", "Význam:", meanings, 0, False)
                if not accepted:
                    return
                self.container.quarantine.map_value(context.object_id, field_name, meaning)
                self.container.quarantine.retry(context.object_id)
            elif choice.startswith("Zkusit"):
                self.container.quarantine.retry(context.object_id)
            else:
                note, accepted = QInputDialog.getText(self, "Vědomě ignorovat", "Volitelná poznámka:")
                if not accepted:
                    return
                self.container.quarantine.ignore(context.object_id, note or None)
        self.refresh_all()

    def _refresh_object(self, contexts: list[ObjectContext]) -> None:
        tokens = self.container.secrets.load_tokens()
        if not tokens.complete:
            self.navigate("settings")
            raise ValueError("Nejprve zadejte Better Hotel tokeny v Nastavení.")
        if not contexts:
            return
        context = contexts[0]
        refresh_type = context.object_type
        refresh_id = context.object_id
        if context.object_type == "BOOKING_REFERENCE":
            row = self.container.database.query(
                "SELECT reservation_id FROM booking_reference_extraction WHERE id=?",
                (context.object_id,),
            )
            if not row:
                raise ValueError("Booking reference nebyla nalezena.")
            refresh_type = "RESERVATION"
            refresh_id = str(row[0]["reservation_id"])
        settings = self.container.settings.all()

        def task(operation: Any) -> None:
            with BetterHotelClient(
                Tokens(tokens.access_token, tokens.client_token),
                timeout_seconds=int(settings["sync.timeout_seconds"]),
                retries=int(settings["sync.retry_count"]),
                requests_per_second=float(settings["sync.requests_per_second"]),
            ) as api:
                self.container.better_hotel_sync.refresh_object(
                    api,
                    object_type=refresh_type,
                    object_id=refresh_id,
                    progress=lambda current, total, message: operation.progress(current, total, message, "Better Hotel"),
                    cancel=operation.is_cancelled,
                    correlation_id=operation.correlation_id,
                )

        operation_id = self.container.operations.submit("REFRESH_OBJECT", task, exclusive_sources=True)
        self._show_progress_dialog(operation_id)
        self.operations_dock.show()

    def _find_counterparts(self, contexts: list[ObjectContext], *, initial_days: int | None = 7) -> None:
        if len(contexts) != 1:
            raise PairingError("Vyberte právě jeden doklad nebo zdroj úhrady.")
        dialog = CounterpartsDialog(
            self.container,
            self.registry,
            contexts[0],
            initial_days=initial_days,
            parent=self,
        )
        dialog.exec()

    def _expand_search_window(self, contexts: list[ObjectContext]) -> None:
        choice, accepted = QInputDialog.getItem(self, "Rozšířit hledání v čase", "Rozsah:", ["14 dní", "30 dní", "Celé období"], 0, False)
        if not accepted:
            return
        days: int | None = 14 if choice.startswith("14") else 30 if choice.startswith("30") else None
        self._find_counterparts(contexts, initial_days=days)

    def _show_detail(self, contexts: list[ObjectContext]) -> None:
        if not contexts:
            return
        if len(contexts) == 1 and contexts[0].object_type == "INVOICE":
            dialog = DocumentPaymentDialog(self.container.database, self.container.payments, contexts[0].object_id, self)
            dialog.changed.connect(self.refresh_all)
            dialog.exec()
            return
        blocks: list[str] = []
        for context in contexts:
            data = self._object_data(context)
            if context.object_type == "INVOICE":
                data["stav_uhrady"] = self._document_payment_status(context.object_id)
                data["potvrzeni_uhrady"] = self._invoice_payment_confirmations(context.object_id)
                data["volne_potvrzeni_booking"] = self._free_payment_confirmations("BOOKING")
                data["volne_potvrzeni_terminal"] = self._free_payment_confirmations("CARD")
            audits = [dict(row) for row in self.container.database.query("SELECT created_at_utc,operation_label,event_code,command_id,correlation_id FROM audit_event WHERE object_ref=? ORDER BY created_at_utc DESC LIMIT 50", (context.object_ref,))]
            related = [asdict(result) for result in self.container.search.related(context.object_ref)]
            blocks.append(json.dumps({"objekt": context.object_ref, "lidský_název": context.primary_label, "data": data, "související": related, "audit": audits}, ensure_ascii=False, indent=2, default=str))
        self.detail_text.setPlainText("\n\n".join(blocks))
        self.detail_dock.show()
        self.detail_dock.raise_()

    def _document_payment_status(self, invoice_id: str) -> str:
        row = self.container.database.query(
            "SELECT i.total_minor,COALESCE(s.manual_paid,0) AS manual_paid,COALESCE(SUM(a.amount_minor),0) AS used "
            "FROM invoice i LEFT JOIN invoice_payment_status s ON s.invoice_id=i.external_id LEFT JOIN allocation a ON a.invoice_id=i.external_id AND a.active=1 "
            "WHERE i.external_id=? GROUP BY i.external_id,s.manual_paid",
            (invoice_id,),
        )
        if not row:
            return "NEUHRAZEN"
        value = row[0]
        if value["manual_paid"] or abs(int(value["used"])) >= abs(int(value["total_minor"])):
            return "UHRAZEN"
        return "NEUHRAZEN" if int(value["used"]) == 0 else "ČÁSTEČNÁ ÚHRADA"

    def _invoice_payment_confirmations(self, invoice_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        allocations = self.container.database.query(
            "SELECT a.id,a.source_type,a.source_id,a.amount_minor,a.method,a.created_at_utc FROM allocation a WHERE a.invoice_id=? AND a.active=1 ORDER BY a.created_at_utc,a.id",
            (invoice_id,),
        )
        for allocation in allocations:
            source: dict[str, Any] = {}
            source_table = {"BOOKING": ("booking_payment_line", "row_hash"), "CARD": ("card_transaction", "id")}.get(str(allocation["source_type"]))
            if source_table:
                rows = self.container.database.query(f"SELECT * FROM {source_table[0]} WHERE {source_table[1]}=?", (allocation["source_id"],))
                source = dict(rows[0]) if rows else {}
            elif allocation["source_type"] in {"CASH", "OTHER"}:
                rows = self.container.database.query("SELECT * FROM manual_settlement WHERE id=?", (allocation["source_id"],))
                source = dict(rows[0]) if rows else {}
            shared = [dict(row) for row in self.container.database.query(
                "SELECT a.invoice_id,i.code,a.amount_minor FROM allocation a JOIN invoice i ON i.external_id=a.invoice_id WHERE a.source_type=? AND a.source_id=? AND a.active=1 AND a.invoice_id<>? ORDER BY i.code",
                (allocation["source_type"], allocation["source_id"], invoice_id),
            )]
            source_remaining = self.container.database.query(
                "SELECT COALESCE((SELECT amount_minor FROM booking_payment_line WHERE row_hash=?),(SELECT amount_minor FROM card_transaction WHERE id=?),0)-COALESCE((SELECT SUM(amount_minor) FROM allocation WHERE source_type=? AND source_id=? AND active=1),0)",
                (allocation["source_id"], allocation["source_id"], allocation["source_type"], allocation["source_id"]),
            )[0][0]
            result.append({"source_type": allocation["source_type"], "source_id": allocation["source_id"], "allocated_minor": allocation["amount_minor"], "source_remaining_minor": source_remaining, "method": allocation["method"], "created_at_utc": allocation["created_at_utc"], "source": source, "spoluhrazené_doklady": shared})
        return result

    def _free_payment_confirmations(self, source_type: str) -> list[dict[str, Any]]:
        if source_type == "BOOKING":
            rows = self.container.database.query(
                "SELECT b.*,b.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='BOOKING' AND a.source_id=b.row_hash AND a.active=1),0) AS remaining_minor FROM booking_payment_line b WHERE b.active_source=1 AND b.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='BOOKING' AND a.source_id=b.row_hash AND a.active=1),0)<>0 ORDER BY b.payout_date,b.row_hash"
            )
        else:
            rows = self.container.database.query(
                "SELECT c.*,c.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='CARD' AND a.source_id=c.id AND a.active=1),0) AS remaining_minor FROM card_transaction c WHERE c.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='CARD' AND a.source_id=c.id AND a.active=1),0)<>0 ORDER BY c.occurred_at,c.id"
            )
        return [dict(row) for row in rows]

    def _show_source(self, contexts: list[ObjectContext]) -> None:
        if not contexts:
            return
        context = contexts[0]
        data = self._object_data(context)
        raw = data.get("raw_json") or data.get("raw_snapshot_json") or data.get("canonical_row_json") or data
        try:
            text = json.dumps(json.loads(raw) if isinstance(raw, str) else raw, ensure_ascii=False, indent=2, default=str)
        except (ValueError, TypeError, json.JSONDecodeError):
            text = str(raw)
        self.detail_text.setPlainText("Zdrojový snapshot – může obsahovat osobní údaje.\n\n" + text)
        self.detail_dock.show()

    def _export_contexts(self, contexts: list[ObjectContext]) -> None:
        if not contexts:
            raise ValueError("Vyberte alespoň jednu položku.")
        configured = str(self.container.settings.get("data.export_directory") or "").strip()
        export_root = Path(configured).expanduser() if configured else self.container.paths.exports
        path, _ = QFileDialog.getSaveFileName(self, "Exportovat vybrané", str(export_root / "vybrane-polozky.csv"), "CSV (*.csv)")
        if not path:
            return
        with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Typ", "ID", "Název", "Měna", "Částka minor", "Stav", "Identifikátory"])
            for context in contexts:
                writer.writerow([context.object_type, context.object_id, context.primary_label, context.currency or "", context.amount_minor if context.amount_minor is not None else "", context.status or "", self._context_identifiers(context)])
        self.statusBar().showMessage(f"Export uložen: {path}", 8000)

    def _object_data(self, context: ObjectContext) -> dict[str, Any]:
        table_keys = {
            "INVOICE": ("invoice", "external_id"),
            "BOOKING": ("booking_payment_line", "row_hash"),
            "CARD": ("card_transaction", "id"),
            "MATCH_GROUP": ("match_group", "id"),
            "ALLOCATION": ("allocation", "id"),
            "RESERVATION": ("reservation", "uuid"),
            "IMPORT_RUN": (None, None),
            "QUARANTINE": ("quarantined_source_row", "id"),
            "CANDIDATE": ("auto_match_candidate", "id"),
            "MANUAL": ("manual_settlement", "id"),
            "AUDIT": ("audit_event", "event_id"),
            "BOOKING_REFERENCE": ("booking_reference_extraction", "id"),
            "BILL": ("bill", "external_id"),
            "BILL_ITEM": ("bill_item", "external_id"),
            "REVISION_ALERT": ("source_revision_alert", "id"),
        }
        table, key = table_keys.get(context.object_type, (None, None))
        if context.object_type == "IMPORT_RUN":
            for candidate in ("api_sync_run", "booking_import_run", "bank_import_run"):
                row = self.container.database.query(f"SELECT * FROM {candidate} WHERE id=?", (context.object_id,))
                if row:
                    return dict(row[0])
            return dict(context.data)
        if table is None or key is None:
            return dict(context.data)
        if context.object_type == "BOOKING_REFERENCE":
            row = self.container.database.query(
                "SELECT e.*,s.raw_channel,s.redacted_preview,s.content_hash AS snapshot_hash "
                "FROM booking_reference_extraction e JOIN reservation_note_snapshot s ON s.id=e.snapshot_id "
                "WHERE e.id=?",
                (context.object_id,),
            )
        else:
            row = self.container.database.query(f"SELECT * FROM {table} WHERE {key}=?", (context.object_id,))
        if not row and context.object_type == "BOOKING":
            row = self.container.database.query("SELECT * FROM booking_payment_line WHERE booking_reference=?", (context.object_id,))
        if not row and context.object_type == "CARD":
            row = self.container.database.query("SELECT * FROM card_transaction WHERE seq_id=?", (context.object_id,))
        return dict(row[0]) if row else dict(context.data)

    def _document_ref(self, context: ObjectContext) -> DocumentRef:
        return DocumentRef(context.object_id, context.row_version)

    def _source_ref(self, context: ObjectContext) -> SourceRef:
        if context.object_type == "BOOKING":
            row = self.container.database.query("SELECT row_hash FROM booking_payment_line WHERE row_hash=? OR booking_reference=? ORDER BY row_hash LIMIT 1", (context.object_id, context.object_id))
            if not row:
                raise PairingError("Booking.com zdroj nebyl nalezen.")
            return SourceRef(SourceType.BOOKING, str(row[0][0]), context.row_version)
        if context.object_type == "CARD":
            row = self.container.database.query("SELECT id FROM card_transaction WHERE id=? OR seq_id=? ORDER BY id LIMIT 1", (context.object_id, context.object_id))
            if not row:
                raise PairingError("Karetní transakce nebyla nalezena.")
            return SourceRef(SourceType.CARD, str(row[0][0]), context.row_version)
        if context.object_type == "CASHBOOK_CARD":
            row = self.container.database.query("SELECT id FROM cashbook_card_transaction WHERE id=? OR cashbook_identity=? ORDER BY id LIMIT 1", (context.object_id, context.object_id))
            if not row:
                raise PairingError("Cashbook source nebyl nalezen.")
            return SourceRef(SourceType.CASHBOOK_CARD, str(row[0][0]), context.row_version)
        row = self.container.database.query("SELECT type FROM manual_settlement WHERE id=?", (context.object_id,))
        if not row:
            raise PairingError("Ruční zdroj nebyl nalezen.")
        return SourceRef(SourceType(str(row[0][0])), context.object_id, context.row_version)

    def _group_ids_for_context(self, context: ObjectContext) -> list[str]:
        if context.object_type == "MATCH_GROUP":
            return [context.object_id]
        if context.object_type != "REVISION_ALERT":
            raise PairingError("Akce vyžaduje vyrovnávací skupinu nebo upozornění na změnu zdroje.")
        rows = self.container.database.query(
            "SELECT affected_group_ids_json FROM source_revision_alert WHERE id=?",
            (context.object_id,),
        )
        if not rows:
            raise PairingError("Upozornění na změnu zdroje nebylo nalezeno.")
        try:
            values = json.loads(rows[0]["affected_group_ids_json"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PairingError("Upozornění neobsahuje platný seznam dotčených skupin.") from exc
        group_ids = [str(value) for value in values if str(value)] if isinstance(values, list) else []
        if not group_ids:
            raise PairingError("Upozornění nemá žádnou dotčenou skupinu.")
        return group_ids

    def _context_identifiers(self, context: ObjectContext) -> str:
        technical = context.data.get("technical_ids")
        values = [context.object_ref]
        if technical:
            values.append(str(technical))
        for key in ("seq_id", "arn", "authorization_code", "payment_id", "group_id", "command_id", "correlation_id"):
            if context.data.get(key):
                values.append(f"{key}={context.data[key]}")
        return " | ".join(values)

    def _set_contexts(self, contexts: list[ObjectContext]) -> None:
        self.current_contexts = contexts
        if contexts:
            self.statusBar().showMessage(f"Vybráno: {len(contexts)} položek", 3000)

    def _navigation_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        key = str(current.data(Qt.ItemDataRole.UserRole))
        self.stack.setCurrentWidget(self.pages[key])
        self.container.settings.save({"ui.last_view": key})
        if hasattr(self.pages[key], "refresh"):
            getattr(self.pages[key], "refresh")()

    def _global_search(self) -> None:
        text = self.global_search.text().strip()
        if not text:
            return
        self.navigate("search")
        self.search.input.setText(text)
        self.search.search_now()

    def _dashboard_drilldown(self, currency: str, status: str) -> None:
        self.navigate("matching")
        self.matching.apply_filter(currency, status)

    def _run_payment_matching(self) -> None:
        def task(operation: Any) -> None:
            result = self.container.payments.auto_match(
                cancel=operation.is_cancelled,
                progress=lambda current, total, message: operation.progress(current, total, message, "Párování úhrad"),
            )
            operation.progress(1, 1, f"Dokončeno: {result.matched} plných, {result.partial} částečných úhrad; {result.alerts} upozornění")

        operation_id = self.container.operations.submit("PAYMENT_MATCHING", task, exclusive_sources=True)
        self._show_progress_dialog(operation_id)

    def _open_import_run(self, source: str, run_id: str) -> None:
        self.navigate("imports")
        if run_id:
            self.imports.focus_run(run_id)
        else:
            self.statusBar().showMessage(
                f"{source} zatím nemá žádný běh. Spusťte načtení v Importech.",
                6000,
            )

    def _open_last_run(self) -> None:
        self.operations_dock.show()
        self.operations_dock.raise_()
        if not self._last_operation_id:
            self.statusBar().showMessage("Dosud nebyl dokončen žádný běh.", 5000)
            return
        for row in range(self.operations_table.rowCount()):
            item = self.operations_table.item(row, 0)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == self._last_operation_id:
                self.operations_table.selectRow(row)
                self.operations_table.scrollToItem(item)
                return

    def _open_object_ref(self, object_ref: str) -> None:
        object_type, _, object_id = object_ref.partition(":")
        context = ObjectContext(object_type, object_id, object_ref, view="audit")
        self._show_detail([context])

    def _open_tray_matching(self) -> None:
        self.navigate("matching")
        if self.tray_contexts:
            self.matching.focus_object(next(iter(self.tray_contexts.values())))

    def _update_tray(self) -> None:
        by_currency: dict[str, int] = {}
        for context in self.tray_contexts.values():
            if context.currency:
                by_currency[context.currency] = by_currency.get(context.currency, 0) + int(context.amount_minor or 0)
        totals = " • ".join(Money(value, currency).format() for currency, value in sorted(by_currency.items()))
        self.tray_summary.setText(f"Pracovní výběr: {len(self.tray_contexts)} položek" + (f" • {totals}" if totals else ""))
        self.tray_list.set_contexts(list(self.tray_contexts.values()))
        self._save_tray()

    def _save_tray(self) -> None:
        state = [asdict(context) for context in self.tray_contexts.values()]
        self.container.view_state.save("working_tray", state)

    def _load_tray(self) -> None:
        values = self.container.view_state.load("working_tray", [])
        try:
            for value in values if isinstance(values, list) else []:
                context = ObjectContext(**value)
                self.tray_contexts[context.object_ref] = context
        except (TypeError, ValueError):
            self.tray_contexts.clear()
        self._update_tray()

    def _refresh_source_status(self) -> None:
        rows = self.container.database.query("SELECT 'Better Hotel' source,MAX(finished_at_utc) last FROM api_sync_run WHERE state='SUCCEEDED' UNION ALL SELECT 'Booking.com',MAX(finished_at_utc) FROM booking_import_run WHERE state='SUCCEEDED' UNION ALL SELECT 'Banka',MAX(finished_at_utc) FROM bank_import_run WHERE state='SUCCEEDED'")
        source_detail = "\n".join(f"{row['source']}: {row['last'] or 'nenačteno'}" for row in rows)
        loaded = sum(1 for row in rows if row["last"])
        self.source_status.setText(f"Stav zdrojů {loaded}/3")
        self.source_status.setToolTip(source_detail + "\n\nKliknutím otevřete Importy a synchronizaci.")
        last = self.container.database.query("SELECT id,operation_type,state,finished_at_utc,message FROM operation_run WHERE finished_at_utc IS NOT NULL ORDER BY finished_at_utc DESC LIMIT 1")
        if last:
            row = last[0]
            self._last_operation_id = str(row["id"])
            self.last_run.setText(f"Poslední běh: {row['state']}")
            self.last_run.setToolTip(
                f"{row['operation_type']} • {row['finished_at_utc']}\n"
                f"{row['message'] or ''}\n\n"
                "Kliknutím otevřete detail v Centru operací."
            )
        else:
            self._last_operation_id = None
            self.last_run.setText("Poslední běh: žádný")
            self.last_run.setToolTip("Dosud nebyl dokončen žádný běh.")

    def _refresh_operations(self) -> None:
        snapshots = sorted(self.container.operations.snapshots(), key=lambda item: item.heartbeat_utc, reverse=True)
        newly_finished = [
            snapshot
            for snapshot in snapshots
            if snapshot.state.value in {"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED", "DISCARDED"}
            and snapshot.id not in self._finished_operations_seen
        ]
        self._finished_operations_seen.update(snapshot.id for snapshot in newly_finished)
        self.operations_table.setRowCount(len(snapshots))
        for row, snapshot in enumerate(snapshots):
            progress = "—" if snapshot.total in (None, 0) else f"{snapshot.current or 0}/{snapshot.total}"
            values = (snapshot.operation_type, snapshot.state.value, snapshot.step, progress, snapshot.heartbeat_utc, snapshot.message)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, snapshot.id)
                item.setToolTip(str(value))
                self.operations_table.setItem(row, column, item)
        self.operations_table.resizeColumnsToContents()
        if any(snapshot.state.value == "SUCCEEDED" for snapshot in newly_finished):
            self.refresh_all()

    def _show_progress_dialog(self, operation_id: str) -> None:
        if not operation_id:
            return
        existing = self._progress_dialogs.get(operation_id)
        if existing is not None:
            existing.show()
            existing.raise_()
            return
        dialog = OperationProgressDialog(self.container.operations, operation_id, self)
        dialog.finished.connect(lambda _result, oid=operation_id: self._progress_dialogs.pop(oid, None))
        self._progress_dialogs[operation_id] = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _cancel_selected_operation(self) -> None:
        rows = self.operations_table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.operations_table.item(rows[0].row(), 0)
        operation_id = item.data(Qt.ItemDataRole.UserRole)
        self.container.operations.cancel(str(operation_id))

    def _delete_current(self) -> None:
        if not self.current_contexts:
            return
        context = self.current_contexts[0]
        mapping = {"ALLOCATION": ActionId.REMOVE_ALLOCATION, "MATCH_GROUP": ActionId.REMOVE_GROUP, "MANUAL": ActionId.REMOVE_MANUAL_SETTLEMENT}
        action = mapping.get(context.object_type)
        if action:
            self.handle_action(action, self.current_contexts)

    def _edit_current(self) -> None:
        if not self.current_contexts:
            return
        context = self.current_contexts[0]
        mapping = {"ALLOCATION": ActionId.EDIT_ALLOCATION, "MANUAL": ActionId.EDIT_MANUAL_SETTLEMENT, "INVOICE": ActionId.SPLIT_DOCUMENT, "BOOKING": ActionId.SPLIT_SOURCE, "CARD": ActionId.SPLIT_SOURCE}
        action = mapping.get(context.object_type)
        if action:
            self.handle_action(action, self.current_contexts)

    def _escape(self) -> None:
        if hasattr(self.matching, "cancel_transient"):
            self.matching.cancel_transient()
        self.detail_dock.hide()
        self.statusBar().clearMessage()

    def _offer_interrupted_recovery(self) -> None:
        for snapshot in self.container.operations.interrupted():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Přerušený běh")
            box.setText(
                f"Operace {snapshot.operation_type} byla přerušena pádem nebo restartem aplikace."
            )
            box.setInformativeText(
                "Ano: obnovit od bezpečného checkpointu.\n"
                "Ne: vědomě zahodit přerušený běh.\n"
                "Zrušit: rozhodnout později v Centru operací."
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Yes)
            answer = box.exec()
            if answer == QMessageBox.StandardButton.Yes:
                self.navigate("imports")
                if self.imports.recover_interrupted(snapshot.operation_type, snapshot.recovery):
                    self.container.operations.discard_interrupted(snapshot.id)
            elif answer == QMessageBox.StandardButton.No:
                self.container.operations.discard_interrupted(snapshot.id)
            else:
                self.operations_dock.show()
                break

    def _daily_backup(self) -> None:
        try:
            self.container.backup.daily_if_needed()
        except Exception:
            self.statusBar().showMessage("Denní zálohu se nepodařilo vytvořit. Podrobnosti jsou v diagnostice.", 8000)

    def _apply_ui_settings(self) -> None:
        settings = self.container.settings.all()
        scale = int(settings.get("ui.text_scale", 100))
        high_contrast = bool(settings.get("ui.high_contrast", False))
        base = max(10, round(10 * scale / 100))
        theme = HIGH_CONTRAST_THEME if high_contrast else NORMAL_THEME
        palette = build_palette(theme)
        stylesheet = build_stylesheet(base, theme)
        application = QApplication.instance()
        if application is not None:
            application.setPalette(palette)
            application.setStyleSheet(stylesheet)
        else:
            self.setPalette(palette)
            self.setStyleSheet(stylesheet)

    def _restore_window_state(self) -> None:
        state = self.container.view_state.load("ui.layout", {})
        if isinstance(state, dict):
            geometry = state.get("geometry")
            dock_state = state.get("dock_state")
            if isinstance(geometry, str):
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            if isinstance(dock_state, str):
                self.restoreState(QByteArray.fromBase64(dock_state.encode("ascii")))
            splitters = state.get("splitters", {})
            if isinstance(splitters, dict):
                for splitter in self.findChildren(QSplitter):
                    sizes = splitters.get(splitter.objectName())
                    if splitter.objectName() and isinstance(sizes, list) and all(isinstance(value, int) and value >= 0 for value in sizes):
                        splitter.setSizes(sizes)
            headers = state.get("headers", {})
            if isinstance(headers, dict):
                for table in self.findChildren(QTableView):
                    encoded = headers.get(table.objectName())
                    if table.objectName() and isinstance(encoded, str):
                        table.horizontalHeader().restoreState(QByteArray.fromBase64(encoded.encode("ascii")))
        key = str(self.container.settings.get("ui.last_view"))
        self.navigate(key if key in self.pages else "dashboard")

    def _save_window_state(self) -> None:
        splitters = {
            splitter.objectName(): splitter.sizes()
            for splitter in self.findChildren(QSplitter)
            if splitter.objectName()
        }
        headers = {
            table.objectName(): bytes(table.horizontalHeader().saveState().toBase64()).decode("ascii")
            for table in self.findChildren(QTableView)
            if table.objectName()
        }
        self.container.view_state.save(
            "ui.layout",
            {
                "geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
                "dock_state": bytes(self.saveState().toBase64()).decode("ascii"),
                "splitters": splitters,
                "headers": headers,
            },
        )

    def _toast(self, text: str) -> None:
        self.toast_label.setText(text)
        QTimer.singleShot(10_000, self.toast_label.clear)
        self.statusBar().showMessage(text, 10_000)

    def _focus_help_changed(self, old: QWidget | None, current: QWidget | None) -> None:
        del old
        if current is None:
            self.focus_help.clear()
            return
        text = current.toolTip() or current.accessibleDescription() or current.accessibleName()
        self.focus_help.setText(str(text or ""))

    def _invoice_remaining(self, invoice_id: str) -> int:
        row = self.container.database.query("SELECT total_minor-COALESCE((SELECT SUM(amount_minor) FROM allocation WHERE invoice_id=? AND active=1),0) AS remaining FROM invoice WHERE external_id=?", (invoice_id, invoice_id))
        return int(row[0][0]) if row else 0

    def _group_difference(self, group_id: str) -> int:
        row = self.container.database.query("SELECT difference_minor FROM match_group WHERE id=?", (group_id,))
        return int(row[0][0]) if row else 0

    def closeEvent(self, event: QCloseEvent) -> None:
        active = [snapshot for snapshot in self.container.operations.snapshots() if snapshot.state.value in {"QUEUED", "RUNNING", "CANCELLING"}]
        if active:
            answer = QMessageBox.question(self, "Probíhá operace", "Probíhá dlouhá operace. Bezpečně ji zrušit a ukončit aplikaci?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for snapshot in active:
                self.container.operations.cancel(snapshot.id)
        self._save_window_state()
        event.accept()
