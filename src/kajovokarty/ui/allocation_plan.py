from __future__ import annotations

from collections.abc import Sequence

from ..application.pairing import SourceRef
from ..domain.money import Money


def format_allocation_plan(
    plan: Sequence[tuple[str, SourceRef, int]],
    currency: str,
) -> str:
    """Render an exact pair-by-pair plan for explicit user confirmation."""
    if not plan:
        return "Nebudou vytvořeny žádné jednotlivé párové vazby."
    lines = ["Přesný navržený rozpis jednotlivých vazeb:"]
    for invoice_id, source_ref, amount_minor in plan:
        lines.append(
            f"• doklad {invoice_id} ← {source_ref.source_type.value}:{source_ref.source_id}: "
            f"{Money(amount_minor, currency).format()}"
        )
    return "\n".join(lines)
