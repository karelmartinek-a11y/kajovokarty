from __future__ import annotations

import ast
import json
from pathlib import Path

from kajovokarty.ui.component_registry import COMPONENT_SPECS, ComponentId, assert_registry_complete


def _enum_values(path: str, enum_name: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == enum_name:
            values: set[str] = set()
            for statement in node.body:
                if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                    values.add(statement.value.value)
            return values
    raise AssertionError(f"Enum {enum_name} nebyl nalezen")


def test_manifest_cardinality_and_unique_ids() -> None:
    manifest = json.loads(Path("docs/SSOT_MANIFEST.json").read_text(encoding="utf-8"))
    expected = {"acceptance_scenarios": 162, "actions": 40, "ui_components": 76}
    for key, count in expected.items():
        values = manifest[key]
        assert len(values) == count
        assert len({item["id"] for item in values}) == count


def test_component_registry_exactly_matches_ssot() -> None:
    assert_registry_complete()
    manifest = json.loads(Path("docs/SSOT_MANIFEST.json").read_text(encoding="utf-8"))
    expected = {item["id"] for item in manifest["ui_components"]}
    assert {item.value for item in ComponentId} == expected
    assert {item.value for item in COMPONENT_SPECS} == expected


def test_action_enum_exactly_matches_ssot_and_all_actions_have_specs() -> None:
    manifest = json.loads(Path("docs/SSOT_MANIFEST.json").read_text(encoding="utf-8"))
    expected = {item["id"] for item in manifest["actions"]}
    actual = _enum_values("src/kajovokarty/ui/action_registry.py", "ActionId")
    assert actual == expected
    source = Path("src/kajovokarty/ui/action_registry.py").read_text(encoding="utf-8")
    for action_id in expected:
        assert f"ActionSpec(ActionId.{action_id}," in source
        assert f"ActionId.{action_id}" in Path("src/kajovokarty/ui/main_window.py").read_text(encoding="utf-8")


def test_action_specs_exactly_match_ssot_labels_tooltips_and_shortcuts() -> None:
    manifest = json.loads(Path("docs/SSOT_MANIFEST.json").read_text(encoding="utf-8"))
    tree = ast.parse(Path("src/kajovokarty/ui/action_registry.py").read_text(encoding="utf-8"))
    actual: dict[str, dict[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ActionSpec":
            action_id = node.args[0].attr
            actual[action_id] = {
                "id": action_id,
                "label": ast.literal_eval(node.args[2]),
                "tooltip": ast.literal_eval(node.args[3]),
                "shortcut": ast.literal_eval(node.args[4]) or "",
            }
    assert actual == {item["id"]: item for item in manifest["actions"]}


def test_component_specs_exactly_match_ssot_registry_rows() -> None:
    manifest = json.loads(Path("docs/SSOT_MANIFEST.json").read_text(encoding="utf-8"))
    actual = {
        component_id.value: {
            "id": component_id.value,
            "human_name": spec.human_name,
            "view": spec.view,
            "primary_function": spec.primary_function,
            "states": "/".join(spec.states),
        }
        for component_id, spec in COMPONENT_SPECS.items()
    }
    assert actual == {item["id"]: item for item in manifest["ui_components"]}


def test_every_structural_component_is_bound_or_created_in_live_ui_code() -> None:
    manifest = json.loads(Path("docs/SSOT_MANIFEST.json").read_text(encoding="utf-8"))
    live_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/kajovokarty/ui").rglob("*.py")
        if path.name != "component_registry.py"
    )
    missing = [
        item["id"]
        for item in manifest["ui_components"]
        if f"ComponentId.{item['id']}" not in live_source
    ]
    assert not missing


def test_group_canvas_has_all_three_normative_drop_targets() -> None:
    source = Path("src/kajovokarty/ui/screens/matching.py").read_text(encoding="utf-8")
    assert "self.contextsDropped.emit(payload, target)" in source
    assert "self.container.pairing.add_to_group(" in source
    assert "allocations=plan" in source
    assert "self.container.pairing.pair(" in source
    assert "Prázdné plátno vytvoří skupinu pouze ze smíšeného výběru" in source
    assert "Cílem musí být vyrovnávací skupina nebo prázdné plátno" in source


def test_date_window_control_is_not_decorative() -> None:
    source = Path("src/kajovokarty/ui/screens/matching.py").read_text(encoding="utf-8")
    assert "counterpartsRequested" in source
    assert "self.date_window.currentData()" in source
    assert "progression = {7: 14, 14: 30, 30: 0, 0: 0}" in source
