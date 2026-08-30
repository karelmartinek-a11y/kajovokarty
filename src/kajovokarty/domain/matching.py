from __future__ import annotations

import hashlib
import itertools
import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from .entities import AutoMatchCandidate, CandidateEvidence, MatchItem
from .enums import MatchStatus, ObjectSide

CancelCallback = Callable[[], bool]


class MatchingCancelled(RuntimeError):
    pass


class MatchingSearchLimit(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MatchingSettings:
    tolerance_minor: int = 1
    bands_days: tuple[int, int, int] = (2, 4, 7)
    auto_threshold: int = 95
    score_margin: int = 15
    max_combination: int = 6
    search_timeout_ms: int = 5000
    max_examined_combinations: int = 250_000

    def validate(self) -> None:
        if not 0 <= self.tolerance_minor <= 100:
            raise ValueError("Tolerance musí být 0 až 100 minor units.")
        if not 90 <= self.auto_threshold <= 100:
            raise ValueError("Auto-match threshold musí být 90 až 100.")
        if not 0 <= self.score_margin <= 100:
            raise ValueError("Score margin musí být 0 až 100.")
        if not 2 <= self.max_combination <= 10:
            raise ValueError("Maximální kombinace musí být 2 až 10.")
        if tuple(sorted(self.bands_days)) != self.bands_days or self.bands_days[0] < 0:
            raise ValueError("Datumová pásma musí být nezáporná a vzestupná.")
        if not 100 <= self.search_timeout_ms <= 60_000:
            raise ValueError("Časový limit hledání musí být 100 až 60 000 ms.")
        if not 100 <= self.max_examined_combinations <= 2_000_000:
            raise ValueError("Kombinační limit musí být 100 až 2 000 000.")


@dataclass(frozen=True, slots=True)
class CandidateCombination:
    documents: tuple[MatchItem, ...]
    sources: tuple[MatchItem, ...]
    difference_minor: int
    score: int
    evidence: tuple[CandidateEvidence, ...]

    @property
    def stable_key(self) -> tuple[object, ...]:
        date_distance = min(
            (abs((d.effective_date - s.effective_date).days) for d in self.documents for s in self.sources),
            default=999999,
        )
        ids = tuple(sorted(i.entity_id for i in (*self.documents, *self.sources)))
        return (-self.score, abs(self.difference_minor), date_distance, len(ids), ids)

    @property
    def object_ids(self) -> frozenset[str]:
        return frozenset(item.entity_id for item in (*self.documents, *self.sources))


class ReconciliationEngine:
    """Deterministic, bounded matching engine using integer minor units only."""

    def __init__(self, settings: MatchingSettings | None = None) -> None:
        self.settings = settings or MatchingSettings()
        self.settings.validate()

    def generate(self, items: Iterable[MatchItem], *, cancel: CancelCallback | None = None) -> list[AutoMatchCandidate]:
        active = [
            item
            for item in items
            if item.remaining_minor != 0
            and not item.manual_locked
            and item.status not in {MatchStatus.EXCLUDED, MatchStatus.REVIEW_REQUIRED, MatchStatus.CONFLICT}
        ]
        by_currency: dict[str, list[MatchItem]] = {}
        for item in active:
            by_currency.setdefault(item.currency, []).append(item)

        deadline = time.monotonic() + self.settings.search_timeout_ms / 1000
        examined = [0]
        result: list[AutoMatchCandidate] = []
        for currency in sorted(by_currency):
            self._checkpoint(deadline, examined, cancel)
            group = by_currency[currency]
            documents = sorted((x for x in group if x.side == ObjectSide.DOCUMENT), key=lambda x: x.entity_id)
            sources = sorted((x for x in group if x.side == ObjectSide.SOURCE), key=lambda x: x.entity_id)
            combinations = self._enumerate_combinations(documents, sources, deadline=deadline, examined=examined, cancel=cancel)
            ranked = sorted(self._apply_uniqueness(combinations), key=lambda x: x.stable_key)
            for combination in ranked:
                competitors = [other for other in ranked if other is not combination and combination.object_ids & other.object_ids]
                second_score = max((other.score for other in competitors), default=0)
                margin = combination.score - second_score
                tie = any(
                    other.score == combination.score
                    and other.stable_key[:-1] == combination.stable_key[:-1]
                    for other in competitors
                )
                facts_hash = self._facts_hash(combination)
                candidate_id = hashlib.sha256(facts_hash.encode("ascii")).hexdigest()[:24]
                can_auto = (
                    combination.score >= self.settings.auto_threshold
                    and margin >= self.settings.score_margin
                    and abs(combination.difference_minor) <= self.settings.tolerance_minor
                    and not tie
                    and not any(e.conflicting for e in combination.evidence)
                )
                alternatives = tuple(
                    self._combination_label(other)
                    for other in sorted(competitors, key=lambda x: x.stable_key)
                    if other.score >= max(0, combination.score - self.settings.score_margin)
                )
                result.append(
                    AutoMatchCandidate(
                        id=candidate_id,
                        currency=currency,
                        document_ids=tuple(d.entity_id for d in combination.documents),
                        source_refs=tuple(s.entity_id for s in combination.sources),
                        score=combination.score,
                        margin=margin,
                        difference_minor=combination.difference_minor,
                        evidence=combination.evidence,
                        alternatives=alternatives,
                        facts_hash=facts_hash,
                        can_auto_match=can_auto,
                    )
                )
        return result

    def _enumerate_combinations(
        self,
        documents: Sequence[MatchItem],
        sources: Sequence[MatchItem],
        *,
        deadline: float,
        examined: list[int],
        cancel: CancelCallback | None,
    ) -> list[CandidateCombination]:
        max_size = self.settings.max_combination
        found: dict[tuple[tuple[str, ...], tuple[str, ...]], CandidateCombination] = {}

        for document in documents:
            for source in sources:
                self._checkpoint(deadline, examined, cancel)
                if (
                    document.booking_reference
                    and source.booking_reference
                    and document.booking_reference == source.booking_reference
                    and self._within_date_window((document,), (source,))
                    and self._sign_compatible(document.remaining_minor, source.remaining_minor)
                ):
                    candidate = self._score((document,), (source,))
                    found[self._key(candidate)] = candidate

        max_docs = min(max_size, len(documents))
        max_sources = min(max_size, len(sources))
        for doc_count in range(1, max_docs + 1):
            for src_count in range(1, max_sources + 1):
                if doc_count + src_count > max_size + 1:
                    continue
                for doc_combo in itertools.combinations(documents, doc_count):
                    doc_total = sum(x.remaining_minor for x in doc_combo)
                    for src_combo in itertools.combinations(sources, src_count):
                        self._checkpoint(deadline, examined, cancel)
                        source_total = sum(x.remaining_minor for x in src_combo)
                        difference = doc_total - source_total
                        if abs(difference) > self.settings.tolerance_minor:
                            continue
                        if not self._within_date_window(doc_combo, src_combo):
                            continue
                        if not self._sign_compatible(doc_total, source_total):
                            continue
                        candidate = self._score(doc_combo, src_combo)
                        found[self._key(candidate)] = candidate
        return list(found.values())

    def _score(self, documents: Sequence[MatchItem], sources: Sequence[MatchItem]) -> CandidateCombination:
        doc_total = sum(x.remaining_minor for x in documents)
        source_total = sum(x.remaining_minor for x in sources)
        difference = doc_total - source_total
        evidence: list[CandidateEvidence] = []
        score = 0
        exact_financial = abs(difference) <= self.settings.tolerance_minor
        is_booking = any(s.entity_type == "BOOKING" for s in sources)

        if exact_financial:
            delta = 15 if is_booking else 60
            score += delta
            evidence.append(CandidateEvidence("EXACT_AMOUNT", "Přesný finanční součet", delta, str(doc_total)))

        booking_refs = {x.booking_reference for x in (*documents, *sources) if x.booking_reference}
        if is_booking and len(booking_refs) == 1 and all(x.booking_reference for x in sources):
            score += 45
            evidence.append(CandidateEvidence("BOOKING_ID", "Přesné Booking.com číslo", 45, next(iter(booking_refs))))
            direct_link = any(d.metadata.get("reservation_invoice_link") for d in documents)
            if direct_link:
                score += 30
                evidence.append(CandidateEvidence("DIRECT_LINK", "Přímá vazba rezervace–faktura", 30, "API"))
            internal_codes = {d.internal_code for d in documents if d.internal_code}
            if len(internal_codes) == 1:
                score += 5
                evidence.append(CandidateEvidence("INTERNAL_CODE", "Shodná skupina rezervace", 5, next(iter(internal_codes))))
        elif is_booking and len(booking_refs) > 1:
            evidence.append(CandidateEvidence("BOOKING_CONFLICT", "Konflikt Booking.com čísla", 0, ", ".join(sorted(booking_refs)), True))

        distance = min(abs((d.effective_date - s.effective_date).days) for d in documents for s in sources)
        if is_booking:
            date_delta = 5 if distance <= 2 else 3 if distance <= 4 else 1 if distance <= 7 else 0
        else:
            date_delta = 25 if distance <= 2 else 18 if distance <= 4 else 10 if distance <= 7 else 0
        score += date_delta
        evidence.append(CandidateEvidence("DATE", "Datumová vzdálenost", date_delta, f"{distance} dní"))

        if not is_booking and any(d.paid_at is not None for d in documents):
            score += 5
            evidence.append(CandidateEvidence("PAID_AT", "Soulad potvrzení úhrady", 5, "ano"))

        return CandidateCombination(tuple(documents), tuple(sources), difference, min(score, 100), tuple(evidence))

    @staticmethod
    def _apply_uniqueness(combinations: Sequence[CandidateCombination]) -> list[CandidateCombination]:
        result: list[CandidateCombination] = []
        for candidate in combinations:
            if any(source.entity_type == "BOOKING" for source in candidate.sources):
                result.append(candidate)
                continue
            competitors = [other for other in combinations if other is not candidate and candidate.object_ids & other.object_ids]
            if not competitors:
                evidence = (*candidate.evidence, CandidateEvidence("UNIQUE", "Jedinečnost částky nebo kombinace v okně", 10, "ano"))
                result.append(replace(candidate, score=min(100, candidate.score + 10), evidence=evidence))
            else:
                result.append(candidate)
        return result

    def _checkpoint(self, deadline: float, examined: list[int], cancel: CancelCallback | None) -> None:
        examined[0] += 1
        if cancel is not None and cancel():
            raise MatchingCancelled("Výpočet párování byl bezpečně zrušen.")
        if examined[0] > self.settings.max_examined_combinations:
            raise MatchingSearchLimit("Kombinační hledání dosáhlo bezpečnostního limitu; nevznikla žádná vazba.")
        if time.monotonic() > deadline:
            raise MatchingSearchLimit("Kombinační hledání překročilo časový limit; nevznikla žádná vazba.")

    def _within_date_window(self, documents: Sequence[MatchItem], sources: Sequence[MatchItem]) -> bool:
        max_days = self.settings.bands_days[-1]
        return any(abs((document.effective_date - source.effective_date).days) <= max_days for document in documents for source in sources)

    @staticmethod
    def _sign_compatible(document_total: int, source_total: int) -> bool:
        return document_total != 0 and source_total != 0 and (document_total > 0) == (source_total > 0)

    @staticmethod
    def _key(candidate: CandidateCombination) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return (tuple(sorted(x.entity_id for x in candidate.documents)), tuple(sorted(x.entity_id for x in candidate.sources)))

    @staticmethod
    def _facts_hash(candidate: CandidateCombination) -> str:
        payload: dict[str, Any] = {
            "documents": [(x.entity_id, x.row_version, x.remaining_minor) for x in candidate.documents],
            "sources": [(x.entity_id, x.row_version, x.remaining_minor) for x in candidate.sources],
            "difference": candidate.difference_minor,
            "score": candidate.score,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(serialized.encode("ascii")).hexdigest()

    @staticmethod
    def _combination_label(candidate: CandidateCombination) -> str:
        docs = ", ".join(x.entity_id for x in candidate.documents)
        srcs = ", ".join(x.entity_id for x in candidate.sources)
        return f"{docs} ↔ {srcs}"


def new_group_id() -> str:
    return str(uuid4())
