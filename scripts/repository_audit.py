from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

REQUIRED_PATHS = (
    "run.bat",
    "README.md",
    "requirements.txt",
    "requirements.lock",
    "pyproject.toml",
    "src",
    "tests",
    "resources",
    "migrations",
    "scripts",
    "docs",
    "build",
    "DELIVERY_SUMMARY.md",
    "RUN_STATUS.json",
    "AUDIT_PASS.md",
    "THIRD_PARTY_LICENSES.md",
)
TEXT_SUFFIXES = {
    ".bat",
    ".cmd",
    ".ini",
    ".iss",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sql",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
IGNORED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SECRET_PATTERNS = {
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\b"),
    "better_hotel_client_token": re.compile(r"\bbh" r"_c_[A-Za-z0-9_-]{20,}\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
}
PLACEHOLDER_PATTERN = re.compile(r"\b(?:TO" r"DO|FIX" r"ME|NotImplementedError)\b")
FORBIDDEN_INPUT_PATTERN = re.compile(r"(?:FINALNI_SSOT|NEZAVISLE_AUDITOVANO|KajovoKarty_BLOCKED_LAST_STATE)", re.IGNORECASE)
FINANCIAL_PATH_PREFIXES = (
    "src/kajovokarty/domain/",
    "src/kajovokarty/application/pairing.py",
    "src/kajovokarty/application/reconciliation.py",
    "src/kajovokarty/application/counterparts.py",
    "src/kajovokarty/infrastructure/importers/",
)


@dataclass(slots=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class AuditReport:
    root: str
    sha256_manifest: str
    passed: bool
    checks: list[Check]

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "sha256_manifest": self.sha256_manifest,
            "passed": self.passed,
            "checks": [asdict(item) for item in self.checks],
        }


def iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in IGNORED_PARTS for part in path.relative_to(root).parts):
            continue
        yield path


def text_files(root: Path) -> Iterable[Path]:
    for path in iter_files(root):
        if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 5_000_000:
            yield path


def add(checks: list[Check], name: str, passed: bool, detail: str) -> None:
    checks.append(Check(name=name, passed=passed, detail=detail))


def manifest_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in iter_files(root):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("build/audit_logs/") or relative in {
            "build/repository-audit.json",
            "build/repository-audit.txt",
        }:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def audit(root: Path, *, blocked_package: bool) -> AuditReport:
    checks: list[Check] = []

    missing = [item for item in REQUIRED_PATHS if not (root / item).exists()]
    add(checks, "required_repository_tree", not missing, "OK" if not missing else "Chybí: " + ", ".join(missing))

    cache_paths = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.name in {".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".coverage"}
    ]
    add(checks, "release_cache_hygiene", not cache_paths, "OK" if not cache_paths else ", ".join(cache_paths[:20]))

    forbidden_inputs = [
        path.relative_to(root).as_posix()
        for path in iter_files(root)
        if FORBIDDEN_INPUT_PATTERN.search(path.name) or path.suffix.lower() in {".doc", ".docx"}
    ]
    add(
        checks,
        "no_original_inputs",
        not forbidden_inputs,
        "OK" if not forbidden_inputs else ", ".join(forbidden_inputs[:20]),
    )

    secret_hits: list[str] = []
    placeholder_hits: list[str] = []
    for path in text_files(root):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                secret_hits.append(f"{relative}:{label}")
        if relative not in {"scripts/repository_audit.py", "scripts/forensic_ssot_audit.py"} and PLACEHOLDER_PATTERN.search(text):
            placeholder_hits.append(relative)
    add(checks, "secret_scan", not secret_hits, "OK" if not secret_hits else ", ".join(secret_hits[:20]))
    add(
        checks,
        "placeholder_scan",
        not placeholder_hits,
        "OK" if not placeholder_hits else ", ".join(placeholder_hits[:20]),
    )

    ast_errors: list[str] = []
    float_hits: list[str] = []
    for path in sorted([*root.glob("src/**/*.py"), *root.glob("tests/**/*.py"), *root.glob("scripts/**/*.py")]):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except SyntaxError as exc:
            ast_errors.append(f"{relative}:{exc.lineno}:{exc.msg}")
            continue
        if relative.startswith(FINANCIAL_PATH_PREFIXES):
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
                    float_hits.append(f"{relative}:{getattr(node, 'lineno', '?')}")
    add(checks, "python_ast", not ast_errors, "OK" if not ast_errors else ", ".join(ast_errors[:20]))
    add(
        checks,
        "financial_float_guard",
        not float_hits,
        "OK" if not float_hits else "float() ve finanční cestě: " + ", ".join(float_hits[:20]),
    )

    migration_files = sorted((root / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
    migration_versions = [int(path.name.split("_", 1)[0]) for path in migration_files]
    migration_ok = bool(migration_versions) and migration_versions == list(range(1, migration_versions[-1] + 1))
    add(checks, "migration_sequence", migration_ok, f"verze {migration_versions}")

    lock_lines = [
        line.strip()
        for line in (root / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    unpinned = [line for line in lock_lines if "==" not in line.partition(";")[0]]
    add(checks, "locked_dependencies", not unpinned, "OK" if not unpinned else ", ".join(unpinned))

    run_bat_path = root / "run.bat"
    run_bat_raw = run_bat_path.read_bytes()
    run_bat = run_bat_raw.decode("ascii", errors="replace")
    required_fragments = ("%~dp0", "--check", "--test", "--repair", ".venv", "scripts\\bootstrap.py")
    missing_fragments = [fragment for fragment in required_fragments if fragment not in run_bat]
    run_bat_cmd_safe = (
        run_bat_raw.startswith(b"@echo off\r\n")
        and not run_bat_raw.startswith(b"\xef\xbb\xbf")
        and b"\n" not in run_bat_raw.replace(b"\r\n", b"")
        and all(byte < 128 for byte in run_bat_raw)
    )
    run_bat_ok = not missing_fragments and run_bat_cmd_safe
    run_bat_detail = "OK – ASCII bez BOM, výhradně CRLF" if run_bat_ok else (
        "Chybí: " + ", ".join(missing_fragments) if missing_fragments else "run.bat není CMD-safe ASCII/CRLF"
    )
    add(checks, "run_bat_static_contract", run_bat_ok, run_bat_detail)

    status = json.loads((root / "RUN_STATUS.json").read_text(encoding="utf-8"))
    status_coherent = status.get("status") in {"PASS", "BLOCKED", "LIMIT"}
    if blocked_package:
        status_coherent = status_coherent and status.get("status") == "BLOCKED" and not status.get("audit_passed")
    add(checks, "run_status_coherence", status_coherent, str(status.get("status")))

    executable_files = [path.relative_to(root).as_posix() for path in iter_files(root) if path.suffix.lower() == ".exe"]
    artifact_ok = not executable_files if blocked_package else bool(executable_files)
    detail = "žádné falešné EXE v BLOCKED balíku" if artifact_ok and blocked_package else ", ".join(executable_files)
    add(checks, "windows_artifact_truthfulness", artifact_ok, detail or "Windows artefakty chybí")

    passed = all(item.passed for item in checks)
    return AuditReport(root=str(root), sha256_manifest=manifest_hash(root), passed=passed, checks=checks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Statický audit release repozitáře KájovoKarty")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--blocked-package", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--text-output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    report = audit(root, blocked_package=args.blocked_package)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    print(payload)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(payload + "\n", encoding="utf-8")
    if args.text_output:
        args.text_output.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"Repository: {root}", f"Manifest SHA-256: {report.sha256_manifest}"]
        lines.extend(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}" for check in report.checks)
        lines.append("VERDICT: " + ("PASS" if report.passed else "FAIL"))
        args.text_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
