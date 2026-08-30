from __future__ import annotations

from pathlib import Path


def test_counterparts_panel_has_all_required_windows_and_explanations() -> None:
    source = Path("src/kajovokarty/ui/counterparts_dialog.py").read_text(encoding="utf-8")
    for label in ("7 dní", "14 dní", "30 dní", "Celé období"):
        assert label in source
    assert "evidence" in source
    assert "ObjectTableView(registry)" in source
    assert "ActionId.ADD_TO_TRAY" in source
    assert "ActionId.PAIR_SELECTED" in source


def test_expanding_manual_search_does_not_mutate_automatic_matching_settings() -> None:
    source = Path("src/kajovokarty/ui/main_window.py").read_text(encoding="utf-8")
    method = source.split("def _expand_search_window", 1)[1].split("def _show_detail", 1)[0]
    assert "settings.save" not in method
    assert "_find_counterparts" in method
