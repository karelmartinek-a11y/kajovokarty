from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
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
from ..domain.money import Money
from .action_registry import ActionId, ObjectActionRegistry, ObjectContext
from .component_registry import ComponentId, bind_component
from .models import ObjectTableModel, ObjectTableView


class CounterpartsDialog(QDialog):
    WINDOWS: tuple[tuple[str, int | None], ...] = (
        ("7 dní", 7),
        ("14 dní", 14),
        ("30 dní", 30),
        ("Celé období", None),
    )

    def __init__(
        self,
        container: ServiceContainer,
        registry: ObjectActionRegistry,
        anchor: ObjectContext,
        *,
        initial_days: int | None = 7,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.container = container
        self.registry = registry
        self.anchor = anchor
        self.setWindowTitle("Možné protějšky")
        self.resize(1120, 720)
        self.setMinimumSize(900, 560)
        self.setAccessibleName("Možné protějšky")
        self.setAccessibleDescription(
            "Vysvětlitelný seznam možných dokladů nebo zdrojů. Rozšířený rozsah nikdy sám nevytvoří vazbu."
        )
        bind_component(self, ComponentId.MATCH_COUNTERPARTS_PANEL)

        root = QVBoxLayout(self)
        title = QLabel(f"Možné protějšky pro: {anchor.primary_label}")
        title.setObjectName("screenTitle")
        root.addWidget(title)
        amount = "—" if anchor.currency is None or anchor.amount_minor is None else Money(anchor.amount_minor, anchor.currency).format()
        self.anchor_summary = QLabel(
            f"{anchor.object_type} • {amount} • stav {anchor.status or '—'} • {anchor.object_ref}"
        )
        self.anchor_summary.setWordWrap(True)
        root.addWidget(self.anchor_summary)

        controls = QHBoxLayout()
        self.window = QComboBox()
        for label, days in self.WINDOWS:
            self.window.addItem(label, days)
        selected = self.window.findData(initial_days)
        self.window.setCurrentIndex(selected if selected >= 0 else 0)
        self.window.currentIndexChanged.connect(self.refresh)
        refresh = QPushButton("Hledat")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(QLabel("Rozsah hledání:"))
        controls.addWidget(self.window)
        controls.addWidget(refresh)
        controls.addStretch(1)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = ObjectTableView(registry)
        self.table.setObjectName("counterpartsTable")
        self.table.setAccessibleName("Seznam možných protějšků")
        self.table.setModel(
            ObjectTableModel(
                ["Typ", "Položka", "Datum", "Vzdálenost", "Zbývá", "Rozdíl", "Jistota", "Stav"],
                ["type", "label", "date", "distance", "remaining", "difference", "score", "status"],
            )
        )
        self.table.selectionContextsChanged.connect(self._selection_changed)
        splitter.addWidget(self.table)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setAccessibleName("Vysvětlení pořadí kandidáta")
        self.evidence.setPlaceholderText("Vyberte kandidáta. Zde se zobrazí finanční rozdíl, datumová vzdálenost a použité důkazy.")
        splitter.addWidget(self.evidence)
        splitter.setSizes([470, 170])
        root.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.add_to_tray = QPushButton("Přidat do pracovního výběru")
        self.add_to_tray.setEnabled(False)
        self.add_to_tray.clicked.connect(self._add_selected)
        self.pair = QPushButton("Spárovat s vybranými")
        self.pair.setEnabled(False)
        self.pair.clicked.connect(self._pair_selected)
        actions.addWidget(self.add_to_tray)
        actions.addWidget(self.pair)
        actions.addStretch(1)
        root.addLayout(actions)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        days = self.window.currentData()
        candidates = self.container.counterparts.search(
            self.anchor.object_type,
            self.anchor.object_id,
            window_days=days,
        )
        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            context = ObjectContext(
                candidate.object_type,
                candidate.object_id,
                candidate.label,
                candidate.currency,
                candidate.remaining_minor,
                candidate.row_version,
                candidate.status,
                "counterparts",
                {
                    "score": candidate.score,
                    "date_distance_days": candidate.date_distance_days,
                    "amount_difference_minor": candidate.amount_difference_minor,
                    "evidence": list(candidate.evidence),
                },
            )
            rows.append(
                {
                    "type": candidate.object_type,
                    "label": candidate.label,
                    "date": candidate.date_text or "—",
                    "distance": "—" if candidate.date_distance_days is None else f"{candidate.date_distance_days} dní",
                    "remaining": Money(candidate.remaining_minor, candidate.currency).format(),
                    "difference": Money(candidate.amount_difference_minor, candidate.currency).format(),
                    "score": f"{candidate.score}/100",
                    "status": candidate.status,
                    "_context": context,
                    "_tooltip": "\n".join(candidate.evidence),
                }
            )
        self.table.model().set_rows(rows)
        range_text = self.window.currentText()
        warning = " Výsledky nad 7 dní zůstávají pouze návrhy k vědomému potvrzení." if days is None or int(days) > 7 else ""
        self.summary.setText(f"Nalezeno {len(rows)} kandidátů v rozsahu {range_text}.{warning}")
        self._selection_changed([])

    def _selection_changed(self, contexts: list[ObjectContext]) -> None:
        self.add_to_tray.setEnabled(bool(contexts))
        self.pair.setEnabled(bool(contexts))
        if not contexts:
            self.evidence.clear()
            return
        blocks: list[str] = []
        for context in contexts:
            currency = context.currency or ""
            difference = int(context.data.get("amount_difference_minor") or 0)
            evidence = "\n".join(f"• {item}" for item in context.data.get("evidence", []))
            blocks.append(
                f"{context.primary_label} • jistota {context.data.get('score', 0)}/100\n"
                f"Finanční rozdíl: {Money(difference, currency).format() if currency else difference}\n"
                f"Datumová vzdálenost: {context.data.get('date_distance_days', '—')} dní\n{evidence}"
            )
        self.evidence.setPlainText("\n\n".join(blocks))

    def _add_selected(self) -> None:
        selected = self.table.selected_contexts()
        if selected:
            self.registry.handler(ActionId.ADD_TO_TRAY, [self.anchor, *selected])

    def _pair_selected(self) -> None:
        selected = self.table.selected_contexts()
        if selected:
            self.registry.handler(ActionId.PAIR_SELECTED, [self.anchor, *selected])
