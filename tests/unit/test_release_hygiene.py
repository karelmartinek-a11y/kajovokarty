from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_source_contains_no_todo_or_embedded_token_headers() -> None:
    forbidden = ("TO" + "DO", "FIX" + "ME", "eyJ0eXAiOiJKV1Qi", "bh_c_")
    violations = []
    for path in list((ROOT / "src").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for value in forbidden:
            if value in text:
                violations.append(f"{path.relative_to(ROOT)} contains {value}")
    assert not violations, "\n".join(violations)
