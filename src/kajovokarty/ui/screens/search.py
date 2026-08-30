from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...app.container import ServiceContainer
from ..action_registry import ObjectActionRegistry, ObjectContext
from ..common import EmptyState
from ..component_registry import ComponentId, bind_component
from ..models import ObjectTableModel, ObjectTableView


class SearchScreen(QWidget):
    contextsChanged = Signal(object)

    def __init__(self, container: ServiceContainer, registry: ObjectActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self.registry = registry
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.search_now)
        layout = QVBoxLayout(self)
        title = QLabel("Vyhledávání")
        title.setObjectName("screenTitle")
        layout.addWidget(title)
        row = QHBoxLayout()
        self.input = QLineEdit()
        bind_component(self.input, ComponentId.SEARCH_INPUT)
        self.input.setPlaceholderText("Doklad, Booking.com číslo, SEQ ID, ARN, částka, datum…")
        self.input.setClearButtonEnabled(True)
        self.input.textChanged.connect(lambda _: self.timer.start())
        button = QPushButton("Hledat")
        button.clicked.connect(self.search_now)
        row.addWidget(self.input, 1)
        row.addWidget(button)
        layout.addLayout(row)
        filter_bar = QWidget()
        bind_component(filter_bar, ComponentId.SEARCH_FILTERS)
        filters = QHBoxLayout(filter_bar)
        filters.setContentsMargins(0, 0, 0, 0)
        self.type_filter = QComboBox()
        for label, value in (
            ("Všechny typy", ""),
            ("Doklady", "Doklad"),
            ("Rezervace", "Rezervace"),
            ("Booking.com", "Booking.com"),
            ("Karty", "Karta"),
            ("Skupiny", "Vyrovnávací skupina"),
            ("Ruční zdroje", "Ruční zdroj"),
            ("Návrhy párování", "Návrh párování"),
            ("Booking reference", "Booking reference"),
            ("Účty", "Účet"),
            ("Položky účtu", "Položka účtu"),
            ("Změny zdrojů", "Upozornění na změnu zdroje"),
        ):
            self.type_filter.addItem(label, value)
        self.type_filter.currentIndexChanged.connect(self.search_now)
        self.currency_filter = QComboBox()
        self.currency_filter.addItem("Všechny měny", "")
        self.currency_filter.addItem("CZK", "CZK")
        self.currency_filter.addItem("EUR", "EUR")
        self.currency_filter.currentIndexChanged.connect(self.search_now)
        self.date_filter = QLineEdit()
        self.date_filter.setPlaceholderText("Datum nebo rok (volitelné)")
        self.date_filter.textChanged.connect(lambda _: self.timer.start())
        clear_filters = QPushButton("Vymazat filtry")
        clear_filters.clicked.connect(self._clear_filters)
        filters.addWidget(QLabel("Typ:"))
        filters.addWidget(self.type_filter)
        filters.addWidget(QLabel("Měna:"))
        filters.addWidget(self.currency_filter)
        filters.addWidget(QLabel("Datum:"))
        filters.addWidget(self.date_filter, 1)
        filters.addWidget(clear_filters)
        layout.addWidget(filter_bar)
        saved_row = QHBoxLayout()
        self.saved = QComboBox()
        self.saved.setAccessibleName("Uložené filtry vyhledávání")
        self.saved.currentIndexChanged.connect(self._apply_saved_filter)
        save = QPushButton("Uložit filtr")
        save.clicked.connect(self._save_filter)
        remove = QPushButton("Odstranit uložený filtr")
        remove.clicked.connect(self._remove_filter)
        saved_row.addWidget(QLabel("Uložený filtr:"))
        saved_row.addWidget(self.saved, 1)
        saved_row.addWidget(save)
        saved_row.addWidget(remove)
        layout.addLayout(saved_row)
        splitter = QSplitter()
        self.results = ObjectTableView(registry)
        bind_component(self.results, ComponentId.SEARCH_RESULTS)
        self.results.setAccessibleName("Výsledky globálního vyhledávání")
        self.results.setModel(ObjectTableModel(["Typ", "Výsledek", "Souvislosti", "Částka", "Datum"], ["type", "label", "secondary", "amount", "date"]))
        self.results.selectionContextsChanged.connect(self._selection_changed)
        splitter.addWidget(self.results)
        self.relations = ObjectTableView(registry)
        bind_component(self.relations, ComponentId.SEARCH_RELATIONS)
        self.relations.setModel(ObjectTableModel(["Typ", "Položka", "Souvislosti", "Částka", "Datum"], ["type", "label", "secondary", "amount", "date"]))
        self.relations.selectionContextsChanged.connect(self.contextsChanged)
        splitter.addWidget(self.relations)
        splitter.setSizes([700, 500])
        layout.addWidget(splitter, 1)
        self.hint = QLabel("Hledání je indexované a podporuje technické i lidské identifikátory.")
        layout.addWidget(self.hint)
        self._reload_saved_filters()

    def focus_search(self) -> None:
        self.input.setFocus()
        self.input.selectAll()

    def search_now(self) -> None:
        query = self.input.text().strip()
        if not query:
            self.results.model().set_rows([])
            self.relations.model().set_rows([])
            self.hint.setText("Zadejte číslo dokladu, rezervace, Booking.com, SEQ ID, ARN, částku nebo datum.")
            return
        results = self.container.search.search(query)
        object_type = str(self.type_filter.currentData() or "")
        currency = str(self.currency_filter.currentData() or "")
        date_text = self.date_filter.text().strip().casefold()
        if object_type:
            results = [result for result in results if result.object_type == object_type]
        if currency:
            results = [result for result in results if f" {currency} " in f" {result.amount_text} "]
        if date_text:
            results = [result for result in results if date_text in result.date_text.casefold()]
        rows = [self._row(result) for result in results]
        self.results.model().set_rows(rows)
        self.hint.setText(f"Nalezeno {len(rows)} výsledků. Každý výsledek má stejné objektové akce jako ostatní živé pohledy.")

    def _reload_saved_filters(self, select_id: str | None = None) -> None:
        self.saved.blockSignals(True)
        self.saved.clear()
        self.saved.addItem("— vyberte —", None)
        for saved_filter in self.container.saved_filters.list("search"):
            self.saved.addItem(saved_filter.name, saved_filter)
            if saved_filter.id == select_id:
                self.saved.setCurrentIndex(self.saved.count() - 1)
        self.saved.blockSignals(False)

    def _apply_saved_filter(self) -> None:
        saved_filter = self.saved.currentData()
        if saved_filter is None:
            return
        self.input.setText(str(saved_filter.values.get("query", "")))
        type_index = self.type_filter.findData(str(saved_filter.values.get("object_type", "")))
        currency_index = self.currency_filter.findData(str(saved_filter.values.get("currency", "")))
        if type_index >= 0:
            self.type_filter.setCurrentIndex(type_index)
        if currency_index >= 0:
            self.currency_filter.setCurrentIndex(currency_index)
        self.date_filter.setText(str(saved_filter.values.get("date", "")))
        self.search_now()

    def _save_filter(self) -> None:
        query = self.input.text().strip()
        if not query:
            QMessageBox.information(self, "Filtr nelze uložit", "Nejprve zadejte hledaný výraz.")
            return
        name, accepted = QInputDialog.getText(self, "Uložit filtr", "Lidský název filtru:")
        if not accepted:
            return
        saved_filter = self.container.saved_filters.save(
            "search",
            name,
            {
                "query": query,
                "object_type": str(self.type_filter.currentData() or ""),
                "currency": str(self.currency_filter.currentData() or ""),
                "date": self.date_filter.text().strip(),
            },
        )
        self._reload_saved_filters(saved_filter.id)

    def _remove_filter(self) -> None:
        saved_filter = self.saved.currentData()
        if saved_filter is None:
            QMessageBox.information(self, "Vyberte filtr", "Vyberte uložený filtr, který chcete odstranit.")
            return
        self.container.saved_filters.remove(saved_filter.id)
        self._reload_saved_filters()

    def _clear_filters(self) -> None:
        self.type_filter.setCurrentIndex(0)
        self.currency_filter.setCurrentIndex(0)
        self.date_filter.clear()
        self.search_now()

    def _selection_changed(self, contexts: list[ObjectContext]) -> None:
        self.contextsChanged.emit(contexts)
        if not contexts:
            self.relations.model().set_rows([])
            return
        related = self.container.search.related(contexts[0].object_ref)
        self.relations.model().set_rows([self._row(item) for item in related])

    @staticmethod
    def _row(result: Any) -> dict[str, Any]:
        object_type, _, object_id = result.object_ref.partition(":")
        currency = None
        amount_minor = None
        amount_parts = result.amount_text.split()
        if len(amount_parts) >= 2 and amount_parts[0].lstrip("-").isdigit():
            amount_minor = int(amount_parts[0])
            currency = amount_parts[1]
        context = ObjectContext(object_type, object_id, result.primary_label, currency, amount_minor, None, None, "search", {"technical_ids": result.technical_ids})
        return {"type": result.object_type, "label": result.primary_label, "secondary": result.secondary_text, "amount": result.amount_text, "date": result.date_text, "_context": context, "_tooltip": result.technical_ids}
