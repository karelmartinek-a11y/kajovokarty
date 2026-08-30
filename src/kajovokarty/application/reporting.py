from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from ..infrastructure.persistence.database import Database


@dataclass(frozen=True, slots=True)
class ReportDefinition:
    key: str
    label: str
    sql: str


REPORTS: dict[str, ReportDefinition] = {
    report.key: report
    for report in (
        ReportDefinition("card_paid_invoices", "Daňové doklady s úhradou kartou", "SELECT i.code AS 'Číslo dokladu',substr(i.document_date_utc,1,10) AS 'Datum dokladu',i.total_minor AS 'Částka úhrady',i.currency_code AS 'Měna částky úhrady',COALESCE(GROUP_CONCAT(DISTINCT r.internal_code),'') AS 'Číslo rezervace',COALESCE(GROUP_CONCAT(DISTINCT r.booking_reference),'') AS 'Číslo rezervace zdroje' FROM invoice i LEFT JOIN reservation_invoice_link l ON l.invoice_id=i.external_id LEFT JOIN reservation r ON r.uuid=l.reservation_id WHERE i.included=1 AND i.pay_method=2 AND i.paid_at_utc IS NOT NULL GROUP BY i.external_id,i.code,i.document_date_utc,i.total_minor,i.currency_code ORDER BY i.document_date_utc"),
        ReportDefinition("booking_payments", "Přehled potvrzení úhrad Booking.com", "SELECT b.row_hash AS 'ID',b.booking_reference AS 'Číslo rezervace zdroje',b.payout_date AS 'Datum potvrzení',b.amount_minor AS 'Částka',b.currency_code AS 'Měna',b.status AS 'Stav využití',b.raw_json AS 'Celá importovaná věta' FROM booking_payment_line b WHERE b.active_source=1 ORDER BY b.payout_date,b.row_hash"),
        ReportDefinition("terminal_payments", "Přehled potvrzení úhrad z terminálu", "SELECT c.id AS 'ID',c.seq_id AS 'SEQ ID',c.terminal_id AS 'Terminál',c.occurred_at AS 'Datum potvrzení',c.amount_minor AS 'Částka',c.currency_code AS 'Měna',c.status AS 'Stav využití',c.raw_json AS 'Celá importovaná věta' FROM card_transaction c ORDER BY c.occurred_at,c.id"),
    )
}


class ReportingService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def rows(self, report_key: str, *, limit: int | None = None) -> tuple[list[str], list[list[Any]]]:
        definition = REPORTS[report_key]
        sql = definition.sql + (" LIMIT ?" if limit is not None else "")
        rows = self.database.query(sql, (limit,) if limit is not None else ())
        if not rows:
            return [], []
        headers = list(rows[0].keys())
        return headers, [[row[key] for key in headers] for row in rows]

    def export_csv(self, report_key: str, destination: Path) -> Path:
        headers, rows = self.rows(report_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows([_safe_spreadsheet_row(row) for row in rows])
        return destination

    def export_xlsx(self, report_key: str, destination: Path) -> Path:
        headers, rows = self.rows(report_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook(write_only=False)
        sheet = workbook.active
        sheet.title = "Sestava"
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append(_safe_spreadsheet_row(row))
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            width = min(50, max(10, max(len(str(cell.value or "")) for cell in column) + 2))
            sheet.column_dimensions[column[0].column_letter].width = width
        workbook.save(destination)
        return destination

    def export_pdf(self, report_key: str, destination: Path) -> Path:
        definition = REPORTS[report_key]
        headers, rows = self.rows(report_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        styles = getSampleStyleSheet()
        story: list[Any] = [Paragraph(definition.label, styles["Title"])]
        table_data = [headers] + [[str(value if value is not None else "") for value in row] for row in rows]
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17385F")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 7), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F9")])]))
        story.append(table)
        SimpleDocTemplate(str(destination), pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24, title=definition.label).build(story)
        return destination


def _safe_spreadsheet_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _safe_spreadsheet_row(row: list[Any]) -> list[Any]:
    return [_safe_spreadsheet_value(value) for value in row]
