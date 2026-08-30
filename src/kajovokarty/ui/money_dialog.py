from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..domain.money import Money
from .component_registry import ComponentId, bind_component


class MoneyAmountDialog(QDialog):
    """Human currency editor; values are converted to integer minor units via Decimal."""

    def __init__(
        self,
        *,
        title: str,
        currency: str,
        initial_minor: int,
        label: str = "Částka",
        explanation: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.currency = currency
        self.amount_minor: int | None = None
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        if explanation:
            info = QLabel(explanation)
            info.setWordWrap(True)
            root.addWidget(info)
        form = QFormLayout()
        self.input = QLineEdit(f"{Money(initial_minor, currency).decimal:.2f}".replace(".", ","))
        self.input.setAccessibleName(f"{label} v měně {currency}")
        self.input.setPlaceholderText("0,00")
        self.input.selectAll()
        form.addRow(f"{label} ({currency})", self.input)
        root.addLayout(form)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setProperty("validationError", True)
        self.error.hide()
        root.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bind_component(self.buttons, ComponentId.MATCH_ALLOC_POPOVER)
        self.buttons.accepted.connect(self._accept_value)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.input.returnPressed.connect(self._accept_value)
        self.input.textChanged.connect(lambda _: self._validate(show_error=False))

    def _validate(self, *, show_error: bool) -> bool:
        try:
            value = Money.parse(self.input.text(), self.currency).amount_minor
        except (ValueError, ArithmeticError) as exc:
            self.amount_minor = None
            self.error.setText(f"Zadejte platnou částku v měně {self.currency}: {exc}")
            self.error.setVisible(show_error)
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return False
        if value == 0:
            self.amount_minor = None
            self.error.setText("Částka nesmí být nula.")
            self.error.setVisible(show_error)
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return False
        self.amount_minor = value
        self.error.hide()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        return True

    def _accept_value(self) -> None:
        if self._validate(show_error=True):
            self.accept()

    @classmethod
    def get_amount(
        cls,
        *,
        title: str,
        currency: str,
        initial_minor: int,
        label: str = "Částka",
        explanation: str = "",
        parent: QWidget | None = None,
    ) -> tuple[int, bool]:
        dialog = cls(
            title=title,
            currency=currency,
            initial_minor=initial_minor,
            label=label,
            explanation=explanation,
            parent=parent,
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return (int(dialog.amount_minor or 0), accepted)
