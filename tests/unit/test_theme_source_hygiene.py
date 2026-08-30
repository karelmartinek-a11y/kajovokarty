from __future__ import annotations

from pathlib import Path

from scripts.ui_contrast_audit import audit_source


def test_ui_colors_are_centralized_and_legacy_fault_is_absent() -> None:
    root = Path(__file__).resolve().parents[2]
    result = audit_source(root)
    assert result["status"] == "PASS", result
