from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...app.config import BETTER_HOTEL_BASE_URL, SETTING_SPECS, SettingSpec
from ...app.container import ServiceContainer
from ...infrastructure.better_hotel.client import BetterHotelClient, Tokens
from ...infrastructure.security.secrets import ApiTokens
from ...application.settings import SettingsValidationError
from ..component_registry import ComponentId, bind_component


class SettingsScreen(QWidget):
    settingsChanged = Signal()

    def __init__(self, container: ServiceContainer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self.widgets: dict[str, QWidget] = {}
        self.rehide = QTimer(self)
        self.rehide.setSingleShot(True)
        self.rehide.setInterval(30_000)
        self.rehide.timeout.connect(lambda: self.show_tokens.setChecked(False))

        root = QVBoxLayout(self)
        title = QLabel("Nastavení")
        title.setObjectName("screenTitle")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        body = QVBoxLayout(page)

        api_box = QGroupBox("Better Hotel API")
        bind_component(api_box, ComponentId.SET_API)
        api_form = QFormLayout(api_box)
        endpoint = QLineEdit(BETTER_HOTEL_BASE_URL)
        endpoint.setReadOnly(True)
        endpoint.setToolTip("Pevný read-only endpoint. Nelze jej měnit.")
        self.access_token = QLineEdit()
        self.access_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.access_token.setToolTip("Tajný Access Token pro read-only přístup k Better Hotel API. Ukládá se mimo databázi v zabezpečeném úložišti.")
        self.access_token.setAccessibleName("Access Token")
        self.client_token = QLineEdit()
        self.client_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_token.setToolTip("Tajný Client Token pro read-only přístup k Better Hotel API. Ukládá se mimo databázi v zabezpečeném úložišti.")
        self.client_token.setAccessibleName("Client Token")
        self.show_tokens = QCheckBox("Dočasně zobrazit tokeny")
        self.show_tokens.setToolTip("Dočasně zobrazí oba tokeny v okně. Po 30 sekundách se znovu skryjí.")
        self.show_tokens.toggled.connect(self._toggle_tokens)
        api_form.addRow("Endpoint", endpoint)
        api_form.addRow("Access Token", self.access_token)
        api_form.addRow("Client Token", self.client_token)
        api_form.addRow("", self.show_tokens)
        api_actions = QHBoxLayout()
        test = QPushButton("Test připojení")
        test.clicked.connect(self.test_connection)
        clear = QPushButton("Odstranit uložené tokeny")
        clear.clicked.connect(self.clear_tokens)
        api_actions.addWidget(test)
        api_actions.addWidget(clear)
        api_actions.addStretch(1)
        api_form.addRow("", api_actions)
        body.addWidget(api_box)


        groups: dict[str, QFormLayout] = {}
        for spec in SETTING_SPECS.values():
            if spec.key == "ui.last_view":
                continue
            if spec.group not in groups:
                box = QGroupBox(spec.group)
                component_map = {
                    "Synchronizace": ComponentId.SET_SYNC,
                    "Párování": ComponentId.SET_MATCH,
                    "Importy": ComponentId.SET_IMPORT,
                    "Data": ComponentId.SET_DATA,
                    "Rozhraní": ComponentId.SET_UI,
                }
                if spec.group in component_map:
                    bind_component(box, component_map[spec.group])
                form = QFormLayout(box)
                groups[spec.group] = form
                body.addWidget(box)
            widget = self._widget_for(spec)
            widget.setToolTip(spec.tooltip)
            widget.setAccessibleName(spec.label)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(widget, 1)
            if spec.key.endswith("directory"):
                browse = QPushButton("Vybrat…")
                browse.setToolTip(f"Vybrat hodnotu: {spec.label}")
                browse.clicked.connect(lambda _checked=False, key=spec.key: self._browse_directory(key))
                row_layout.addWidget(browse)
            reset = QPushButton("Výchozí")
            reset.setToolTip(f"Obnovit výchozí hodnotu: {spec.label}")
            reset.clicked.connect(lambda _checked=False, key=spec.key: self._reset_one(key))
            row_layout.addWidget(reset)
            label = QLabel(spec.label)
            label.setToolTip(spec.tooltip)
            row_widget.setToolTip(spec.tooltip)
            groups[spec.group].addRow(label, row_widget)
            self.widgets[spec.key] = widget
            self._connect_validation(widget)

        self.validation_summary = QLabel("Nastavení jsou platná.")
        self.validation_summary.setWordWrap(True)
        bind_component(self.validation_summary, ComponentId.SETTINGS_VALIDATION_SUMMARY)
        body.addWidget(self.validation_summary)

        data_box = QGroupBox("Zálohy, diagnostika a data")
        data_actions = QHBoxLayout(data_box)
        backup = QPushButton("Vytvořit zálohu")
        backup.clicked.connect(self.create_backup)
        restore = QPushButton("Obnovit ze zálohy")
        restore.clicked.connect(self.restore_backup)
        diagnostic = QPushButton("Vytvořit diagnostický balíček")
        diagnostic.clicked.connect(self.create_diagnostics)
        open_data = QPushButton("Zobrazit datovou složku")
        open_data.clicked.connect(self.show_data_path)
        data_actions.addWidget(backup)
        data_actions.addWidget(restore)
        data_actions.addWidget(diagnostic)
        reset_layout = QPushButton("Obnovit rozložení a sloupce")
        reset_layout.clicked.connect(self.reset_layout_state)
        reset_filters = QPushButton("Odstranit uložené filtry")
        reset_filters.clicked.connect(self.reset_saved_filters)
        data_actions.addWidget(open_data)
        data_actions.addWidget(reset_layout)
        data_actions.addWidget(reset_filters)
        body.addWidget(data_box)
        body.addStretch(1)
        scroll.setWidget(page)
        root.addWidget(scroll, 1)

        controls = QHBoxLayout()
        save = QPushButton("Uložit nastavení")
        save.setObjectName("PRIMARY_SAVE_SETTINGS")
        save.clicked.connect(self.save)
        defaults = QPushButton("Obnovit výchozí")
        defaults.clicked.connect(self.restore_defaults)
        controls.addStretch(1)
        controls.addWidget(defaults)
        controls.addWidget(save)
        root.addLayout(controls)
        self.load()

    def _widget_for(self, spec: SettingSpec) -> QWidget:
        default = spec.default
        if isinstance(default, bool):
            return QCheckBox()
        if isinstance(default, date):
            widget = QDateEdit()
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("dd.MM.yyyy")
            return widget
        if isinstance(default, int):
            widget = QSpinBox()
            widget.setRange(int(spec.minimum if spec.minimum is not None else -2_147_483_648), int(spec.maximum if spec.maximum is not None else 2_147_483_647))
            return widget
        if isinstance(default, float):
            widget = QDoubleSpinBox()
            widget.setDecimals(2)
            widget.setSingleStep(0.1)
            widget.setRange(float(spec.minimum if spec.minimum is not None else -1e9), float(spec.maximum if spec.maximum is not None else 1e9))
            return widget
        if spec.choices:
            widget = QComboBox()
            labels = {"ask": "Vždy se zeptat", "compact": "Kompaktní", "normal": "Normální", "comfortable": "Pohodlná"}
            for choice in spec.choices:
                widget.addItem(labels.get(str(choice), str(choice)), choice)
            return widget
        line = QLineEdit()
        if spec.key.endswith("directory"):
            line.setPlaceholderText("Výchozí aplikační složka")
        return line

    def load(self) -> None:
        try:
            tokens = self.container.secrets.load_tokens()
        except Exception as exc:
            QMessageBox.warning(self, "Tokeny nelze načíst", str(exc))
            tokens = ApiTokens()
        self.access_token.setText(tokens.access_token)
        self.client_token.setText(tokens.client_token)
        values = self.container.settings.all()
        if not str(values.get("data.data_directory") or "").strip():
            values["data.data_directory"] = str(self.container.paths.data)
        for key, widget in self.widgets.items():
            self._set_widget_value(widget, values.get(key, SETTING_SPECS[key].default))
        self._validate_live()

    def save(self) -> None:
        values = {key: self._widget_value(widget) for key, widget in self.widgets.items()}
        previous_values = self.container.settings.all()
        try:
            previous_tokens = self.container.secrets.load_tokens()
        except Exception:
            previous_tokens = ApiTokens()
        configuration_saved = False
        requested_data_directory = Path(str(values.get("data.data_directory") or "").strip()).expanduser()
        current_data_directory = self.container.paths.data.resolve()
        relocation_required = bool(str(values.get("data.data_directory") or "").strip()) and requested_data_directory.resolve() != current_data_directory
        if relocation_required:
            answer = QMessageBox.question(
                self,
                "Změnit datovou složku",
                "Program vytvoří bezpečnostní zálohu a konzistentní kopii databáze, tokenů, logů a nastavení. "
                "Nová složka se použije po restartu aplikace. Pokračovat?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.container.settings.save(values)
            self.container.secrets.save_tokens(ApiTokens(self.access_token.text().strip(), self.client_token.text().strip()))
            configuration_saved = True
            if relocation_required:
                self.container.data_location.prepare(requested_data_directory)
        except SettingsValidationError as exc:
            self._show_validation_errors(exc.errors)
            QMessageBox.warning(self, "Nastavení nebylo uloženo", "Opravte označené hodnoty. Žádná část konfigurace nebyla uložena.")
            return
        except Exception as exc:
            if configuration_saved and relocation_required:
                try:
                    self.container.settings.save(previous_values)
                    self.container.secrets.save_tokens(previous_tokens)
                except Exception as rollback_exc:
                    QMessageBox.critical(
                        self,
                        "Nastavení vyžaduje kontrolu",
                        f"Změna datové složky selhala a automatické vrácení nastavení také selhalo: {rollback_exc}",
                    )
            QMessageBox.warning(self, "Nastavení nebylo uloženo", str(exc))
            return
        self._show_validation_errors({})
        self.show_tokens.setChecked(False)
        message = "Nastavení bylo atomicky uloženo. Tokeny jsou uložené mimo databázi v uživatelském šifrovaném úložišti."
        if relocation_required:
            message += "\n\nDatová složka byla bezpečně připravena. Ukončete a znovu spusťte aplikaci, aby se nové umístění aktivovalo."
        QMessageBox.information(self, "Nastavení", message)
        self.settingsChanged.emit()

    def restore_defaults(self) -> None:
        for key, widget in self.widgets.items():
            self._set_widget_value(widget, SETTING_SPECS[key].default)
        self._validate_live()

    def _reset_one(self, key: str) -> None:
        self._set_widget_value(self.widgets[key], SETTING_SPECS[key].default)
        self._validate_live()

    def _browse_directory(self, key: str) -> None:
        widget = self.widgets.get(key)
        if not isinstance(widget, QLineEdit):
            return
        initial = widget.text().strip() or str(self.container.paths.data)
        selected = QFileDialog.getExistingDirectory(self, SETTING_SPECS[key].label, initial)
        if selected:
            widget.setText(selected)

    def _connect_validation(self, widget: QWidget) -> None:
        signal = None
        if isinstance(widget, QCheckBox):
            signal = widget.toggled
        elif isinstance(widget, QDateEdit):
            signal = widget.dateChanged
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            signal = widget.valueChanged
        elif isinstance(widget, QComboBox):
            signal = widget.currentIndexChanged
        elif isinstance(widget, QLineEdit):
            signal = widget.textChanged
        if signal is not None:
            signal.connect(lambda *_: self._validate_live())

    def _validate_live(self) -> None:
        values = {key: self._widget_value(widget) for key, widget in self.widgets.items()}
        try:
            self.container.settings.validate(values)
        except SettingsValidationError as exc:
            self._show_validation_errors(exc.errors)
        else:
            self._show_validation_errors({})

    def _show_validation_errors(self, errors: dict[str, str]) -> None:
        for key, widget in self.widgets.items():
            error = errors.get(key)
            widget.setProperty("invalid", bool(error))
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
            widget.setToolTip((SETTING_SPECS[key].tooltip + (f"\nChyba: {error}" if error else "")))
        if errors:
            lines = [f"• {SETTING_SPECS.get(key, SettingSpec(key, '', key, '', '')).label}: {message}" for key, message in errors.items()]
            self.validation_summary.setText("Nastavení nelze uložit:\n" + "\n".join(lines))
            self.validation_summary.setProperty("state", "invalid")
        else:
            self.validation_summary.setText("Nastavení jsou platná a lze je atomicky uložit.")
            self.validation_summary.setProperty("state", "valid")
        self.validation_summary.style().unpolish(self.validation_summary)
        self.validation_summary.style().polish(self.validation_summary)
        self.validation_summary.update()

    def reset_layout_state(self) -> None:
        self.container.view_state.save("ui.layout", {})
        QMessageBox.information(self, "Rozložení", "Uložené rozložení panelů a sloupců bylo resetováno. Změna se plně projeví po novém otevření obrazovek.")
        self.settingsChanged.emit()

    def reset_saved_filters(self) -> None:
        answer = QMessageBox.question(self, "Odstranit uložené filtry", "Odstranit všechny uložené filtry vyhledávání a sestav?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.container.database.execute("DELETE FROM saved_filter")
        QMessageBox.information(self, "Uložené filtry", "Všechny uložené filtry byly odstraněny.")

    def test_connection(self) -> None:
        access = self.access_token.text().strip()
        client_token = self.client_token.text().strip()
        if not access or not client_token:
            QMessageBox.information(self, "Tokeny nejsou nastavené", "Doplňte Access Token a Client Token. Aplikace se bez nich normálně otevře, pouze nebude stahovat API data.")
            return
        values = {key: self._widget_value(widget) for key, widget in self.widgets.items()}
        try:
            normalized = self.container.settings.validate(values)
            with BetterHotelClient(Tokens(access, client_token), timeout_seconds=int(normalized["sync.timeout_seconds"]), retries=int(normalized["sync.retry_count"]), requests_per_second=float(normalized["sync.requests_per_second"])) as api:
                api.get("/currency")
        except Exception as exc:
            QMessageBox.warning(self, "Test připojení se nezdařil", str(exc))
            return
        QMessageBox.information(self, "Test připojení", "Read-only spojení s Better Hotelem je funkční.")

    def clear_tokens(self) -> None:
        self.container.secrets.clear_tokens()
        self.access_token.clear()
        self.client_token.clear()
        self.show_tokens.setChecked(False)
        QMessageBox.information(self, "Tokeny", "Uložené tokeny byly odstraněny.")

    def create_backup(self) -> None:
        try:
            path = self.container.backup.create()
        except Exception as exc:
            QMessageBox.warning(self, "Záloha se nezdařila", str(exc))
            return
        QMessageBox.information(self, "Záloha vytvořena", str(path))

    def restore_backup(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Vyberte zálohu",
            str(self.container.backup.directory),
            "SQLite zálohy (*.sqlite3)",
        )
        if not file_name:
            return
        answer = QMessageBox.question(self, "Obnovit databázi", "Před obnovou vznikne bezpečnostní kopie aktuální databáze. Pokračovat?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.container.backup.restore(Path(file_name))
        except Exception as exc:
            QMessageBox.warning(self, "Obnova se nezdařila", str(exc))
            return
        QMessageBox.information(self, "Obnova dokončena", "Databáze byla obnovena a její integrita ověřena.")

    def create_diagnostics(self) -> None:
        try:
            path = self.container.diagnostics.create()
        except Exception as exc:
            QMessageBox.warning(self, "Diagnostika se nezdařila", str(exc))
            return
        QMessageBox.information(self, "Diagnostický balíček", f"Balíček bez tokenů byl vytvořen:\n{path}")

    def show_data_path(self) -> None:
        QMessageBox.information(self, "Datová složka", str(self.container.paths.data))

    def _toggle_tokens(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.access_token.setEchoMode(mode)
        self.client_token.setEchoMode(mode)
        if visible:
            self.rehide.start()
        else:
            self.rehide.stop()

    @staticmethod
    def _widget_value(widget: QWidget) -> Any:
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QDateEdit):
            value = widget.date()
            return date(value.year(), value.month(), value.day())
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QLineEdit):
            return widget.text()
        raise TypeError(type(widget).__name__)

    @staticmethod
    def _set_widget_value(widget: QWidget, value: Any) -> None:
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QDateEdit):
            if isinstance(value, str):
                value = date.fromisoformat(value)
            widget.setDate(QDate(value.year, value.month, value.day))
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(value))
        elif isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(value))
        elif isinstance(widget, QComboBox):
            index = widget.findData(value)
            if index >= 0:
                widget.setCurrentIndex(index)
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value))
