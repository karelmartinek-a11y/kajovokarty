from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_windows_workflow_covers_required_dpi_matrix_and_frozen_build() -> None:
    workflow = (ROOT / ".github" / "workflows" / "windows-release.yml").read_text(encoding="utf-8")
    for scale in ('"1"', '"1.25"', '"1.5"', '"1.75"', '"2"'):
        assert scale in workflow
    assert "gui_layout_audit.py" in workflow
    assert "scripts\\build_release.py" in workflow
    assert "run.bat --check" in workflow
    assert "run.bat --test" in workflow
    assert "installer_smoke.ps1" in workflow


def test_gui_audit_checks_focus_geometry_and_all_pages() -> None:
    source = (ROOT / "scripts" / "gui_layout_audit.py").read_text(encoding="utf-8")
    assert "window.navigation.count()" in source
    assert "FocusPolicy.NoFocus" in source
    assert "window.grab().save" in source
    assert '"status": "PASS" if not failures else "FAIL"' in source
