from __future__ import annotations

from pathlib import Path


def test_quarantine_is_a_live_registry_backed_workbench() -> None:
    source = Path("src/kajovokarty/ui/quarantine_dialog.py").read_text(encoding="utf-8")
    assert "ObjectTableView(registry)" in source
    assert "ActionId.RESOLVE_QUARANTINE" in source
    assert "ActionId.SHOW_SOURCE_ROW" in source
    assert "ActionId.SHOW_AUDIT" in source
    assert "raw_json" in source
    assert "reason_filter" in source
    assert "state_filter" in source


def test_import_screen_opens_quarantine_dialog_not_message_dump() -> None:
    source = Path("src/kajovokarty/ui/screens/imports.py").read_text(encoding="utf-8")
    assert "QuarantineDialog" in source
    method = source.split("def show_quarantine", 1)[1].split("def retry_selected", 1)[0]
    assert "QMessageBox.information" not in method
