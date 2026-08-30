import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_action_registry_has_all_normative_ids_without_duplicate_values() -> None:
    path = ROOT / "src" / "kajovokarty" / "ui" / "action_registry.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ids = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ActionId":
            for statement in node.body:
                if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name):
                    ids.append(statement.targets[0].id)
    required = {
        "OPEN_DETAIL", "OPEN_IN_MATCHING", "ADD_TO_TRAY", "PAIR_SELECTED", "CREATE_GROUP", "SPLIT_SOURCE",
        "SPLIT_DOCUMENT", "EDIT_ALLOCATION", "REMOVE_ALLOCATION", "REMOVE_GROUP", "ACCEPT_CANDIDATE",
        "REJECT_CANDIDATE", "MARK_CASH", "MARK_OTHER", "MANUAL_RESOLVE", "INCLUDE", "EXCLUDE",
        "SHOW_RELATIONS", "SHOW_AUDIT", "SHOW_SOURCE_ROW", "COPY_PRIMARY_ID", "COPY_ALL_IDS",
        "EXPORT_SELECTION", "UNDO", "REDO", "RETRY_RUN", "OPEN_QUARANTINE", "RESOLVE_QUARANTINE",
        "REFRESH_OBJECT", "FIND_COUNTERPARTS", "EXPAND_SEARCH_WINDOW", "BALANCE_AS_GROUP", "REVALIDATE_GROUP",
        "EDIT_MANUAL_SETTLEMENT", "REMOVE_MANUAL_SETTLEMENT", "REOPEN_MANUAL_RESOLUTION", "REMOVE_FROM_TRAY", "CLEAR_TRAY",
    }
    assert required <= set(ids)
    assert len(ids) == len(set(ids))


def _action_ids_from_enum(tree: ast.AST) -> set[str]:
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.ClassDef) and node.name == "ActionId":
            return {
                statement.targets[0].id
                for statement in node.body
                if isinstance(statement, ast.Assign)
                and statement.targets
                and isinstance(statement.targets[0], ast.Name)
            }
    return set()


def test_every_action_id_has_exactly_one_spec_and_main_handler_branch() -> None:
    registry_path = ROOT / "src" / "kajovokarty" / "ui" / "action_registry.py"
    registry_tree = ast.parse(registry_path.read_text(encoding="utf-8"))
    action_ids = _action_ids_from_enum(registry_tree)
    spec_ids: list[str] = []
    for node in ast.walk(registry_tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "ActionSpec"):
            continue
        first = node.args[0] if node.args else None
        if (
            isinstance(first, ast.Attribute)
            and isinstance(first.value, ast.Name)
            and first.value.id == "ActionId"
        ):
            spec_ids.append(first.attr)
    assert set(spec_ids) == action_ids
    assert len(spec_ids) == len(set(spec_ids))

    handler_path = ROOT / "src" / "kajovokarty" / "ui" / "main_window.py"
    handler_tree = ast.parse(handler_path.read_text(encoding="utf-8"))
    handled = {
        node.attr
        for node in ast.walk(handler_tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ActionId"
    }
    assert action_ids <= handled


def test_live_screens_build_object_menus_from_central_registry() -> None:
    screens = ROOT / "src" / "kajovokarty" / "ui" / "screens"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in screens.glob("*.py"))
    assert "registry.build_menu" in sources
    assert "ObjectTableView(registry)" in sources
    # A live screen must not create its own independently named object QAction.
    assert "QAction(" not in sources
