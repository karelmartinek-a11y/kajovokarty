from __future__ import annotations

from pathlib import Path


def test_drag_preview_distinguishes_allowed_partial_and_blocked_with_text_and_icon() -> None:
    models = Path("src/kajovokarty/ui/models.py").read_text(encoding="utf-8")
    matching = Path("src/kajovokarty/ui/screens/matching.py").read_text(encoding="utf-8")
    assert "set_drop_preview_provider" in models
    assert '"allowed": "✓"' in models
    assert '"partial": "ℹ"' in models
    assert '"blocked": "⛔"' in models
    assert "palette(highlight)" in models
    assert "Přiřadit část" in matching
    assert "Spárovat – přesná shoda" in matching
    assert "Nelze spojit" in matching


def test_drop_payload_remains_non_authoritative() -> None:
    source = Path("src/kajovokarty/ui/models.py").read_text(encoding="utf-8")
    payload = source.split('payload = {', 1)[1].split('}', 1)[0]
    assert "amount_minor" not in payload
    assert "currency" not in payload
    assert "entity_type" in payload
    assert "row_version" in payload


def test_table_drop_supports_exact_multiselect_in_both_directions() -> None:
    source = Path("src/kajovokarty/ui/screens/matching.py").read_text(encoding="utf-8")
    assert "preview_many(documents, sources)" in source
    assert "Vícepoložkové párování přetažením" in source
    assert 'dragged_types == {"INVOICE"}' in source
    assert "dragged_types.issubset(source_types)" in source
    assert "Částečný vícepoložkový výběr vyžaduje kontrolu rozpisu" in source


def test_partial_drop_editor_uses_human_decimal_amount_not_minor_units() -> None:
    source = Path("src/kajovokarty/ui/screens/matching.py").read_text(encoding="utf-8")
    assert "QInputDialog.getText" in source
    assert "Money.parse(value, currency).amount_minor" in source
    assert "Zadejte částku v měně dokladu" in source
    assert "Zadejte částku v minor units" not in source
