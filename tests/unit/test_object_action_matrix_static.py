from __future__ import annotations

import ast
import json
from pathlib import Path


def _spec_object_types() -> dict[str, set[str]]:
    tree = ast.parse(Path("src/kajovokarty/ui/action_registry.py").read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "ActionSpec"):
            continue
        action = node.args[0]
        if not isinstance(action, ast.Attribute):
            continue
        object_types = node.args[5]
        if isinstance(object_types, ast.Call) and isinstance(object_types.func, ast.Name) and object_types.func.id == "frozenset":
            values = ast.literal_eval(object_types.args[0])
        else:
            values = ast.literal_eval(object_types)
        result[action.attr] = set(values)
    return result


def test_appendix_b_object_action_matrix_is_covered_by_central_registry() -> None:
    contract = json.loads(Path("docs/OBJECT_ACTION_MATRIX.json").read_text(encoding="utf-8"))["objects"]
    specs = _spec_object_types()
    missing: list[str] = []
    for object_type, row in contract.items():
        for action_id in row["required_actions"]:
            if action_id not in specs:
                missing.append(f"{object_type}:{action_id}:missing-spec")
            elif object_type not in specs[action_id]:
                missing.append(f"{object_type}:{action_id}:not-applicable")
    assert not missing


def test_appendix_b_technical_objects_are_searchable_and_have_live_handlers() -> None:
    search_source = Path("src/kajovokarty/application/search.py").read_text(encoding="utf-8")
    main_source = Path("src/kajovokarty/ui/main_window.py").read_text(encoding="utf-8")
    for object_type in (
        "ALLOCATION",
        "IMPORT_RUN",
        "QUARANTINE",
        "AUDIT",
        "CANDIDATE",
        "BOOKING_REFERENCE",
        "BILL",
        "BILL_ITEM",
        "REVISION_ALERT",
    ):
        assert f'{object_type}:' in search_source
        assert f'"{object_type}"' in main_source


def test_dashboard_freshness_and_top_status_controls_are_not_decorative() -> None:
    dashboard = Path("src/kajovokarty/ui/screens/dashboard.py").read_text(encoding="utf-8")
    main = Path("src/kajovokarty/ui/main_window.py").read_text(encoding="utf-8")
    imports = Path("src/kajovokarty/ui/screens/imports.py").read_text(encoding="utf-8")
    assert "self.freshness = ObjectTableView(self.registry)" in dashboard
    assert "self.freshness.activated.connect(self._freshness_activated)" in dashboard
    assert "self.dashboard.openImportRun.connect(self._open_import_run)" in main
    assert "self.source_status.clicked.connect" in main
    assert "self.last_run.clicked.connect(self._open_last_run)" in main
    assert "def focus_run(self, run_id: str) -> bool:" in imports
