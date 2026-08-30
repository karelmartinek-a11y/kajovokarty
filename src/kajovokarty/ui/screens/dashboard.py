from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QVBoxLayout, QWidget

from ...app.container import ServiceContainer
from ...domain.money import Money
from ..action_registry import ObjectActionRegistry, ObjectContext
from ..common import KpiCard
from ..component_registry import ComponentId, bind_component
from ..models import ObjectTableModel, ObjectTableView


_KPI_DEFINITIONS = (
    ("documents", "Doklady"),
    ("booking", "Booking.com"),
    ("cards", "Karty"),
    ("manual", "Ruční zdroje"),
    ("matched", "Spárováno"),
    ("unmatched", "Nespárováno"),
    ("underpaid", "Chybí úhrada"),
    ("overpaid", "Přeplatek"),
    ("conflicts", "Konflikty"),
    ("old", "Staré rozdíly"),
)

_AGING_BUCKETS = (
    ("0_2", "0–2 dny", 0, 2),
    ("3_7", "3–7 dní", 3, 7),
    ("8_30", "8–30 dní", 8, 30),
    ("31_90", "31–90 dní", 31, 90),
    ("90_plus", "90+ dní", 91, None),
)


class DashboardScreen(QWidget):
    openMatching = Signal(str, str)
    openImportRun = Signal(str, str)
    documentActivated = Signal(object)
    autoMatchRequested = Signal()

    def __init__(self, container: ServiceContainer, registry: ObjectActionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self.registry = registry
        layout = QVBoxLayout(self)
        heading = QLabel("Dashboard")
        heading.setObjectName("screenTitle")
        layout.addWidget(heading)
        document_box = QGroupBox("Doklady s úhradou kartou")
        document_layout = QVBoxLayout(document_box)
        filter_row = QHBoxLayout()
        self.document_status = QComboBox()
        self.document_status.addItems(["Všechny stavy", "NEUHRAZEN", "ČÁSTEČNÁ ÚHRADA", "UHRAZEN"])
        self.document_status.currentIndexChanged.connect(self.refresh_documents)
        self.document_search = QLineEdit()
        self.document_search.setPlaceholderText("Hledat číslo dokladu, rezervaci nebo Booking číslo…")
        self.document_search.textChanged.connect(self.refresh_documents)
        self.booking_reference_filter = QComboBox()
        self.booking_reference_filter.addItems(["Booking číslo: všechny", "Booking číslo: má", "Booking číslo: nemá"])
        self.booking_reference_filter.currentIndexChanged.connect(self.refresh_documents)
        auto_match = QPushButton("Automaticky spárovat")
        auto_match.clicked.connect(self.autoMatchRequested)
        filter_row.addWidget(QLabel("Stav:"))
        filter_row.addWidget(self.document_status)
        filter_row.addWidget(self.booking_reference_filter)
        filter_row.addWidget(self.document_search, 1)
        filter_row.addWidget(auto_match)
        document_layout.addLayout(filter_row)
        self.documents = ObjectTableView(self.registry)
        self.documents.setAccessibleName("Přehled dokladů s úhradou kartou")
        self.documents.setModel(ObjectTableModel(
            ["Stav", "Číslo dokladu", "Datum", "Částka", "Měna", "Číslo rezervace", "Číslo rezervace zdroje"],
            ["status", "code", "date", "amount", "currency", "reservation", "booking_reference"],
        ))
        self.documents.activated.connect(self._document_activated)
        document_layout.addWidget(self.documents)
        layout.addWidget(document_box, 2)
        self.alerts = QLabel()
        self.alerts.setWordWrap(True)
        self.alerts.setObjectName("criticalAlert")
        layout.addWidget(self.alerts)
        freshness_box = QGroupBox("Aktuálnost zdrojů")
        bind_component(freshness_box, ComponentId.DASH_FRESHNESS)
        freshness_layout = QVBoxLayout(freshness_box)
        self.freshness = ObjectTableView(self.registry)
        self.freshness.setAccessibleName("Aktuálnost zdrojů a poslední běhy")
        self.freshness.setAccessibleDescription(
            "Tabulka posledních běhů Better Hotelu, Booking.com a banky. "
            "Enter nebo dvojklik otevře běh v Importech; Shift+F10 otevře plné objektové menu."
        )
        self.freshness.setModel(
            ObjectTableModel(
                ["Zdroj", "Poslední úspěšný běh", "Stav"],
                ["source", "last", "status"],
            )
        )
        self.freshness.activated.connect(self._freshness_activated)
        freshness_layout.addWidget(self.freshness)
        layout.addWidget(freshness_box)
        self.kpi_boxes: dict[str, dict[str, KpiCard]] = {}
        currency_grid = QHBoxLayout()
        self.currency_grid = currency_grid
        for currency, component_id in (("CZK", ComponentId.DASH_CZK), ("EUR", ComponentId.DASH_EUR)):
            box = QGroupBox(f"Přehled {currency}")
            bind_component(box, component_id)
            grid = QGridLayout(box)
            cards: dict[str, KpiCard] = {}
            for index, (key, label) in enumerate(_KPI_DEFINITIONS):
                card = KpiCard(f"{currency}:{key}", label)
                card.clicked.connect(self._kpi_clicked)
                grid.addWidget(card, index // 5, index % 5)
                cards[key] = card
            self.kpi_boxes[currency] = cards
            currency_grid.addWidget(box)
        layout.addLayout(currency_grid)

        aging_box = QGroupBox("Stáří rozdílů")
        bind_component(aging_box, ComponentId.DASH_AGING)
        aging_layout = QHBoxLayout(aging_box)
        self.aging_cards: dict[str, KpiCard] = {}
        for key, label, _minimum, _maximum in _AGING_BUCKETS:
            card = KpiCard(f"AGING:{key}", label)
            card.clicked.connect(self._aging_clicked)
            aging_layout.addWidget(card)
            self.aging_cards[key] = card
        layout.addWidget(aging_box)

        splitter = QSplitter()
        self.oldest = self._table("Nejstarší rozdíly", splitter, ComponentId.DASH_OLDEST)
        self.largest = self._table("Největší rozdíly", splitter, ComponentId.DASH_LARGEST)
        layout.addWidget(splitter, 1)
        freshness_box.setVisible(False)
        for index in range(currency_grid.count()):
            widget = currency_grid.itemAt(index).widget()
            if widget is not None:
                widget.setVisible(False)
        aging_box.setVisible(False)
        splitter.setVisible(False)
        self.refresh()

    def _table(self, title: str, parent: QWidget, component_id: ComponentId) -> ObjectTableView:
        box = QGroupBox(title, parent)
        bind_component(box, component_id)
        box_layout = QVBoxLayout(box)
        table = ObjectTableView(self.registry)
        table.setModel(ObjectTableModel(["Stav", "Doklad / skupina", "Datum", "Měna", "Rozdíl"], ["status", "label", "date", "currency", "difference"]))
        box_layout.addWidget(table)
        return table

    def refresh(self) -> None:
        with self.container.database.read_connection() as conn:
            self.refresh_documents()
            warning_age = int(self.container.settings.get("matching.warning_age_days"))
            for currency in ("CZK", "EUR"):
                counts = {
                    "documents": conn.execute("SELECT COUNT(*) FROM invoice WHERE included=1 AND currency_code=?", (currency,)).fetchone()[0],
                    "booking": conn.execute("SELECT COUNT(*) FROM booking_payment_line WHERE active_source=1 AND currency_code=?", (currency,)).fetchone()[0],
                    "cards": conn.execute("SELECT COUNT(*) FROM card_transaction WHERE currency_code=?", (currency,)).fetchone()[0],
                    "manual": conn.execute("SELECT COUNT(*) FROM manual_settlement WHERE active=1 AND currency_code=?", (currency,)).fetchone()[0],
                    "matched": conn.execute("SELECT COUNT(*) FROM match_group WHERE currency_code=? AND status IN ('AUTO_MATCHED','MANUAL_MATCHED','AGGREGATE_MATCHED')", (currency,)).fetchone()[0],
                    "unmatched": conn.execute("SELECT COUNT(*) FROM invoice WHERE included=1 AND currency_code=? AND status IN ('UNMATCHED','PARTIAL')", (currency,)).fetchone()[0],
                    "underpaid": conn.execute("SELECT COUNT(*) FROM match_group WHERE currency_code=? AND status='UNDERPAID'", (currency,)).fetchone()[0],
                    "overpaid": conn.execute("SELECT COUNT(*) FROM match_group WHERE currency_code=? AND status='OVERPAID'", (currency,)).fetchone()[0],
                    "conflicts": conn.execute("SELECT COUNT(*) FROM match_group WHERE currency_code=? AND status IN ('CONFLICT','REVIEW_REQUIRED')", (currency,)).fetchone()[0],
                    "old": conn.execute("SELECT COUNT(*) FROM match_group WHERE currency_code=? AND status NOT IN ('AUTO_MATCHED','MANUAL_MATCHED','AGGREGATE_MATCHED','MANUAL_RESOLVED','REVERSED') AND julianday('now')-julianday(substr(created_at_utc,1,10))>=?", (currency, warning_age)).fetchone()[0],
                }
                for key, count in counts.items():
                    self.kpi_boxes[currency][key].set_value(str(count))
                    self.kpi_boxes[currency][key].setToolTip(
                        f"{count} položek v měně {currency}. Kliknutím otevřete filtrované párování."
                    )
            for key, _label, minimum, maximum in _AGING_BUCKETS:
                if maximum is None:
                    count = conn.execute("SELECT COUNT(*) FROM match_group WHERE status NOT IN ('AUTO_MATCHED','MANUAL_MATCHED','AGGREGATE_MATCHED','MANUAL_RESOLVED','REVERSED') AND julianday('now')-julianday(substr(created_at_utc,1,10))>=?", (minimum,)).fetchone()[0]
                else:
                    count = conn.execute("SELECT COUNT(*) FROM match_group WHERE status NOT IN ('AUTO_MATCHED','MANUAL_MATCHED','AGGREGATE_MATCHED','MANUAL_RESOLVED','REVERSED') AND julianday('now')-julianday(substr(created_at_utc,1,10)) BETWEEN ? AND ?", (minimum, maximum)).fetchone()[0]
                self.aging_cards[key].set_value(str(count))
                self.aging_cards[key].setToolTip(f"{count} rozdílů ve stáří {_label}. Kliknutím otevřete filtr.")
            group_rows = conn.execute("SELECT * FROM match_group WHERE difference_minor<>0 OR status IN ('CONFLICT','REVIEW_REQUIRED') ORDER BY created_at_utc ASC LIMIT 100").fetchall()
            newest: list[dict[str, Any]] = []
            for source, table in (
                ("Better Hotel", "api_sync_run"),
                ("Booking.com", "booking_import_run"),
                ("Banka", "bank_import_run"),
            ):
                latest = conn.execute(
                    f"SELECT id,state,started_at_utc,finished_at_utc FROM {table} "
                    "ORDER BY COALESCE(finished_at_utc,started_at_utc) DESC LIMIT 1"
                ).fetchone()
                newest.append(
                    {
                        "source": source,
                        "id": str(latest["id"]) if latest else "",
                        "state": str(latest["state"]) if latest else "EMPTY",
                        "last": str((latest["finished_at_utc"] or latest["started_at_utc"])) if latest else "dosud nenačteno",
                    }
                )
        rows = [self._group_row(row) for row in group_rows]
        self.oldest.model().set_rows(rows)
        largest = sorted(rows, key=lambda row: abs(row["_context"].amount_minor or 0), reverse=True)
        self.largest.model().set_rows(largest)
        freshness_rows: list[dict[str, Any]] = []
        for row in newest:
            run_id = str(row["id"])
            context = (
                ObjectContext(
                    "IMPORT_RUN",
                    run_id,
                    f"{row['source']} {run_id[:8]}",
                    status=str(row["state"]),
                    view="dashboard",
                    data={"source": str(row["source"])},
                )
                if run_id
                else ObjectContext(
                    "SOURCE_STATUS",
                    str(row["source"]),
                    f"{row['source']} – dosud nenačteno",
                    status="EMPTY",
                    view="dashboard",
                    data={"source": str(row["source"]), "empty": True},
                )
            )
            freshness_rows.append(
                {
                    "source": row["source"],
                    "last": row["last"],
                    "status": row["state"],
                    "_context": context,
                    "_tooltip": (
                        "Enter nebo dvojklik otevře detail běhu v Importech."
                        if run_id
                        else "Zdroj zatím nemá žádný běh. Otevřete Importy a spusťte načtení vědomou akcí."
                    ),
                }
            )
        self.freshness.model().set_rows(freshness_rows)

    def refresh_documents(self) -> None:
        status = self.document_status.currentText()
        text = self.document_search.text().strip()
        booking_filter = self.booking_reference_filter.currentText()
        clauses = ["i.included=1", "i.pay_method=2", "i.paid_at_utc IS NOT NULL"]
        params: list[Any] = []
        status_sql = "CASE WHEN COALESCE(s.manual_paid,0)=1 OR ABS(COALESCE(u.used,0))>=ABS(i.total_minor) THEN 'UHRAZEN' WHEN COALESCE(u.used,0)=0 THEN 'NEUHRAZEN' ELSE 'ČÁSTEČNÁ ÚHRADA' END"
        if status != "Všechny stavy":
            clauses.append(status_sql + "=?")
            params.append(status)
        if booking_filter == "Booking číslo: má":
            clauses.append("r.booking_reference IS NOT NULL AND TRIM(r.booking_reference)<>''")
        elif booking_filter == "Booking číslo: nemá":
            clauses.append("(r.booking_reference IS NULL OR TRIM(r.booking_reference)='')")
        if text:
            clauses.append("(i.code LIKE ? OR r.internal_code LIKE ? OR r.booking_reference LIKE ?)")
            params.extend([f"%{text}%"] * 3)
        rows: list[dict[str, Any]] = []
        with self.container.database.read_connection() as conn:
            query = "SELECT i.*,r.internal_code,r.booking_reference," + status_sql + " AS settlement_status,COALESCE(u.used,0) AS used FROM invoice i LEFT JOIN invoice_payment_status s ON s.invoice_id=i.external_id LEFT JOIN (SELECT invoice_id,SUM(amount_minor) used FROM allocation WHERE active=1 GROUP BY invoice_id) u ON u.invoice_id=i.external_id LEFT JOIN reservation_invoice_link l ON l.invoice_id=i.external_id LEFT JOIN reservation r ON r.uuid=l.reservation_id WHERE " + " AND ".join(clauses) + " GROUP BY i.external_id,r.internal_code,r.booking_reference ORDER BY i.document_date_utc DESC"
            for row in conn.execute(query, params):
                remaining = int(row["total_minor"]) - int(row["used"])
                context = ObjectContext("INVOICE", str(row["external_id"]), str(row["code"]), str(row["currency_code"]), remaining, row["row_version"], str(row["settlement_status"]), "dashboard", {"raw_json": row["raw_json"], "included": True})
                rows.append({"status": row["settlement_status"], "code": row["code"], "date": str(row["document_date_utc"])[:10], "amount": Money(row["total_minor"], row["currency_code"]).format(), "currency": row["currency_code"], "reservation": row["internal_code"] or "", "booking_reference": row["booking_reference"] or "", "_context": context})
        self.documents.model().set_rows(rows)
        critical = self.container.database.query("SELECT message FROM payment_matching_alert WHERE severity='CRITICAL' AND resolved_at_utc IS NULL ORDER BY created_at_utc DESC LIMIT 5")
        self.alerts.setText("⚠ Kritická upozornění: " + " | ".join(str(row["message"]) for row in critical) if critical else "")

    def _document_activated(self, index: QModelIndex) -> None:
        context = self.documents.model().context_at(index.row())
        if context is not None:
            self.documentActivated.emit(context)


    def _freshness_activated(self, index: QModelIndex) -> None:
        model = self.freshness.model()
        if not isinstance(model, ObjectTableModel) or not index.isValid():
            return
        context = model.context_at(index.row())
        source = str(context.data.get("source") or "")
        if context.data.get("empty"):
            self.openImportRun.emit(source, "")
            return
        self.openImportRun.emit(source, context.object_id)

    @staticmethod
    def _group_row(row: Any) -> dict[str, Any]:
        context = ObjectContext("MATCH_GROUP", row["id"], f"Skupina {row['id'][:8]}", row["currency_code"], row["difference_minor"], row["row_version"], row["status"], "dashboard", {"allocation_mode": row["allocation_mode"]})
        return {
            "status": row["status"],
            "label": context.primary_label,
            "date": row["created_at_utc"][:10],
            "currency": row["currency_code"],
            "difference": Money(row["difference_minor"], row["currency_code"]).format(),
            "_context": context,
        }

    def _kpi_clicked(self, key: str) -> None:
        currency, status = key.split(":", 1)
        self.openMatching.emit(currency, status)

    def _aging_clicked(self, key: str) -> None:
        _prefix, bucket = key.split(":", 1)
        self.openMatching.emit("Všechny měny", f"age:{bucket}")
