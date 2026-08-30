from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ..infrastructure.importers.bank_file import BankFileImportService, MultipleMatchingSheets
from ..infrastructure.importers.booking_csv import BookingCsvImportService
from ..infrastructure.persistence.database import Database


class ImportPreflightError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ImportFilePreview:
    kind: str
    path: Path
    file_name: str
    extension: str
    size_bytes: int
    sha256: str
    schema_columns: int
    estimated_rows: int
    selected_sheet: str | None
    currencies: tuple[str, ...]
    usable_rows: int
    quarantine_rows: int
    duplicate_file: bool

    @property
    def human_summary(self) -> str:
        sheet = f" • list {self.selected_sheet}" if self.selected_sheet else ""
        duplicate = " • přesný duplikát již importovaného souboru" if self.duplicate_file else ""
        currencies = ", ".join(self.currencies) or "bez měny"
        return (
            f"{self.kind} • {self.file_name} • {self.size_bytes:,} B • SHA-256 {self.sha256[:12]}…"
            f" • schéma {self.schema_columns} sloupců • {self.estimated_rows} řádků"
            f" • použitelné {self.usable_rows} • karanténa {self.quarantine_rows} • {currencies}{sheet}{duplicate}"
        ).replace(",", " ")


class ImportPreflightService:
    """Immutable file validation and preview before a file enters the import queue."""

    def __init__(
        self,
        database: Database,
        booking: BookingCsvImportService,
        bank: BankFileImportService,
    ) -> None:
        self.database = database
        self.booking = booking
        self.bank = bank

    def booking_preview(self, path: Path, *, max_megabytes: int) -> ImportFilePreview:
        file_path = self._validate_file(path, {".csv"}, max_megabytes)
        digest = self._sha256(file_path)
        parsed = self.booking.inspect(file_path)
        currencies = tuple(sorted({row.line.currency for row in parsed if row.line.currency}))
        usable = sum(1 for row in parsed if row.eligible and row.quarantine_reason is None)
        quarantined = len(parsed) - usable
        duplicate = bool(
            self.database.query(
                "SELECT 1 FROM booking_import_run WHERE file_hash=? AND state IN ('SUCCEEDED','DUPLICATE') LIMIT 1",
                (digest,),
            )
        )
        return ImportFilePreview(
            kind="Booking.com",
            path=file_path,
            file_name=file_path.name,
            extension=file_path.suffix.casefold(),
            size_bytes=file_path.stat().st_size,
            sha256=digest,
            schema_columns=12,
            estimated_rows=len(parsed),
            selected_sheet=None,
            currencies=currencies,
            usable_rows=usable,
            quarantine_rows=quarantined,
            duplicate_file=duplicate,
        )

    def bank_preview(
        self,
        path: Path,
        *,
        max_megabytes: int,
        sheet_name: str | None = None,
    ) -> ImportFilePreview:
        file_path = self._validate_file(path, {".csv", ".xls", ".xlsx"}, max_megabytes)
        digest = self._sha256(file_path)
        selected_sheet, parsed = self.bank.inspect(file_path, sheet_name=sheet_name)
        kinds = Counter(row.kind for row in parsed)
        currencies = tuple(
            sorted(
                {
                    row.transaction.currency
                    for row in parsed
                    if row.transaction is not None and row.transaction.currency
                }
            )
        )
        duplicate = bool(
            self.database.query(
                "SELECT 1 FROM bank_import_run WHERE file_hash=? AND state IN ('SUCCEEDED','DUPLICATE') LIMIT 1",
                (digest,),
            )
        )
        return ImportFilePreview(
            kind="Banka",
            path=file_path,
            file_name=file_path.name,
            extension=file_path.suffix.casefold(),
            size_bytes=file_path.stat().st_size,
            sha256=digest,
            schema_columns=21,
            estimated_rows=len(parsed),
            selected_sheet=selected_sheet,
            currencies=currencies,
            usable_rows=kinds.get("sale", 0) + kinds.get("refund", 0),
            quarantine_rows=kinds.get("quarantine", 0),
            duplicate_file=duplicate,
        )

    @staticmethod
    def _validate_file(path: Path, allowed: set[str], max_megabytes: int) -> Path:
        file_path = path.expanduser().resolve()
        if not file_path.is_file():
            raise ImportPreflightError("Vybraný soubor neexistuje nebo není běžný soubor.")
        if file_path.suffix.casefold() not in allowed:
            raise ImportPreflightError("Soubor má nepodporovanou příponu.")
        size = file_path.stat().st_size
        if size <= 0:
            raise ImportPreflightError("Soubor je prázdný.")
        limit = int(max_megabytes) * 1024 * 1024
        if size > limit:
            raise ImportPreflightError(
                f"Soubor má {size:,} B a překračuje nastavený limit {limit:,} B."
            )
        return file_path

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


__all__ = [
    "ImportFilePreview",
    "ImportPreflightError",
    "ImportPreflightService",
    "MultipleMatchingSheets",
]
