import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCIAL_FILES = [ROOT / "src" / "kajovokarty" / "domain", ROOT / "src" / "kajovokarty" / "application" / "pairing.py", ROOT / "src" / "kajovokarty" / "domain" / "matching.py"]


def test_financial_domain_does_not_call_float() -> None:
    violations = []
    paths = []
    for item in FINANCIAL_FILES:
        paths.extend(item.rglob("*.py") if item.is_dir() else [item])
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not violations, "Finanční doména používá float(): " + ", ".join(violations)
