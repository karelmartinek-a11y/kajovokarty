from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import uuid4

from ..domain.enums import AllocationMode, MatchStatus, SourceType
from ..infrastructure.importers.common import canonical_json, utc_now
from ..infrastructure.persistence.database import Database
from .audit import AuditContext, AuditService


class PairingError(ValueError):
    pass


class VersionConflict(PairingError):
    pass


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_type: SourceType
    source_id: str
    expected_row_version: int | None = None

    @property
    def object_ref(self) -> str:
        return f"{self.source_type.value}:{self.source_id}"


@dataclass(frozen=True, slots=True)
class DocumentRef:
    invoice_id: str
    expected_row_version: int | None = None


@dataclass(frozen=True, slots=True)
class DropPreview:
    allowed: bool
    exact: bool
    partial: bool
    reason: str
    currency: str | None
    assign_minor: int
    document_remaining_minor: int
    source_remaining_minor: int


class PairingDropValidationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def preview(self, document: DocumentRef, source: SourceRef) -> DropPreview:
        return self.preview_many([document], [source])

    def preview_many(self, documents: list[DocumentRef], sources: list[SourceRef]) -> DropPreview:
        if not documents or not sources:
            return DropPreview(False, False, False, "Vyberte alespoň jeden doklad a jeden zdroj úhrady.", None, 0, 0, 0)
        with self.database.read_connection() as conn:
            invoices = [_load_invoice(conn, document) for document in documents]
            source_rows = [_load_source(conn, source) for source in sources]
            for document in documents:
                lock_reason = _manual_lock_reason(conn, document.invoice_id, None)
                if lock_reason:
                    return DropPreview(False, False, False, lock_reason, None, 0, 0, 0)
            for source in sources:
                lock_reason = _manual_lock_reason(conn, None, source)
                if lock_reason:
                    return DropPreview(False, False, False, lock_reason, None, 0, 0, 0)
            document_remaining_values = [
                _invoice_remaining(conn, invoice["external_id"], invoice["total_minor"]) for invoice in invoices
            ]
            source_remaining_values = [
                _source_remaining(conn, source, source_row["amount_minor"])
                for source, source_row in zip(sources, source_rows, strict=True)
            ]
        currencies = {row["currency_code"] for row in invoices + source_rows}
        if len(currencies) != 1:
            return DropPreview(False, False, False, "Položky nelze spárovat, protože používají různé měny.", None, 0, sum(document_remaining_values), sum(source_remaining_values))
        currency = currencies.pop()
        if any(value == 0 for value in document_remaining_values):
            return DropPreview(False, False, False, "Vybraný doklad už nemá žádnou zbývající částku.", currency, 0, sum(document_remaining_values), sum(source_remaining_values))
        if any(value == 0 for value in source_remaining_values):
            return DropPreview(False, False, False, "Vybraný zdroj je už plně použit.", currency, 0, sum(document_remaining_values), sum(source_remaining_values))
        document_signs = {1 if value > 0 else -1 for value in document_remaining_values}
        source_signs = {1 if value > 0 else -1 for value in source_remaining_values}
        if len(document_signs) != 1 or len(source_signs) != 1 or document_signs != source_signs:
            return DropPreview(False, False, False, "Účetní směry vybraných dokladů a zdrojů nejsou kompatibilní.", currency, 0, sum(document_remaining_values), sum(source_remaining_values))
        document_remaining = sum(document_remaining_values)
        source_remaining = sum(source_remaining_values)
        assign = min(abs(document_remaining), abs(source_remaining)) * (1 if document_remaining > 0 else -1)
        exact = document_remaining == source_remaining
        reason = "Přesná souhrnná shoda." if exact else "Výběr je souhrnně částečný."
        return DropPreview(True, exact, not exact, reason, currency, assign, document_remaining, source_remaining)


class ManualAllocationService:
    """Transactional, audited and compensating-command pairing service."""

    def __init__(self, database: Database, audit: AuditService) -> None:
        self.database = database
        self.audit = audit

    def propose_allocations(
        self,
        documents: list[DocumentRef],
        sources: list[SourceRef],
    ) -> list[tuple[str, SourceRef, int]]:
        """Return a deterministic, non-persistent detailed allocation proposal.

        The returned plan is never authoritative by itself.  Callers must show the
        exact pair-by-pair proposal to the user and pass the accepted plan back to
        :meth:`pair`.  This prevents an N:M selection from being silently converted
        into arbitrary pairwise links merely because its aggregate totals balance.
        """
        if not documents or not sources:
            raise PairingError("Vyberte alespoň jeden doklad a jeden zdroj úhrady.")
        with self.database.read_connection() as conn:
            invoice_rows = [_load_invoice(conn, ref) for ref in documents]
            source_rows = [_load_source(conn, ref) for ref in sources]
            self._validate_pairing_selection(conn, documents, sources, invoice_rows, source_rows)
            return self._automatic_allocation_plan(conn, invoice_rows, sources, source_rows)

    def propose_group_additions(
        self,
        group_id: str,
        documents: list[DocumentRef],
        sources: list[SourceRef],
    ) -> list[tuple[str, SourceRef, int]]:
        """Return the exact detailed plan that adding members would create.

        Existing active members are included because newly added items may complete
        a previously partial group.  No database change is performed.
        """
        if not documents and not sources:
            raise PairingError("Přetažený výběr neobsahuje žádný doklad ani zdroj úhrady.")
        with self.database.read_connection() as conn:
            group = conn.execute(
                "SELECT * FROM match_group WHERE id=? AND status<>'REVERSED'", (group_id,)
            ).fetchone()
            if group is None:
                raise PairingError("Vyrovnávací skupina neexistuje nebo byla rozpojena.")
            if group["allocation_mode"] != AllocationMode.DETAILED.value:
                raise PairingError(
                    "Tato skupina nemá detailní rozpis. Nejprve ji znovu otevřete nebo "
                    "převeďte na detailní rozpis."
                )
            if group["status"] == MatchStatus.REVIEW_REQUIRED.value:
                raise PairingError(
                    "Skupina vyžaduje kontrolu změněných zdrojových dat. Nejprve ji znovu ověřte."
                )

            invoice_refs: dict[str, DocumentRef] = {
                str(row["invoice_id"]): DocumentRef(str(row["invoice_id"]))
                for row in conn.execute(
                    "SELECT invoice_id FROM match_group_document WHERE group_id=? AND active=1",
                    (group_id,),
                )
            }
            source_refs: dict[str, SourceRef] = {}
            for row in conn.execute(
                "SELECT entity_type,entity_id FROM match_group_source "
                "WHERE group_id=? AND active=1",
                (group_id,),
            ):
                ref = SourceRef(SourceType(str(row["entity_type"])), str(row["entity_id"]))
                source_refs[ref.object_ref] = ref

            for ref in documents:
                invoice_refs.setdefault(ref.invoice_id, ref)
            for ref in sources:
                source_refs.setdefault(ref.object_ref, ref)

            all_documents = list(invoice_refs.values())
            all_sources = list(source_refs.values())
            invoice_rows = [_load_invoice(conn, ref) for ref in all_documents]
            source_rows = [_load_source(conn, ref) for ref in all_sources]
            self._validate_pairing_selection(
                conn,
                all_documents,
                all_sources,
                invoice_rows,
                source_rows,
                allow_group_id=group_id,
            )
            if any(str(row["currency_code"]) != str(group["currency_code"]) for row in invoice_rows + source_rows):
                raise PairingError("Přidávané položky používají jinou měnu než cílová skupina.")
            return self._automatic_allocation_plan(conn, invoice_rows, all_sources, source_rows)

    def pair(
        self,
        documents: list[DocumentRef],
        sources: list[SourceRef],
        *,
        allocations: list[tuple[str, SourceRef, int]] | None = None,
        aggregate: bool = False,
        correlation_id: str | None = None,
        human_label: str = "Ruční párování",
    ) -> tuple[str, str]:
        if not documents or not sources:
            raise PairingError("Vyberte alespoň jeden doklad a jeden zdroj úhrady.")
        correlation = correlation_id or uuid4().hex
        command_id = uuid4().hex
        group_id = uuid4().hex
        with self.database.transaction() as conn:
            invoice_rows = [_load_invoice(conn, ref) for ref in documents]
            source_rows = [_load_source(conn, ref) for ref in sources]
            currency = self._validate_pairing_selection(
                conn, documents, sources, invoice_rows, source_rows
            )
            document_amounts = {
                row["external_id"]: _invoice_remaining(conn, row["external_id"], row["total_minor"])
                for row in invoice_rows
            }
            source_amounts = {
                ref.object_ref: _source_remaining(conn, ref, row["amount_minor"])
                for ref, row in zip(sources, source_rows, strict=True)
            }
            if any(value == 0 for value in document_amounts.values()):
                raise PairingError("Vybraný doklad už nemá žádnou zbývající částku.")
            if any(value == 0 for value in source_amounts.values()):
                raise PairingError("Vybraný zdroj už nemá žádnou zbývající částku.")
            document_total = sum(document_amounts.values())
            source_total = sum(source_amounts.values())
            difference = document_total - source_total
            mode = AllocationMode.AGGREGATE if aggregate else AllocationMode.DETAILED
            if aggregate and difference != 0:
                raise PairingError("Skupinu lze vyrovnat jako celek pouze při rozdílu 0.")
            if aggregate and allocations:
                raise PairingError(
                    "Skupinové vyrovnání nesmí obsahovat jednotlivé párové alokace."
                )
            if not aggregate and allocations is None:
                if len(documents) > 1 and len(sources) > 1:
                    raise PairingError(
                        "Více dokladů a více zdrojů vyžaduje před uložením výslovně "
                        "potvrzený detailní rozpis, nebo zvolte Vyrovnat skupinu jako celek."
                    )
                allocations = self._automatic_allocation_plan(
                    conn, invoice_rows, sources, source_rows
                )
            if not aggregate and not allocations:
                raise PairingError("Vybrané položky nemají účetně kompatibilní částku pro vytvoření vazby.")
            selected_documents = set(document_amounts)
            selected_sources = {ref.object_ref for ref in sources}
            if allocations is not None:
                for invoice_id, source_ref, _ in allocations:
                    if invoice_id not in selected_documents or source_ref.object_ref not in selected_sources:
                        raise PairingError("Plán alokací obsahuje položku mimo vybranou skupinu.")
            now = utc_now()
            initial_status = MatchStatus.AGGREGATE_MATCHED if aggregate else MatchStatus.PARTIAL
            conn.execute(
                "INSERT INTO match_group(id,currency_code,status,document_total_minor,source_total_minor,difference_minor,allocation_mode,manual_lock,source_revision_signature,created_at_utc,updated_at_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
                (group_id, currency, initial_status.value, document_total, source_total, difference, mode.value, 1, _revision_signature(invoice_rows, source_rows), now, now),
            )
            for row in invoice_rows:
                conn.execute(
                    "INSERT INTO match_group_document(group_id,invoice_id,signed_amount_minor,first_seen_utc,active,row_version) VALUES(?,?,?,?,1,1)",
                    (group_id, row["external_id"], document_amounts[row["external_id"]], now),
                )
            for ref, row in zip(sources, source_rows, strict=True):
                conn.execute(
                    "INSERT INTO match_group_source(group_id,entity_type,entity_id,signed_amount_minor,first_seen_utc,active,row_version) VALUES(?,?,?,?,?,1,1)",
                    (group_id, ref.source_type.value, ref.source_id, source_amounts[ref.object_ref], now),
                )
            allocation_ids: list[str] = []
            if not aggregate:
                assert allocations is not None
                for invoice_id, source_ref, amount_minor in allocations:
                    if amount_minor == 0:
                        continue
                    _validate_allocation(conn, invoice_id, source_ref, amount_minor)
                    allocation_id = uuid4().hex
                    conn.execute(
                        "INSERT INTO allocation(id,group_id,source_type,source_id,invoice_id,amount_minor,method,command_id,active,created_at_utc,row_version) VALUES(?,?,?,?,?,?,?,?,1,?,1)",
                        (allocation_id, group_id, source_ref.source_type.value, source_ref.source_id, invoice_id, amount_minor, "MANUAL", command_id, now),
                    )
                    allocation_ids.append(allocation_id)
            payload = {"group_id": group_id, "allocation_ids": allocation_ids}
            self._record_command(conn, command_id, correlation, "CREATE_GROUP", payload, {"group_id": group_id}, human_label)
            self.audit.append(
                conn,
                event_code="MANUAL_GROUP_CREATED",
                operation_label=human_label,
                context=AuditContext(correlation, command_id),
                object_ref=f"MATCH_GROUP:{group_id}",
                before=None,
                after={
                    "currency": currency,
                    "difference_minor": difference,
                    "allocation_mode": mode.value,
                    "documents": [row["external_id"] for row in invoice_rows],
                    "sources": [ref.object_ref for ref in sources],
                    "allocations": allocation_ids,
                },
            )
            self._recalculate_group(conn, group_id)
        return group_id, command_id


    def add_to_group(
        self,
        group_id: str,
        documents: list[DocumentRef],
        sources: list[SourceRef],
        *,
        allocations: list[tuple[str, SourceRef, int]] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        """Add ungrouped members to an existing detailed group.

        The command is atomic, audited and reversible. Aggregate/review-required groups must be
        explicitly reopened first. Pairwise allocations are created only from an exact plan that
        the caller has shown and the user has accepted; membership alone never fabricates links.
        """
        if not documents and not sources:
            raise PairingError("Přetažený výběr neobsahuje žádný doklad ani zdroj úhrady.")
        correlation = correlation_id or uuid4().hex
        command_id = uuid4().hex
        with self.database.transaction() as conn:
            group = conn.execute("SELECT * FROM match_group WHERE id=? AND status<>'REVERSED'", (group_id,)).fetchone()
            if group is None:
                raise PairingError("Vyrovnávací skupina neexistuje nebo byla rozpojena.")
            if group["allocation_mode"] != AllocationMode.DETAILED.value:
                raise PairingError("Tato skupina nemá detailní rozpis. Nejprve ji znovu otevřete nebo převeďte na detailní rozpis.")
            if group["status"] == MatchStatus.REVIEW_REQUIRED.value:
                raise PairingError("Skupina vyžaduje kontrolu změněných zdrojových dat. Nejprve ji znovu ověřte.")

            added_documents: list[str] = []
            added_sources: list[tuple[str, str]] = []
            invoice_rows: list[Any] = []
            source_rows: list[Any] = []
            source_refs: list[SourceRef] = []
            now = utc_now()

            for ref in documents:
                if conn.execute("SELECT 1 FROM match_group_document WHERE group_id=? AND invoice_id=? AND active=1", (group_id, ref.invoice_id)).fetchone():
                    continue
                external_lock = conn.execute(
                    "SELECT g.id FROM match_group g JOIN match_group_document d ON d.group_id=g.id WHERE d.invoice_id=? AND d.active=1 AND g.manual_lock=1 AND g.status<>'REVERSED' AND g.id<>? LIMIT 1",
                    (ref.invoice_id, group_id),
                ).fetchone()
                if external_lock:
                    raise PairingError("Doklad už chrání jiné ruční rozhodnutí. Nejprve otevřete jeho stávající skupinu.")
                row = _load_invoice(conn, ref)
                if row["currency_code"] != group["currency_code"]:
                    raise PairingError(f"Nelze přidat doklad v {row['currency_code']} do skupiny v {group['currency_code']}.")
                remaining = _invoice_remaining(conn, row["external_id"], row["total_minor"])
                if remaining == 0:
                    raise PairingError("Přidávaný doklad už nemá žádnou zbývající částku.")
                conn.execute(
                    "INSERT INTO match_group_document(group_id,invoice_id,signed_amount_minor,first_seen_utc,active,row_version) VALUES(?,?,?,?,1,1)",
                    (group_id, row["external_id"], remaining, now),
                )
                added_documents.append(str(row["external_id"]))

            for ref in sources:
                if conn.execute("SELECT 1 FROM match_group_source WHERE group_id=? AND entity_type=? AND entity_id=? AND active=1", (group_id, ref.source_type.value, ref.source_id)).fetchone():
                    continue
                external_lock = conn.execute(
                    "SELECT g.id FROM match_group g JOIN match_group_source m ON m.group_id=g.id WHERE m.entity_type=? AND m.entity_id=? AND m.active=1 AND g.manual_lock=1 AND g.status<>'REVERSED' AND g.id<>? LIMIT 1",
                    (ref.source_type.value, ref.source_id, group_id),
                ).fetchone()
                if external_lock:
                    raise PairingError("Zdroj úhrady už chrání jiné ruční rozhodnutí. Nejprve otevřete jeho stávající skupinu.")
                row = _load_source(conn, ref)
                if row["currency_code"] != group["currency_code"]:
                    raise PairingError(f"Nelze přidat zdroj v {row['currency_code']} do skupiny v {group['currency_code']}.")
                remaining = _source_remaining(conn, ref, row["amount_minor"])
                if remaining == 0:
                    raise PairingError("Přidávaný zdroj už nemá žádnou zbývající částku.")
                conn.execute(
                    "INSERT INTO match_group_source(group_id,entity_type,entity_id,signed_amount_minor,first_seen_utc,active,row_version) VALUES(?,?,?,?,?,1,1)",
                    (group_id, ref.source_type.value, ref.source_id, remaining, now),
                )
                added_sources.append((ref.source_type.value, ref.source_id))

            if not added_documents and not added_sources:
                raise PairingError("Všechny přetažené položky už jsou členy této skupiny.")

            for row in conn.execute("SELECT i.* FROM invoice i JOIN match_group_document d ON d.invoice_id=i.external_id WHERE d.group_id=? AND d.active=1 ORDER BY i.external_id", (group_id,)):
                invoice_rows.append(row)
            for member in conn.execute("SELECT entity_type,entity_id FROM match_group_source WHERE group_id=? AND active=1 ORDER BY entity_type,entity_id", (group_id,)):
                ref = SourceRef(SourceType(member["entity_type"]), member["entity_id"])
                source_refs.append(ref)
                source_rows.append(_load_source(conn, ref))

            plan = allocations or []
            active_documents = {str(row["external_id"]) for row in invoice_rows}
            active_sources = {ref.object_ref for ref in source_refs}
            for invoice_id, source_ref, _ in plan:
                if invoice_id not in active_documents or source_ref.object_ref not in active_sources:
                    raise PairingError(
                        "Plán alokací obsahuje položku mimo cílovou skupinu."
                    )
            allocation_ids: list[str] = []
            for invoice_id, source_ref, amount_minor in plan:
                if amount_minor == 0:
                    continue
                _validate_allocation(conn, invoice_id, source_ref, amount_minor)
                allocation_id = uuid4().hex
                conn.execute(
                    "INSERT INTO allocation(id,group_id,source_type,source_id,invoice_id,amount_minor,method,command_id,active,created_at_utc,row_version) VALUES(?,?,?,?,?,?,?,?,1,?,1)",
                    (allocation_id, group_id, source_ref.source_type.value, source_ref.source_id, invoice_id, amount_minor, "MANUAL_DROP_GROUP", command_id, now),
                )
                allocation_ids.append(allocation_id)

            payload = {
                "group_id": group_id,
                "document_ids": added_documents,
                "source_refs": [{"type": kind, "id": identifier} for kind, identifier in added_sources],
                "allocation_ids": allocation_ids,
            }
            self._record_command(conn, command_id, correlation, "ADD_GROUP_MEMBERS", payload, payload, "Přidání položek do vyrovnávací skupiny")
            self._recalculate_group(conn, group_id)
            after = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
            self.audit.append(
                conn,
                event_code="GROUP_MEMBERS_ADDED",
                operation_label="Přidat položky do vyrovnávací skupiny",
                context=AuditContext(correlation, command_id),
                object_ref=f"MATCH_GROUP:{group_id}",
                before=dict(group),
                after={**dict(after), **payload},
            )
        return command_id

    @staticmethod
    def _validate_pairing_selection(
        conn: Any,
        documents: list[DocumentRef],
        sources: list[SourceRef],
        invoice_rows: list[Any],
        source_rows: list[Any],
        *,
        allow_group_id: str | None = None,
    ) -> str:
        for ref in documents:
            reason = _manual_lock_reason(conn, ref.invoice_id, None, allow_group_id=allow_group_id)
            if reason:
                raise PairingError(reason)
        for ref in sources:
            reason = _manual_lock_reason(conn, None, ref, allow_group_id=allow_group_id)
            if reason:
                raise PairingError(reason)
        currencies = {str(row["currency_code"]) for row in invoice_rows + source_rows}
        if len(currencies) != 1:
            raise PairingError("Položky nelze spárovat, protože používají různé měny.")
        return currencies.pop()

    def pair_one(self, document: DocumentRef, source: SourceRef, amount_minor: int | None = None) -> tuple[str, str]:
        preview = PairingDropValidationService(self.database).preview(document, source)
        if not preview.allowed:
            raise PairingError(preview.reason)
        amount = preview.assign_minor if amount_minor is None else amount_minor
        return self.pair([document], [source], allocations=[(document.invoice_id, source, amount)], human_label=f"Přiřazení částky {amount}")

    def create_invoice_case(self, invoice_id: str, *, correlation_id: str | None = None) -> tuple[str, str]:
        correlation = correlation_id or uuid4().hex
        command_id = uuid4().hex
        group_id = uuid4().hex
        with self.database.transaction() as conn:
            invoice = _load_invoice(conn, DocumentRef(invoice_id))
            reason = _manual_lock_reason(conn, invoice_id, None)
            if reason:
                raise PairingError(reason)
            remaining = _invoice_remaining(conn, invoice_id, invoice["total_minor"])
            if remaining == 0:
                raise PairingError("Doklad už nemá žádnou zbývající částku.")
            now = utc_now()
            conn.execute(
                "INSERT INTO match_group(id,currency_code,status,document_total_minor,source_total_minor,difference_minor,allocation_mode,manual_lock,source_revision_signature,created_at_utc,updated_at_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
                (group_id, invoice["currency_code"], MatchStatus.UNDERPAID.value, remaining, 0, remaining, AllocationMode.DETAILED.value, 1, _revision_signature([invoice], []), now, now),
            )
            conn.execute(
                "INSERT INTO match_group_document(group_id,invoice_id,signed_amount_minor,first_seen_utc,active,row_version) VALUES(?,?,?,?,1,1)",
                (group_id, invoice_id, remaining, now),
            )
            self._record_command(conn, command_id, correlation, "CREATE_GROUP", {"group_id": group_id, "allocation_ids": []}, {"group_id": group_id}, "Vytvoření pracovního případu")
            self.audit.append(conn, event_code="MANUAL_GROUP_CREATED", operation_label="Vytvoření pracovního případu", context=AuditContext(correlation, command_id), object_ref=f"MATCH_GROUP:{group_id}", before=None, after={"invoice_id": invoice_id, "remaining_minor": remaining, "currency": invoice["currency_code"]})
            self._recalculate_group(conn, group_id)
        return group_id, command_id

    def include_invoice(self, invoice_id: str, included: bool) -> str:
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM invoice WHERE external_id=?", (invoice_id,)).fetchone()
            if row is None:
                raise PairingError("Doklad neexistuje.")
            before = bool(row["included"])
            if before == included:
                raise PairingError("Požadovaný stav kontroly už je nastavený.")
            conn.execute("UPDATE invoice SET included=?,status=?,row_version=row_version+1 WHERE external_id=?", (int(included), MatchStatus.UNMATCHED.value if included else MatchStatus.EXCLUDED.value, invoice_id))
            self._record_command(conn, command_id, correlation, "INCLUDE_INVOICE" if included else "EXCLUDE_INVOICE", {"invoice_id": invoice_id, "included": included}, {"invoice_id": invoice_id, "included": before}, "Zahrnutí do kontroly" if included else "Vyřazení z kontroly")
            self.audit.append(conn, event_code="INVOICE_INCLUDED" if included else "INVOICE_EXCLUDED", operation_label="Zahrnout do kontroly" if included else "Vyřadit z kontroly", context=AuditContext(correlation, command_id), object_ref=f"INVOICE:{invoice_id}", before={"included": before}, after={"included": included})
        return command_id

    def add_manual_settlement(
        self,
        group_id: str,
        source_type: SourceType,
        amount_minor: int,
        *,
        name: str | None = None,
        note: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[str, str]:
        if source_type not in {SourceType.CASH, SourceType.OTHER}:
            raise PairingError("Ruční zdroj musí být hotovost nebo jiný zdroj.")
        if amount_minor == 0:
            raise PairingError("Ruční zdroj nesmí mít nulovou částku.")
        correlation = correlation_id or uuid4().hex
        command_id = uuid4().hex
        settlement_id = uuid4().hex
        with self.database.transaction() as conn:
            group = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
            if group is None:
                raise PairingError("Vyrovnávací skupina neexistuje.")
            if group["allocation_mode"] != AllocationMode.DETAILED.value:
                raise PairingError("Do skupinového vyrovnání bez rozpisu nelze vložit individuální ruční zdroj. Nejprve skupinu znovu otevřete.")
            if group["status"] in {MatchStatus.MANUAL_RESOLVED.value, MatchStatus.REVIEW_REQUIRED.value, MatchStatus.REVERSED.value}:
                raise PairingError("Skupinu je nejprve nutné znovu otevřít nebo ověřit.")
            now = utc_now()
            conn.execute(
                "INSERT INTO manual_settlement(id,group_id,type,amount_minor,currency_code,name,note,active,created_at_utc,updated_at_utc,row_version) VALUES(?,?,?,?,?,?,?,1,?,?,1)",
                (settlement_id, group_id, source_type.value, amount_minor, group["currency_code"], name, note, now, now),
            )
            conn.execute(
                "INSERT INTO match_group_source(group_id,entity_type,entity_id,signed_amount_minor,first_seen_utc,active,row_version) VALUES(?,?,?,?,?,1,1)",
                (group_id, source_type.value, settlement_id, amount_minor, now),
            )
            allocation_ids = self._allocate_manual_source(conn, group_id, SourceRef(source_type, settlement_id), amount_minor, command_id)
            if not allocation_ids:
                raise PairingError("Ruční zdroj nemá účetně kompatibilní zbytek dokladu, ke kterému by jej bylo možné přiřadit.")
            self._recalculate_group(conn, group_id)
            self._record_command(
                conn,
                command_id,
                correlation,
                "ADD_MANUAL_SETTLEMENT",
                {"settlement_id": settlement_id, "group_id": group_id, "allocation_ids": allocation_ids},
                {"settlement_id": settlement_id, "group_id": group_id, "allocation_ids": allocation_ids},
                "Doplnění ručního zdroje",
            )
            self.audit.append(conn, event_code="MANUAL_SETTLEMENT_ADDED", operation_label="Doplnění jako hotovost" if source_type == SourceType.CASH else "Doplnění jiným zdrojem", context=AuditContext(correlation, command_id), object_ref=f"MANUAL:{settlement_id}", after={"amount_minor": amount_minor, "currency": group["currency_code"], "type": source_type.value, "note": note, "allocation_ids": allocation_ids})
        return settlement_id, command_id

    def edit_manual_settlement(self, settlement_id: str, amount_minor: int, *, name: str | None = None, note: str | None = None) -> str:
        if amount_minor == 0:
            raise PairingError("Ruční zdroj nesmí mít nulovou částku.")
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM manual_settlement WHERE id=? AND active=1", (settlement_id,)).fetchone()
            if row is None:
                raise PairingError("Ruční zdroj neexistuje.")
            before = dict(row)
            old_allocations = [dict(item) for item in conn.execute("SELECT * FROM allocation WHERE source_type=? AND source_id=? AND active=1 ORDER BY id", (row["type"], settlement_id))]
            conn.execute("UPDATE allocation SET active=0,row_version=row_version+1 WHERE source_type=? AND source_id=? AND active=1", (row["type"], settlement_id))
            conn.execute("UPDATE manual_settlement SET amount_minor=?,name=?,note=?,updated_at_utc=?,row_version=row_version+1 WHERE id=?", (amount_minor, name, note, utc_now(), settlement_id))
            conn.execute("UPDATE match_group_source SET signed_amount_minor=?,row_version=row_version+1 WHERE group_id=? AND entity_type=? AND entity_id=? AND active=1", (amount_minor, row["group_id"], row["type"], settlement_id))
            new_allocation_ids = self._allocate_manual_source(conn, row["group_id"], SourceRef(SourceType(row["type"]), settlement_id), amount_minor, command_id)
            if not new_allocation_ids:
                raise PairingError("Upravený ruční zdroj nemá účetně kompatibilní zbytek dokladu.")
            self._recalculate_group(conn, row["group_id"])
            payload = {"settlement_id": settlement_id, "amount_minor": amount_minor, "name": name, "note": note, "allocation_ids": new_allocation_ids}
            inverse = {"settlement_id": settlement_id, "amount_minor": row["amount_minor"], "name": row["name"], "note": row["note"], "allocation_ids": [item["id"] for item in old_allocations]}
            self._record_command(conn, command_id, correlation, "EDIT_MANUAL_SETTLEMENT", payload, inverse, "Úprava ručního zdroje")
            self.audit.append(conn, event_code="MANUAL_SETTLEMENT_EDITED", operation_label="Upravit ruční zdroj", context=AuditContext(correlation, command_id), object_ref=f"MANUAL:{settlement_id}", before={**before, "allocation_ids": inverse["allocation_ids"]}, after={**before, "amount_minor": amount_minor, "name": name, "note": note, "allocation_ids": new_allocation_ids})
        return command_id

    def remove_manual_settlement(self, settlement_id: str) -> str:
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM manual_settlement WHERE id=? AND active=1", (settlement_id,)).fetchone()
            if row is None:
                raise PairingError("Ruční zdroj neexistuje nebo už byl odebrán.")
            allocation_ids = [item[0] for item in conn.execute("SELECT id FROM allocation WHERE source_type=? AND source_id=? AND active=1", (row["type"], settlement_id))]
            self._set_manual_active(conn, settlement_id, False)
            self._record_command(conn, command_id, correlation, "REMOVE_MANUAL_SETTLEMENT", {"settlement_id": settlement_id, "allocation_ids": allocation_ids}, {"settlement_id": settlement_id, "allocation_ids": allocation_ids}, "Odebrání ručního zdroje")
            self.audit.append(conn, event_code="MANUAL_SETTLEMENT_REMOVED", operation_label="Odebrat ruční zdroj", context=AuditContext(correlation, command_id), object_ref=f"MANUAL:{settlement_id}", before=dict(row), after={**dict(row), "active": 0})
        return command_id

    def manual_resolve(self, group_id: str, *, correlation_id: str | None = None) -> str:
        correlation = correlation_id or uuid4().hex
        command_id = uuid4().hex
        with self.database.transaction() as conn:
            group = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
            if group is None:
                raise PairingError("Vyrovnávací skupina neexistuje.")
            if group["status"] == MatchStatus.REVIEW_REQUIRED.value:
                raise PairingError("Skupina vyžaduje kontrolu zdrojových změn. Nejprve zvolte Znovu ověřit skupinu.")
            before = dict(group)
            conn.execute("UPDATE match_group SET status='MANUAL_RESOLVED',manual_lock=1,updated_at_utc=?,row_version=row_version+1 WHERE id=?", (utc_now(), group_id))
            self._record_command(conn, command_id, correlation, "MANUAL_RESOLVE", {"group_id": group_id, "status": MatchStatus.MANUAL_RESOLVED.value, "manual_lock": 1}, {"group_id": group_id, "status": before["status"], "manual_lock": before["manual_lock"]}, "Označení jako ručně vyřešené")
            self.audit.append(conn, event_code="MANUAL_RESOLVED", operation_label="Označit jako ručně vyřešené", context=AuditContext(correlation, command_id), object_ref=f"MATCH_GROUP:{group_id}", before=before, after={**before, "status": "MANUAL_RESOLVED", "manual_lock": 1})
            self._refresh_group_entities(conn, group_id)
        return command_id

    def reopen_manual_resolution(self, group_id: str) -> str:
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            group = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
            if group is None:
                raise PairingError("Vyrovnávací skupina neexistuje.")
            if group["status"] != MatchStatus.MANUAL_RESOLVED.value:
                raise PairingError("Skupina není ve stavu Ručně vyřešeno.")
            before = dict(group)
            conn.execute("UPDATE match_group SET status='UNMATCHED',manual_lock=1,updated_at_utc=?,row_version=row_version+1 WHERE id=?", (utc_now(), group_id))
            self._recalculate_group(conn, group_id)
            current = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
            payload = {"group_id": group_id, "status": current["status"], "manual_lock": current["manual_lock"]}
            inverse = {"group_id": group_id, "status": before["status"], "manual_lock": before["manual_lock"]}
            self._record_command(conn, command_id, correlation, "REOPEN_MANUAL_RESOLUTION", payload, inverse, "Znovu otevření ručního vyřešení")
            self.audit.append(conn, event_code="MANUAL_RESOLUTION_REOPENED", operation_label="Znovu otevřít ruční vyřešení", context=AuditContext(correlation, command_id), object_ref=f"MATCH_GROUP:{group_id}", before=before, after=dict(current))
        return command_id

    def reopen_review_required(self, group_id: str) -> str:
        """Consciously reopen a source-revision case for manual work.

        The source revision alert is retained and marked as resolved by reopening;
        no historical allocation or audit event is deleted.
        """
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            group = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
            if group is None:
                raise PairingError("Vyrovnávací skupina neexistuje.")
            if group["status"] != MatchStatus.REVIEW_REQUIRED.value:
                raise PairingError("Skupina není ve stavu Vyžaduje kontrolu.")
            alert_ids = [
                str(row[0])
                for row in conn.execute(
                    "SELECT id FROM source_revision_alert "
                    "WHERE affected_group_ids_json LIKE ? AND state='OPEN'",
                    (f"%{group_id}%",),
                )
            ]
            before = {
                "group_id": group_id,
                "status": group["status"],
                "manual_lock": int(group["manual_lock"]),
                "review_required_reason": group["review_required_reason"],
                "alert_ids": alert_ids,
                "alerts_resolved": False,
            }
            if alert_ids:
                placeholders = ",".join("?" for _ in alert_ids)
                conn.execute(
                    f"UPDATE source_revision_alert SET state='RESOLVED',resolved_at_utc=?,"
                    f"resolution_method='REOPENED' WHERE id IN ({placeholders})",
                    (utc_now(), *alert_ids),
                )
            conn.execute(
                "UPDATE match_group SET status='UNMATCHED',review_required_reason=NULL,"
                "manual_lock=1,updated_at_utc=?,row_version=row_version+1 WHERE id=?",
                (utc_now(), group_id),
            )
            self._recalculate_group(conn, group_id)
            current = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
            after = {
                "group_id": group_id,
                "status": current["status"],
                "manual_lock": int(current["manual_lock"]),
                "review_required_reason": current["review_required_reason"],
                "alert_ids": alert_ids,
                "alerts_resolved": True,
            }
            self._record_command(
                conn,
                command_id,
                correlation,
                "REOPEN_REVIEW_REQUIRED",
                after,
                before,
                "Znovu otevření případu po změně zdroje",
            )
            self.audit.append(
                conn,
                event_code="REVIEW_CASE_REOPENED",
                operation_label="Znovu otevřít případ",
                context=AuditContext(correlation, command_id),
                object_ref=f"MATCH_GROUP:{group_id}",
                before=dict(group),
                after=dict(current),
            )
        return command_id

    def revalidate_group(self, group_id: str) -> str:
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            before = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
            if before is None:
                raise PairingError("Vyrovnávací skupina neexistuje.")
            invoices = [row[0] for row in conn.execute("SELECT invoice_id FROM match_group_document WHERE group_id=? AND active=1", (group_id,))]
            sources = [(row[0], row[1]) for row in conn.execute("SELECT entity_type,entity_id FROM match_group_source WHERE group_id=? AND active=1", (group_id,))]
            rows = [conn.execute("SELECT * FROM invoice WHERE external_id=?", (invoice_id,)).fetchone() for invoice_id in invoices]
            source_rows = [_load_source(conn, SourceRef(SourceType(kind), identifier)) for kind, identifier in sources]
            signature = _revision_signature([row for row in rows if row is not None], source_rows)
            alert_ids = [row[0] for row in conn.execute("SELECT id FROM source_revision_alert WHERE affected_group_ids_json LIKE ? AND state='OPEN'", (f'%{group_id}%',))]
            conn.execute("UPDATE match_group SET status='UNMATCHED',source_revision_signature=?,review_required_reason=NULL,updated_at_utc=?,row_version=row_version+1 WHERE id=?", (signature, utc_now(), group_id))
            if alert_ids:
                placeholders = ",".join("?" for _ in alert_ids)
                conn.execute(f"UPDATE source_revision_alert SET state='RESOLVED',resolved_at_utc=?,resolution_method='REVALIDATED' WHERE id IN ({placeholders})", (utc_now(), *alert_ids))
            self._recalculate_group(conn, group_id)
            after = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
            payload = {"group_id": group_id, "source_revision_signature": after["source_revision_signature"], "status": after["status"], "review_required_reason": after["review_required_reason"], "alert_ids": alert_ids}
            inverse = {"group_id": group_id, "source_revision_signature": before["source_revision_signature"], "status": before["status"], "review_required_reason": before["review_required_reason"], "alert_ids": alert_ids}
            self._record_command(conn, command_id, correlation, "REVALIDATE_GROUP", payload, inverse, "Znovu ověření skupiny")
            self.audit.append(conn, event_code="GROUP_REVALIDATED", operation_label="Znovu ověřit skupinu", context=AuditContext(correlation, command_id), object_ref=f"MATCH_GROUP:{group_id}", before=dict(before), after=dict(after))
        return command_id

    def edit_allocation(self, allocation_id: str, amount_minor: int, *, expected_row_version: int | None = None) -> str:
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            allocation = conn.execute("SELECT * FROM allocation WHERE id=? AND active=1", (allocation_id,)).fetchone()
            if allocation is None:
                raise PairingError("Vazba neexistuje.")
            if expected_row_version is not None and allocation["row_version"] != expected_row_version:
                raise VersionConflict("Vazba se mezitím změnila.")
            source = SourceRef(SourceType(allocation["source_type"]), allocation["source_id"])
            _validate_allocation(conn, allocation["invoice_id"], source, amount_minor, exclude_allocation=allocation_id)
            before = dict(allocation)
            conn.execute("UPDATE allocation SET amount_minor=?,row_version=row_version+1 WHERE id=?", (amount_minor, allocation_id))
            self._recalculate_group(conn, allocation["group_id"])
            self._record_command(conn, command_id, correlation, "EDIT_ALLOCATION", {"allocation_id": allocation_id, "amount_minor": amount_minor}, {"allocation_id": allocation_id, "amount_minor": before["amount_minor"]}, "Úprava přiřazené částky")
            self.audit.append(conn, event_code="ALLOCATION_EDITED", operation_label="Upravit přiřazenou částku", context=AuditContext(correlation, command_id), object_ref=f"ALLOCATION:{allocation_id}", before=before, after={**before, "amount_minor": amount_minor})
        return command_id

    def remove_allocation(self, allocation_id: str) -> str:
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            allocation = conn.execute("SELECT * FROM allocation WHERE id=? AND active=1", (allocation_id,)).fetchone()
            if allocation is None:
                raise PairingError("Vazba neexistuje nebo už byla rozpojena.")
            conn.execute("UPDATE allocation SET active=0,row_version=row_version+1 WHERE id=?", (allocation_id,))
            self._recalculate_group(conn, allocation["group_id"])
            self._record_command(conn, command_id, correlation, "REMOVE_ALLOCATION", {"allocation_id": allocation_id}, {"allocation_id": allocation_id}, "Rozpojení vazby")
            self.audit.append(conn, event_code="ALLOCATION_REMOVED", operation_label="Rozpojit tuto vazbu", context=AuditContext(correlation, command_id), object_ref=f"ALLOCATION:{allocation_id}", before=dict(allocation), after={**dict(allocation), "active": 0})
        return command_id

    def remove_group(self, group_id: str) -> str:
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            group = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
            if group is None:
                raise PairingError("Skupina neexistuje.")
            self._undo_group(conn, group_id)
            conn.execute("UPDATE match_group SET manual_lock=0 WHERE id=?", (group_id,))
            self._record_command(conn, command_id, correlation, "REMOVE_GROUP", {"group_id": group_id}, {"group_id": group_id}, "Rozpojení celé skupiny")
            self.audit.append(conn, event_code="GROUP_REMOVED", operation_label="Rozpojit celou skupinu", context=AuditContext(correlation, command_id), object_ref=f"MATCH_GROUP:{group_id}", before=dict(group), after={**dict(group), "status": "REVERSED", "manual_lock": 0})
        return command_id

    def undo(self, command_id: str) -> str:
        with self.database.transaction() as conn:
            command = conn.execute("SELECT * FROM action_command WHERE command_id=?", (command_id,)).fetchone()
            if command is None or not command["reversible"]:
                raise PairingError("Tuto změnu nelze vrátit.")
            if command["state"] != "APPLIED":
                raise PairingError("Změna už byla vrácena nebo není aktivní.")
            inverse = json.loads(command["inverse_payload_json"] or "{}")
            payload = json.loads(command["payload_json"] or "{}")
            self._apply_compensation(conn, command["command_type"], inverse, payload, undo=True)
            undo_command_id = uuid4().hex
            correlation = uuid4().hex
            now = utc_now()
            conn.execute("UPDATE action_command SET state='REVERSED',reversed_at_utc=? WHERE command_id=?", (now, command_id))
            conn.execute("INSERT INTO action_command(command_id,correlation_id,command_type,payload_json,inverse_payload_json,human_label,reversible,state,created_at_utc,applied_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?)", (undo_command_id, correlation, "UNDO", canonical_json({"original_command_id": command_id}), canonical_json({"original_command_id": command_id}), f"Vrátit: {command['human_label']}", 1, "APPLIED", now, now))
            self.audit.append(conn, event_code="COMMAND_UNDO", operation_label=f"Vrátit: {command['human_label']}", context=AuditContext(correlation, undo_command_id), object_ref=f"COMMAND:{command_id}", before={"state": "APPLIED"}, after={"state": "REVERSED"})
            return undo_command_id

    def redo(self, command_id: str) -> str:
        with self.database.transaction() as conn:
            command = conn.execute("SELECT * FROM action_command WHERE command_id=?", (command_id,)).fetchone()
            if command is None or command["state"] != "REVERSED":
                raise PairingError("Tuto změnu nelze znovu provést.")
            payload = json.loads(command["payload_json"] or "{}")
            inverse = json.loads(command["inverse_payload_json"] or "{}")
            self._apply_compensation(conn, command["command_type"], payload, inverse, undo=False)
            now = utc_now()
            redo_id = uuid4().hex
            correlation = uuid4().hex
            conn.execute("UPDATE action_command SET state='APPLIED',applied_at_utc=?,reversed_at_utc=NULL WHERE command_id=?", (now, command_id))
            conn.execute("INSERT INTO action_command(command_id,correlation_id,command_type,payload_json,inverse_payload_json,human_label,reversible,state,created_at_utc,applied_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?)", (redo_id, correlation, "REDO", canonical_json({"original_command_id": command_id}), canonical_json({"original_command_id": command_id}), f"Znovu: {command['human_label']}", 1, "APPLIED", now, now))
            self.audit.append(conn, event_code="COMMAND_REDO", operation_label=f"Znovu: {command['human_label']}", context=AuditContext(correlation, redo_id), object_ref=f"COMMAND:{command_id}", before={"state": "REVERSED"}, after={"state": "APPLIED"})
            return redo_id

    def _apply_compensation(self, conn: Any, command_type: str, target: dict[str, Any], opposite: dict[str, Any], *, undo: bool) -> None:
        if command_type == "CREATE_GROUP":
            self._undo_group(conn, target["group_id"]) if undo else self._restore_group(conn, target["group_id"])
        elif command_type == "ADD_MANUAL_SETTLEMENT":
            self._set_manual_active(conn, target["settlement_id"], not undo)
        elif command_type == "ADD_GROUP_MEMBERS":
            self._set_group_additions_active(conn, target, active=not undo)
        elif command_type == "MANUAL_RESOLVE":
            self._set_group_state(conn, target)
        elif command_type == "REOPEN_MANUAL_RESOLUTION":
            self._set_group_state(conn, target)
        elif command_type == "REOPEN_REVIEW_REQUIRED":
            self._set_review_reopen_state(conn, target)
        elif command_type == "REVALIDATE_GROUP":
            self._set_revalidation_state(conn, target, resolved=not undo)
        elif command_type == "EDIT_ALLOCATION":
            allocation = conn.execute("SELECT group_id FROM allocation WHERE id=?", (target["allocation_id"],)).fetchone()
            if allocation is None:
                raise PairingError("Vazba už neexistuje.")
            conn.execute("UPDATE allocation SET amount_minor=?,row_version=row_version+1 WHERE id=?", (target["amount_minor"], target["allocation_id"]))
            self._recalculate_group(conn, allocation["group_id"])
        elif command_type == "REMOVE_ALLOCATION":
            allocation = conn.execute("SELECT group_id FROM allocation WHERE id=?", (target["allocation_id"],)).fetchone()
            if allocation is None:
                raise PairingError("Vazba už neexistuje.")
            conn.execute("UPDATE allocation SET active=?,row_version=row_version+1 WHERE id=?", (0 if not undo else 1, target["allocation_id"]))
            self._recalculate_group(conn, allocation["group_id"])
        elif command_type == "REMOVE_GROUP":
            self._restore_group(conn, target["group_id"]) if undo else self._undo_group(conn, target["group_id"])
        elif command_type in {"INCLUDE_INVOICE", "EXCLUDE_INVOICE"}:
            included = bool(target["included"])
            conn.execute("UPDATE invoice SET included=?,status=?,row_version=row_version+1 WHERE external_id=?", (int(included), MatchStatus.UNMATCHED.value if included else MatchStatus.EXCLUDED.value, target["invoice_id"]))
        elif command_type == "EDIT_MANUAL_SETTLEMENT":
            self._restore_manual_edit(conn, target, opposite)
        elif command_type == "REMOVE_MANUAL_SETTLEMENT":
            self._set_manual_active(conn, target["settlement_id"], undo)
        else:
            raise PairingError("Pro tento typ příkazu není bezpečná kompenzace definována.")

    def _restore_manual_edit(self, conn: Any, target: dict[str, Any], opposite: dict[str, Any]) -> None:
        settlement_id = target["settlement_id"]
        row = conn.execute("SELECT group_id,type FROM manual_settlement WHERE id=?", (settlement_id,)).fetchone()
        if row is None:
            raise PairingError("Ruční zdroj už neexistuje.")
        opposite_ids = [str(value) for value in opposite.get("allocation_ids", [])]
        target_ids = [str(value) for value in target.get("allocation_ids", [])]
        if opposite_ids:
            placeholders = ",".join("?" for _ in opposite_ids)
            conn.execute(f"UPDATE allocation SET active=0,row_version=row_version+1 WHERE id IN ({placeholders})", tuple(opposite_ids))
        conn.execute("UPDATE manual_settlement SET amount_minor=?,name=?,note=?,updated_at_utc=?,row_version=row_version+1 WHERE id=?", (target["amount_minor"], target.get("name"), target.get("note"), utc_now(), settlement_id))
        conn.execute("UPDATE match_group_source SET signed_amount_minor=?,row_version=row_version+1 WHERE group_id=? AND entity_type=? AND entity_id=?", (target["amount_minor"], row["group_id"], row["type"], settlement_id))
        for allocation_id in target_ids:
            allocation = conn.execute("SELECT invoice_id,source_type,source_id,amount_minor FROM allocation WHERE id=?", (allocation_id,)).fetchone()
            if allocation is None:
                raise PairingError("Historická vazba ručního zdroje chybí.")
            _validate_allocation(conn, allocation["invoice_id"], SourceRef(SourceType(allocation["source_type"]), allocation["source_id"]), allocation["amount_minor"], exclude_allocation=allocation_id)
            conn.execute("UPDATE allocation SET active=1,row_version=row_version+1 WHERE id=?", (allocation_id,))
        self._recalculate_group(conn, row["group_id"])

    def _set_group_state(self, conn: Any, values: dict[str, Any]) -> None:
        conn.execute("UPDATE match_group SET status=?,manual_lock=?,review_required_reason=?,updated_at_utc=?,row_version=row_version+1 WHERE id=?", (values["status"], int(values.get("manual_lock", 1)), values.get("review_required_reason"), utc_now(), values["group_id"]))
        self._refresh_group_entities(conn, values["group_id"])

    def _set_review_reopen_state(self, conn: Any, values: dict[str, Any]) -> None:
        group_id = str(values["group_id"])
        conn.execute(
            "UPDATE match_group SET status=?,manual_lock=?,review_required_reason=?,"
            "updated_at_utc=?,row_version=row_version+1 WHERE id=?",
            (
                values["status"],
                int(values.get("manual_lock", 1)),
                values.get("review_required_reason"),
                utc_now(),
                group_id,
            ),
        )
        alert_ids = [str(value) for value in values.get("alert_ids", [])]
        if alert_ids:
            placeholders = ",".join("?" for _ in alert_ids)
            if values.get("alerts_resolved"):
                conn.execute(
                    f"UPDATE source_revision_alert SET state='RESOLVED',resolved_at_utc=?,"
                    f"resolution_method='REOPENED' WHERE id IN ({placeholders})",
                    (utc_now(), *alert_ids),
                )
            else:
                conn.execute(
                    f"UPDATE source_revision_alert SET state='OPEN',resolved_at_utc=NULL,"
                    f"resolution_method=NULL WHERE id IN ({placeholders})",
                    tuple(alert_ids),
                )
        self._refresh_group_entities(conn, group_id)

    def _set_revalidation_state(self, conn: Any, values: dict[str, Any], *, resolved: bool) -> None:
        conn.execute("UPDATE match_group SET status=?,source_revision_signature=?,review_required_reason=?,updated_at_utc=?,row_version=row_version+1 WHERE id=?", (values["status"], values["source_revision_signature"], values.get("review_required_reason"), utc_now(), values["group_id"]))
        alert_ids = [str(value) for value in values.get("alert_ids", [])]
        if alert_ids:
            placeholders = ",".join("?" for _ in alert_ids)
            if resolved:
                conn.execute(f"UPDATE source_revision_alert SET state='RESOLVED',resolved_at_utc=?,resolution_method='REVALIDATED' WHERE id IN ({placeholders})", (utc_now(), *alert_ids))
            else:
                conn.execute(f"UPDATE source_revision_alert SET state='OPEN',resolved_at_utc=NULL,resolution_method=NULL WHERE id IN ({placeholders})", tuple(alert_ids))
        self._refresh_group_entities(conn, values["group_id"])

    def _set_group_additions_active(self, conn: Any, values: dict[str, Any], *, active: bool) -> None:
        group_id = str(values["group_id"])
        for invoice_id in values.get("document_ids", []):
            conn.execute(
                "UPDATE match_group_document SET active=?,row_version=row_version+1 WHERE group_id=? AND invoice_id=?",
                (int(active), group_id, invoice_id),
            )
        for source in values.get("source_refs", []):
            conn.execute(
                "UPDATE match_group_source SET active=?,row_version=row_version+1 WHERE group_id=? AND entity_type=? AND entity_id=?",
                (int(active), group_id, source["type"], source["id"]),
            )
        allocation_ids = list(values.get("allocation_ids", []))
        if allocation_ids:
            placeholders = ",".join("?" for _ in allocation_ids)
            conn.execute(
                f"UPDATE allocation SET active=?,row_version=row_version+1 WHERE id IN ({placeholders})",
                (int(active), *allocation_ids),
            )
        self._recalculate_group(conn, group_id)

    def _allocate_manual_source(self, conn: Any, group_id: str, source_ref: SourceRef, amount_minor: int, command_id: str) -> list[str]:
        remaining = amount_minor
        allocation_ids: list[str] = []
        now = utc_now()
        rows = conn.execute(
            "SELECT d.invoice_id,i.total_minor FROM match_group_document d JOIN invoice i ON i.external_id=d.invoice_id WHERE d.group_id=? AND d.active=1 ORDER BY i.document_date_utc,i.external_id",
            (group_id,),
        ).fetchall()
        for row in rows:
            if remaining == 0:
                break
            document_remaining = _invoice_remaining(conn, row["invoice_id"], row["total_minor"])
            if document_remaining == 0 or document_remaining * remaining <= 0:
                continue
            amount = min(abs(document_remaining), abs(remaining)) * (1 if remaining > 0 else -1)
            _validate_allocation(conn, row["invoice_id"], source_ref, amount)
            allocation_id = uuid4().hex
            conn.execute(
                "INSERT INTO allocation(id,group_id,source_type,source_id,invoice_id,amount_minor,method,command_id,active,created_at_utc,row_version) VALUES(?,?,?,?,?,?,?,?,1,?,1)",
                (allocation_id, group_id, source_ref.source_type.value, source_ref.source_id, row["invoice_id"], amount, f"MANUAL_{source_ref.source_type.value}", command_id, now),
            )
            allocation_ids.append(allocation_id)
            remaining -= amount
        return allocation_ids

    def _automatic_allocation_plan(self, conn: Any, invoice_rows: list[Any], refs: list[SourceRef], source_rows: list[Any]) -> list[tuple[str, SourceRef, int]]:
        documents = [[row["external_id"], _invoice_remaining(conn, row["external_id"], row["total_minor"])] for row in sorted(invoice_rows, key=lambda item: item["external_id"])]
        source_pairs = sorted(zip(refs, source_rows, strict=True), key=lambda item: item[0].object_ref)
        sources = [[ref, _source_remaining(conn, ref, row["amount_minor"])] for ref, row in source_pairs]
        result: list[tuple[str, SourceRef, int]] = []
        for document in documents:
            for source in sources:
                if document[1] == 0:
                    break
                if source[1] == 0 or document[1] * source[1] <= 0:
                    continue
                amount = min(abs(document[1]), abs(source[1])) * (1 if document[1] > 0 else -1)
                result.append((str(document[0]), source[0], amount))
                document[1] -= amount
                source[1] -= amount
        return result

    @staticmethod
    def _record_command(conn: Any, command_id: str, correlation: str, command_type: str, payload: dict[str, Any], inverse: dict[str, Any], label: str) -> None:
        now = utc_now()
        conn.execute("INSERT INTO action_command(command_id,correlation_id,command_type,payload_json,inverse_payload_json,human_label,reversible,state,created_at_utc,applied_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?)", (command_id, correlation, command_type, canonical_json(payload), canonical_json(inverse), label, 1, "APPLIED", now, now))

    @staticmethod
    def _recalculate_group(conn: Any, group_id: str) -> None:
        group = conn.execute("SELECT * FROM match_group WHERE id=?", (group_id,)).fetchone()
        if group is None:
            return
        document_total = int(conn.execute("SELECT COALESCE(SUM(signed_amount_minor),0) FROM match_group_document WHERE group_id=? AND active=1", (group_id,)).fetchone()[0])
        source_total = int(conn.execute("SELECT COALESCE(SUM(signed_amount_minor),0) FROM match_group_source WHERE group_id=? AND active=1", (group_id,)).fetchone()[0])
        difference = document_total - source_total
        active_members = int(conn.execute("SELECT (SELECT COUNT(*) FROM match_group_document WHERE group_id=? AND active=1)+(SELECT COUNT(*) FROM match_group_source WHERE group_id=? AND active=1)", (group_id, group_id)).fetchone()[0])
        if active_members == 0:
            status = MatchStatus.REVERSED
        elif group["status"] == MatchStatus.REVIEW_REQUIRED.value and group["review_required_reason"]:
            status = MatchStatus.REVIEW_REQUIRED
        elif group["status"] == MatchStatus.MANUAL_RESOLVED.value:
            status = MatchStatus.MANUAL_RESOLVED
        elif group["allocation_mode"] == AllocationMode.AGGREGATE.value:
            status = MatchStatus.AGGREGATE_MATCHED if difference == 0 else MatchStatus.CONFLICT
        else:
            allocations = conn.execute("SELECT amount_minor,method FROM allocation WHERE group_id=? AND active=1", (group_id,)).fetchall()
            allocated_total = sum(int(row["amount_minor"]) for row in allocations)
            document_uncovered = document_total - allocated_total
            source_unassigned = source_total - allocated_total
            if document_uncovered == 0 and source_unassigned == 0 and difference == 0:
                auto = bool(allocations) and all(row["method"] == "AUTO" for row in allocations) and not group["manual_lock"]
                status = MatchStatus.AUTO_MATCHED if auto else MatchStatus.MANUAL_MATCHED
            elif allocations:
                status = MatchStatus.PARTIAL
            elif difference > 0:
                status = MatchStatus.UNDERPAID
            elif difference < 0:
                status = MatchStatus.OVERPAID
            else:
                status = MatchStatus.UNMATCHED
        conn.execute("UPDATE match_group SET document_total_minor=?,source_total_minor=?,difference_minor=?,status=?,updated_at_utc=?,row_version=row_version+1 WHERE id=?", (document_total, source_total, difference, status.value, utc_now(), group_id))
        ManualAllocationService._refresh_group_entities(conn, group_id)

    @staticmethod
    def _refresh_group_entities(conn: Any, group_id: str) -> None:
        invoice_ids = [row[0] for row in conn.execute("SELECT invoice_id FROM match_group_document WHERE group_id=?", (group_id,))]
        source_refs = [SourceRef(SourceType(row[0]), row[1]) for row in conn.execute("SELECT entity_type,entity_id FROM match_group_source WHERE group_id=?", (group_id,))]
        _refresh_entities(conn, invoice_ids, source_refs)

    def _undo_group(self, conn: Any, group_id: str) -> None:
        invoice_ids = [row[0] for row in conn.execute("SELECT invoice_id FROM match_group_document WHERE group_id=?", (group_id,))]
        source_refs = [SourceRef(SourceType(row[0]), row[1]) for row in conn.execute("SELECT entity_type,entity_id FROM match_group_source WHERE group_id=?", (group_id,))]
        conn.execute("UPDATE allocation SET active=0,row_version=row_version+1 WHERE group_id=?", (group_id,))
        conn.execute("UPDATE manual_settlement SET active=0,row_version=row_version+1,updated_at_utc=? WHERE group_id=?", (utc_now(), group_id))
        conn.execute("UPDATE match_group_document SET active=0,row_version=row_version+1 WHERE group_id=?", (group_id,))
        conn.execute("UPDATE match_group_source SET active=0,row_version=row_version+1 WHERE group_id=?", (group_id,))
        conn.execute("UPDATE match_group SET status='REVERSED',updated_at_utc=?,row_version=row_version+1 WHERE id=?", (utc_now(), group_id))
        _refresh_entities(conn, invoice_ids, source_refs)

    def _restore_group(self, conn: Any, group_id: str) -> None:
        conn.execute("UPDATE match_group_document SET active=1,row_version=row_version+1 WHERE group_id=?", (group_id,))
        conn.execute("UPDATE match_group_source SET active=1,row_version=row_version+1 WHERE group_id=?", (group_id,))
        conn.execute("UPDATE allocation SET active=1,row_version=row_version+1 WHERE group_id=?", (group_id,))
        conn.execute("UPDATE manual_settlement SET active=1,row_version=row_version+1,updated_at_utc=? WHERE group_id=?", (utc_now(), group_id))
        conn.execute("UPDATE match_group SET manual_lock=1 WHERE id=?", (group_id,))
        self._recalculate_group(conn, group_id)

    def _set_manual_active(self, conn: Any, settlement_id: str, active: bool) -> None:
        row = conn.execute("SELECT group_id,type FROM manual_settlement WHERE id=?", (settlement_id,)).fetchone()
        if row is None:
            raise PairingError("Ruční zdroj neexistuje.")
        conn.execute("UPDATE manual_settlement SET active=?,updated_at_utc=?,row_version=row_version+1 WHERE id=?", (int(active), utc_now(), settlement_id))
        conn.execute("UPDATE match_group_source SET active=?,row_version=row_version+1 WHERE group_id=? AND entity_type=? AND entity_id=?", (int(active), row["group_id"], row["type"], settlement_id))
        conn.execute("UPDATE allocation SET active=?,row_version=row_version+1 WHERE source_type=? AND source_id=?", (int(active), row["type"], settlement_id))
        self._recalculate_group(conn, row["group_id"])


def _load_invoice(conn: Any, ref: DocumentRef) -> Any:
    row = conn.execute("SELECT * FROM invoice WHERE external_id=? AND included=1", (ref.invoice_id,)).fetchone()
    if row is None:
        raise PairingError("Doklad neexistuje nebo je vyřazen z kontroly.")
    if ref.expected_row_version is not None and row["row_version"] != ref.expected_row_version:
        raise VersionConflict("Doklad se mezitím změnil. Načtěte aktuální stav.")
    return row


def _load_source(conn: Any, ref: SourceRef) -> Any:
    if ref.source_type == SourceType.BOOKING:
        row = conn.execute("SELECT row_hash AS id,amount_minor,currency_code,row_version,status,content_hash FROM booking_payment_line WHERE row_hash=?", (ref.source_id,)).fetchone()
    elif ref.source_type == SourceType.CARD:
        row = conn.execute("SELECT id,amount_minor,currency_code,row_version,status,content_hash FROM card_transaction WHERE id=? OR (terminal_id || '|' || seq_id)=?", (ref.source_id, ref.source_id)).fetchone()
    else:
        row = conn.execute("SELECT id,amount_minor,currency_code,row_version,'MANUAL' AS status,'' AS content_hash FROM manual_settlement WHERE id=? AND active=1", (ref.source_id,)).fetchone()
    if row is None:
        raise PairingError("Zdroj úhrady neexistuje.")
    if ref.expected_row_version is not None and row["row_version"] != ref.expected_row_version:
        raise VersionConflict("Zdroj se mezitím změnil. Načtěte aktuální stav.")
    return row


def _manual_lock_reason(
    conn: Any,
    invoice_id: str | None,
    source: SourceRef | None,
    *,
    allow_group_id: str | None = None,
) -> str | None:
    excluded_group = " AND g.id<>?" if allow_group_id else ""
    if invoice_id is not None:
        row = conn.execute(
            "SELECT g.id FROM match_group g JOIN match_group_document d ON d.group_id=g.id "
            "WHERE d.invoice_id=? AND d.active=1 AND g.manual_lock=1 "
            f"AND g.status<>'REVERSED'{excluded_group} LIMIT 1",
            (invoice_id, allow_group_id) if allow_group_id else (invoice_id,),
        ).fetchone()
    elif source is not None:
        row = conn.execute(
            "SELECT g.id FROM match_group g JOIN match_group_source s ON s.group_id=g.id "
            "WHERE s.entity_type=? AND s.entity_id=? AND s.active=1 AND g.manual_lock=1 "
            f"AND g.status<>'REVERSED'{excluded_group} LIMIT 1",
            (source.source_type.value, source.source_id, allow_group_id)
            if allow_group_id
            else (source.source_type.value, source.source_id),
        ).fetchone()
    else:
        row = None
    if row is None:
        return None
    return "Tuto položku chrání ruční rozhodnutí. Nejprve otevřete její skupinu a zvolte Upravit ruční párování."


def _invoice_remaining(conn: Any, invoice_id: str, total_minor: int) -> int:
    allocated = conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM allocation WHERE invoice_id=? AND active=1", (invoice_id,)).fetchone()[0]
    return int(total_minor) - int(allocated)


def _source_remaining(conn: Any, ref: SourceRef, amount_minor: int) -> int:
    allocated = conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM allocation WHERE source_type=? AND source_id=? AND active=1", (ref.source_type.value, ref.source_id)).fetchone()[0]
    return int(amount_minor) - int(allocated)


def _validate_allocation(conn: Any, invoice_id: str, source_ref: SourceRef, amount_minor: int, exclude_allocation: str | None = None) -> None:
    invoice = _load_invoice(conn, DocumentRef(invoice_id))
    source = _load_source(conn, source_ref)
    if invoice["currency_code"] != source["currency_code"]:
        raise PairingError("Položky nelze spárovat, protože používají různé měny.")
    excluded = " AND id<>?" if exclude_allocation else ""
    params_doc: tuple[Any, ...] = (invoice_id, exclude_allocation) if exclude_allocation else (invoice_id,)
    params_src: tuple[Any, ...] = (source_ref.source_type.value, source_ref.source_id, exclude_allocation) if exclude_allocation else (source_ref.source_type.value, source_ref.source_id)
    doc_used = conn.execute(f"SELECT COALESCE(SUM(amount_minor),0) FROM allocation WHERE invoice_id=? AND active=1{excluded}", params_doc).fetchone()[0]
    src_used = conn.execute(f"SELECT COALESCE(SUM(amount_minor),0) FROM allocation WHERE source_type=? AND source_id=? AND active=1{excluded}", params_src).fetchone()[0]
    doc_remaining = int(invoice["total_minor"]) - int(doc_used)
    src_remaining = int(source["amount_minor"]) - int(src_used)
    if amount_minor == 0 or amount_minor * doc_remaining <= 0 or amount_minor * src_remaining <= 0:
        raise PairingError("Zadaná částka není účetně kompatibilní se zbývající částkou.")
    if abs(amount_minor) > abs(doc_remaining) or abs(amount_minor) > abs(src_remaining):
        raise PairingError("Zadaná částka je vyšší než zbývající částka zdroje nebo dokladu.")


def _refresh_entities(conn: Any, invoice_ids: Iterable[str], source_refs: Iterable[SourceRef]) -> None:
    for invoice_id in set(invoice_ids):
        row = conn.execute("SELECT total_minor,included FROM invoice WHERE external_id=?", (invoice_id,)).fetchone()
        if row is None:
            continue
        if not row["included"]:
            status = MatchStatus.EXCLUDED.value
        else:
            group_statuses = {item[0] for item in conn.execute("SELECT g.status FROM match_group g JOIN match_group_document d ON d.group_id=g.id WHERE d.invoice_id=? AND d.active=1 AND g.status<>'REVERSED'", (invoice_id,))}
            status = _object_status(conn, "invoice_id", invoice_id, int(row["total_minor"]), group_statuses)
        conn.execute("UPDATE invoice SET status=?,row_version=row_version+1 WHERE external_id=?", (status, invoice_id))
    for ref in set(source_refs):
        if ref.source_type not in {SourceType.BOOKING, SourceType.CARD}:
            continue
        source = _load_source(conn, ref)
        group_statuses = {item[0] for item in conn.execute("SELECT g.status FROM match_group g JOIN match_group_source s ON s.group_id=g.id WHERE s.entity_type=? AND s.entity_id=? AND s.active=1 AND g.status<>'REVERSED'", (ref.source_type.value, ref.source_id))}
        status = _object_status(conn, "source", ref.object_ref, int(source["amount_minor"]), group_statuses)
        table = "booking_payment_line" if ref.source_type == SourceType.BOOKING else "card_transaction"
        key = "row_hash" if ref.source_type == SourceType.BOOKING else "id"
        conn.execute(f"UPDATE {table} SET status=?,row_version=row_version+1 WHERE {key}=?", (status, ref.source_id))


def _object_status(conn: Any, kind: str, identifier: str, total_minor: int, group_statuses: set[str]) -> str:
    if MatchStatus.REVIEW_REQUIRED.value in group_statuses:
        return MatchStatus.REVIEW_REQUIRED.value
    if MatchStatus.MANUAL_RESOLVED.value in group_statuses:
        return MatchStatus.MANUAL_RESOLVED.value
    if MatchStatus.AGGREGATE_MATCHED.value in group_statuses:
        return MatchStatus.AGGREGATE_MATCHED.value
    if kind == "invoice_id":
        used_rows = conn.execute("SELECT amount_minor,method FROM allocation WHERE invoice_id=? AND active=1", (identifier,)).fetchall()
    else:
        source_type, source_id = identifier.split(":", 1)
        used_rows = conn.execute("SELECT amount_minor,method FROM allocation WHERE source_type=? AND source_id=? AND active=1", (source_type, source_id)).fetchall()
    used = sum(int(row["amount_minor"]) for row in used_rows)
    remaining = total_minor - used
    if remaining == 0 and used_rows:
        return MatchStatus.AUTO_MATCHED.value if all(row["method"] == "AUTO" for row in used_rows) else MatchStatus.MANUAL_MATCHED.value
    if used_rows:
        return MatchStatus.PARTIAL.value
    return MatchStatus.UNMATCHED.value


def _revision_signature(invoice_rows: list[Any], source_rows: list[Any]) -> str:
    payload = [(row["content_hash"], row["row_version"]) for row in invoice_rows + source_rows]
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()
