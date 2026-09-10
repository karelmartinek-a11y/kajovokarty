from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree

ACCEPTANCE_PATTERN = re.compile(r"\b(?:API|BOOK|BANK|MATCH|UI|DATA|OPS|BUILD|INV)-\d{2}\b")
NEW_ACCEPTANCE_PATTERN = re.compile(r"\b(?:IMP|REC|AUTO|UI)-\d{3}\b")
SECRET_PATTERNS = {
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\b"),
    "better_hotel_client_token": re.compile(r"\bbh" r"_c_[A-Za-z0-9_-]{20,}\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
}
TEXT_SUFFIXES = {".bat", ".cmd", ".ini", ".iss", ".json", ".md", ".ps1", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"}
IGNORED = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
REQUIRED_ROOT = {
    "run.bat", "README.md", "requirements.txt", "requirements.lock", "pyproject.toml",
    "src", "tests", "resources", "migrations", "scripts", "docs", "build",
    "DELIVERY_SUMMARY.md", "RUN_STATUS.json", "AUDIT_PASS.md", "THIRD_PARTY_LICENSES.md",
}


@dataclass(slots=True)
class Finding:
    id: str
    area: str
    status: str
    detail: str
    evidence: list[str]


class ForensicAudit:
    def __init__(self, root: Path, ssot: Path) -> None:
        self.root = root.resolve()
        self.ssot = ssot.resolve()
        self.findings: list[Finding] = []
        self.ssot_text = self._read_ssot(self.ssot)
        self.ssot_compact = re.sub(r"\s+", "", self.ssot_text)
        self.manifest = json.loads((self.root / "docs/SSOT_MANIFEST.json").read_text(encoding="utf-8"))

    def add(self, finding_id: str, area: str, status: str, detail: str, *evidence: str) -> None:
        self.findings.append(Finding(finding_id, area, status, detail, list(evidence)))

    @staticmethod
    def _read_ssot(path: Path) -> str:
        if path.suffix.casefold() in {".md", ".txt"}:
            return path.read_text(encoding="utf-8")
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        texts: list[str] = []
        for element in root.iter():
            if element.tag.endswith("}t") and element.text:
                texts.append(element.text)
            elif element.tag.endswith("}tab"):
                texts.append("\t")
            elif element.tag.endswith("}br"):
                texts.append("\n")
        return "\n".join(texts)

    @property
    def is_new_ssot(self) -> bool:
        return self.ssot.name.startswith("KajovoKarty_SSOT_nova_rekonsiliace")

    @staticmethod
    def _iter_files(root: Path):
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in IGNORED for part in path.relative_to(root).parts):
                continue
            yield path

    @staticmethod
    def _enum_values(tree: ast.Module, class_name: str) -> list[str]:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                values: list[str] = []
                for statement in node.body:
                    if (
                        isinstance(statement, ast.Assign)
                        and isinstance(statement.value, ast.Constant)
                        and isinstance(statement.value.value, str)
                    ):
                        values.append(statement.value.value)
                return values
        return []

    def check_ssot_identity(self) -> None:
        if self.is_new_ssot:
            required = [
                "# K", "# 7.", "# 11.", "# 12.", "# 28.",
            ]
            missing = [phrase for phrase in required if phrase not in self.ssot_text]
            self.add("SSOT-NEW-IDENTITY", "SSOT", "PASS" if not missing else "FAIL", f"Nový SSOT; chybí={missing}", str(self.ssot))
            return
        required_phrases = [
            "KájovoKarty", "Finální jednotný SSOT", "Verze dokumentu", "1.1",
            "Tento jediný dokument je autoritativní zdroj pravdy",
        ]
        missing = [phrase for phrase in required_phrases if phrase not in self.ssot_text]
        self.add(
            "SSOT-IDENTITY", "SSOT", "PASS" if not missing else "FAIL",
            "Autoritativní SSOT 1.1 byl načten a identifikován." if not missing else f"Chybí identifikační texty: {missing}",
            str(self.ssot), f"sha256={hashlib.sha256(self.ssot.read_bytes()).hexdigest()}",
        )

    def check_cardinality(self) -> None:
        if self.is_new_ssot:
            actual = set(NEW_ACCEPTANCE_PATTERN.findall(self.ssot_text))
            expected = ({f"IMP-{i:03d}" for i in range(1, 9)} | {f"REC-{i:03d}" for i in range(1, 13)} |
                        {f"AUTO-{i:03d}" for i in range(1, 7)} | {f"UI-{i:03d}" for i in range(1, 9)})
            self.add("SSOT-NEW-ACCEPTANCE-CARDINALITY", "SSOT", "PASS" if actual == expected else "FAIL", f"SSOT={len(actual)}, očekáváno={len(expected)}, chybí={sorted(expected - actual)}, přebývá={sorted(actual - expected)}", str(self.ssot))
            return
        doc_ids = set(ACCEPTANCE_PATTERN.findall(self.ssot_text))
        manifest_ids = {row["id"] for row in self.manifest["acceptance_scenarios"]}
        detail = f"SSOT={len(doc_ids)}, manifest={len(manifest_ids)}, očekáváno=162"
        self.add(
            "SSOT-ACCEPTANCE-CARDINALITY", "SSOT", "PASS" if doc_ids == manifest_ids and len(doc_ids) == 162 else "FAIL",
            detail,
            "docs/SSOT_MANIFEST.json",
        )
        action_ids = [row["id"] for row in self.manifest["actions"]]
        missing_actions = [value for value in action_ids if value not in self.ssot_compact]
        self.add(
            "SSOT-ACTION-CARDINALITY", "SSOT", "PASS" if len(action_ids) == 38 and len(set(action_ids)) == 38 and not missing_actions else "FAIL",
            f"38 akcí; chybějící v DOCX: {missing_actions}", "docs/SSOT_MANIFEST.json",
        )
        component_ids = [row["id"] for row in self.manifest["ui_components"]]
        missing_components = [value for value in component_ids if value not in self.ssot_compact]
        self.add(
            "SSOT-UI-CARDINALITY", "SSOT", "PASS" if len(component_ids) == 76 and len(set(component_ids)) == 76 and not missing_components else "FAIL",
            f"76 UI komponent; chybějící v DOCX: {missing_components}", "docs/SSOT_MANIFEST.json",
        )

    def check_action_registry(self) -> None:
        path = self.root / "src/kajovokarty/ui/action_registry.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        enum_values = self._enum_values(tree, "ActionId")
        specs: dict[str, dict[str, str]] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ActionSpec"):
                continue
            specs[node.args[0].attr] = {
                "id": node.args[0].attr,
                "label": ast.literal_eval(node.args[2]),
                "tooltip": ast.literal_eval(node.args[3]),
                "shortcut": ast.literal_eval(node.args[4]) or "",
            }
        expected = {row["id"]: row for row in self.manifest["actions"]}
        mismatches = [key for key in sorted(expected) if specs.get(key) != expected[key]]
        self.add(
            "UI-ACTION-REGISTRY", "UI", "PASS" if set(enum_values) == set(expected) and not mismatches else "FAIL",
            f"enum={len(enum_values)}, specs={len(specs)}, přesné odchylky={mismatches}",
            path.relative_to(self.root).as_posix(),
        )
        main_source = (self.root / "src/kajovokarty/ui/main_window.py").read_text(encoding="utf-8")
        missing_handlers = [value for value in enum_values if f"ActionId.{value}" not in main_source]
        self.add(
            "UI-ACTION-HANDLERS", "UI", "PASS" if not missing_handlers else "FAIL",
            f"Akce bez dohledatelného handleru: {missing_handlers}", "src/kajovokarty/ui/main_window.py",
        )

    def check_object_action_matrix(self) -> None:
        contract_path = self.root / "docs/OBJECT_ACTION_MATRIX.json"
        if not contract_path.exists():
            self.add("UI-OBJECT-ACTION-MATRIX", "UI", "FAIL", "Chybí forenzní kontrakt Přílohy B.", "docs/OBJECT_ACTION_MATRIX.json")
            return
        contract = json.loads(contract_path.read_text(encoding="utf-8"))["objects"]
        registry_path = self.root / "src/kajovokarty/ui/action_registry.py"
        tree = ast.parse(registry_path.read_text(encoding="utf-8"), filename=str(registry_path))
        specs: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ActionSpec"):
                continue
            action = node.args[0]
            if not isinstance(action, ast.Attribute):
                continue
            object_types_node = node.args[5]
            if (
                isinstance(object_types_node, ast.Call)
                and isinstance(object_types_node.func, ast.Name)
                and object_types_node.func.id == "frozenset"
            ):
                values = ast.literal_eval(object_types_node.args[0])
            else:
                values = ast.literal_eval(object_types_node)
            specs[action.attr] = set(values)
        missing: list[str] = []
        for object_type, row in contract.items():
            for action_id in row["required_actions"]:
                if action_id not in specs:
                    missing.append(f"{object_type}:{action_id}:missing-spec")
                elif object_type not in specs[action_id]:
                    missing.append(f"{object_type}:{action_id}:not-applicable")
        self.add(
            "UI-OBJECT-ACTION-MATRIX",
            "UI",
            "PASS" if not missing else "FAIL",
            f"Objekty={len(contract)}, chybějící vazby={missing}",
            "docs/OBJECT_ACTION_MATRIX.json",
            "src/kajovokarty/ui/action_registry.py",
        )

    def check_component_registry(self) -> None:
        path = self.root / "src/kajovokarty/ui/component_registry.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        enum_values = self._enum_values(tree, "ComponentId")
        specs: dict[str, dict[str, str]] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ComponentSpec"):
                continue
            specs[node.args[0].attr] = {
                "id": node.args[0].attr,
                "human_name": ast.literal_eval(node.args[1]),
                "view": ast.literal_eval(node.args[2]),
                "primary_function": ast.literal_eval(node.args[3]),
                "states": "/".join(ast.literal_eval(node.args[4])),
            }
        expected = {row["id"]: row for row in self.manifest["ui_components"]}
        mismatches = [key for key in sorted(expected) if specs.get(key) != expected[key]]
        self.add(
            "UI-COMPONENT-REGISTRY", "UI", "PASS" if set(enum_values) == set(expected) and not mismatches else "FAIL",
            f"enum={len(enum_values)}, specs={len(specs)}, přesné odchylky={mismatches}",
            path.relative_to(self.root).as_posix(),
        )
        live_source = "\n".join(
            candidate.read_text(encoding="utf-8", errors="replace")
            for candidate in (self.root / "src/kajovokarty/ui").rglob("*.py")
            if candidate.name != "component_registry.py"
        )
        unbound = [component_id for component_id in expected if f"ComponentId.{component_id}" not in live_source]
        self.add(
            "UI-COMPONENT-LIVE-BINDINGS",
            "UI",
            "PASS" if not unbound else "FAIL",
            f"Komponenty bez dohledatelné živé vazby: {unbound}",
            "src/kajovokarty/ui/",
        )

    def check_repository_hygiene(self) -> None:
        missing = sorted(REQUIRED_ROOT - {path.name for path in self.root.iterdir()})
        self.add("REPO-TREE", "Repository", "PASS" if not missing else "FAIL", f"Chybí: {missing}")
        secrets: list[str] = []
        placeholders: list[str] = []
        original_inputs: list[str] = []
        for path in self._iter_files(self.root):
            relative = path.relative_to(self.root).as_posix()
            if path.suffix.lower() in {".doc", ".docx"} or re.search(r"FINALNI_SSOT|NEZAVISLE_AUDITOVANO", path.name, re.I):
                original_inputs.append(relative)
            if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 5_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    secrets.append(f"{relative}:{label}")
            if relative not in {"scripts/repository_audit.py", "scripts/forensic_ssot_audit.py"}:
                for lineno, line in enumerate(text.splitlines(), 1):
                    if re.search(r"\b(?:TO" r"DO|FIX" r"ME|NotImplementedError)\b", line):
                        placeholders.append(f"{relative}:{lineno}")
        self.add("REPO-SECRETS", "Security", "PASS" if not secrets else "FAIL", f"Nálezy: {secrets}")
        self.add("REPO-PLACEHOLDERS", "Repository", "PASS" if not placeholders else "FAIL", f"Nálezy: {placeholders}")
        self.add("REPO-NO-INPUTS", "Security", "PASS" if not original_inputs else "FAIL", f"Nálezy: {original_inputs}")

    def check_python_and_money(self) -> None:
        syntax_errors: list[str] = []
        float_hits: list[str] = []
        for path in [*self.root.glob("src/**/*.py"), *self.root.glob("tests/**/*.py"), *self.root.glob("scripts/**/*.py")]:
            relative = path.relative_to(self.root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            except SyntaxError as exc:
                syntax_errors.append(f"{relative}:{exc.lineno}:{exc.msg}")
                continue
            financial = relative.startswith("src/kajovokarty/domain/") or relative.startswith("src/kajovokarty/application/pairing.py") or relative.startswith("src/kajovokarty/application/reconciliation.py") or relative.startswith("src/kajovokarty/application/counterparts.py") or relative.startswith("src/kajovokarty/infrastructure/importers/")
            if financial:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
                        float_hits.append(f"{relative}:{node.lineno}")
        self.add("PY-AST", "Static", "PASS" if not syntax_errors else "FAIL", f"Chyby: {syntax_errors}")
        self.add("MONEY-NO-FLOAT", "Finance", "PASS" if not float_hits else "FAIL", f"Nálezy: {float_hits}")

    def check_api_read_only(self) -> None:
        api_root = self.root / "src/kajovokarty/infrastructure/better_hotel"
        text = "\n".join(path.read_text(encoding="utf-8") for path in api_root.glob("*.py"))
        text += "\n" + (self.root / "src/kajovokarty/app/config.py").read_text(encoding="utf-8")
        forbidden = [verb for verb in ("post", "put", "patch", "delete") if re.search(rf"\bdef\s+{verb}\b|\.request\(\s*['\"]{verb.upper()}['\"]", text)]
        endpoint_ok = "https://api.better-hotel.com/api/connector/v/1" in text
        header_ok = "X-Access-Token" in text and "X-Client-Token" in text and "Bearer" not in text
        self.add("API-READ-ONLY", "API", "PASS" if not forbidden and endpoint_ok and header_ok else "FAIL", f"forbidden={forbidden}, endpoint={endpoint_ok}, headers={header_ok}", "src/kajovokarty/infrastructure/better_hotel/")

    def check_database(self) -> None:
        migrations = sorted((self.root / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
        versions = [int(path.name.split("_", 1)[0]) for path in migrations]
        contiguous = versions == list(range(1, versions[-1] + 1)) if versions else False
        try:
            with tempfile.TemporaryDirectory(prefix="kajovokarty-audit-") as temp:
                database_path = Path(temp) / "audit.sqlite3"
                conn = sqlite3.connect(database_path)
                try:
                    conn.execute("PRAGMA foreign_keys=ON")
                    conn.execute("CREATE TABLE schema_migration(version INTEGER PRIMARY KEY,name TEXT,checksum TEXT,applied_at_utc TEXT)")
                    for path in migrations:
                        conn.executescript(path.read_text(encoding="utf-8"))
                        version = int(path.name.split("_", 1)[0])
                        conn.execute("INSERT INTO schema_migration VALUES(?,?,?,datetime('now'))", (version, path.stem, hashlib.sha256(path.read_bytes()).hexdigest()))
                    conn.commit()
                    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
                finally:
                    conn.close()
            db_ok = integrity == "ok" and not fk
            detail = f"migrace={versions}, integrity={integrity}, foreign_key_errors={len(fk)}"
        except Exception as exc:
            db_ok = False
            detail = f"Migrace selhala: {type(exc).__name__}: {exc}"
        self.add("DB-MIGRATIONS", "Database", "PASS" if contiguous and db_ok else "FAIL", detail, "migrations/")

    def check_bootstrap_and_build(self) -> None:
        run_bat_path = self.root / "run.bat"
        run_bat_raw = run_bat_path.read_bytes()
        run_bat = run_bat_raw.decode("ascii", errors="replace")
        required = ["%~dp0", "chcp 65001", "--check", "--test", "--repair", ".venv", "scripts\\bootstrap.py"]
        missing = [fragment for fragment in required if fragment.lower() not in run_bat.lower()]
        cmd_safe = (
            run_bat_raw.startswith(b"@echo off\r\n")
            and not run_bat_raw.startswith(b"\xef\xbb\xbf")
            and b"\n" not in run_bat_raw.replace(b"\r\n", b"")
            and all(byte < 128 for byte in run_bat_raw)
        )
        bootstrap_ok = not missing and cmd_safe
        detail = f"Chybí: {missing}" if missing else ("ASCII bez BOM, výhradně CRLF." if cmd_safe else "run.bat není CMD-safe ASCII/CRLF.")
        self.add("BOOTSTRAP-STATIC", "Build", "PASS" if bootstrap_ok else "FAIL", detail, "run.bat", "scripts/bootstrap.py")
        build_required = ["build/KajovoKarty.spec", "build/installer/KajovoKarty.iss", "scripts/build_release.py", ".github/workflows/windows-release.yml"]
        absent = [value for value in build_required if not (self.root / value).exists()]
        self.add("BUILD-REPRODUCIBLE-STATIC", "Build", "PASS" if not absent else "FAIL", f"Chybí: {absent}", *build_required)
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["cmd.exe", "/d", "/c", "run.bat --check"],
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                run_status = "PASS" if result.returncode == 0 else "FAIL"
                run_detail = f"cmd.exe run.bat --check exit={result.returncode}."
            except (OSError, subprocess.TimeoutExpired) as exc:
                run_status = "BLOCKED"
                run_detail = f"Windows CMD gate nelze spustit: {exc}"
        else:
            run_status = "BLOCKED"
            run_detail = f"Host={platform.system()} {platform.machine()} není Windows."
        self.add("WINDOWS-RUN-BAT", "Runtime", run_status, run_detail, "run.bat")
        try:
            __import__("PySide6")
            qt_status = "PASS"
            qt_detail = "PySide6 lze importovat."
        except Exception as exc:
            qt_status = "BLOCKED"
            qt_detail = f"PySide6 runtime není dostupný: {exc}"
        self.add("QT-GUI-DPI", "UI runtime", qt_status, qt_detail, "tests/ui/test_gui_smoke.py", "scripts/gui_layout_audit.py")
        if platform.system() == "Windows" and shutil.which("ISCC.exe"):
            installer_status = "PASS"
            installer_detail = "Inno Setup compiler je dostupný."
        else:
            installer_status = "BLOCKED"
            installer_detail = "Windows EXE a Inno Setup instalátor nelze na tomto hostu skutečně sestavit a spustit."
        self.add("WINDOWS-EXE-INSTALLER", "Build", installer_status, installer_detail, "scripts/build_release.py", "build/KajovoKarty.iss")

    def check_local_test_evidence(self) -> None:
        evidence_path = self.root / "build/local-test-results.json"
        if not evidence_path.exists():
            self.add("LOCAL-TEST-SUITE", "Tests", "FAIL", "Chybí strojově čitelný záznam posledního lokálního testu.", "build/local-test-results.json")
        else:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            passed = int(evidence.get("passed", 0))
            failed = int(evidence.get("failed", 0))
            skipped = int(evidence.get("skipped", 0))
            self.add(
                "LOCAL-TEST-SUITE",
                "Tests",
                "PASS" if passed > 0 and failed == 0 else "FAIL",
                f"passed={passed}, failed={failed}, skipped={skipped}; skipped GUI test není release PASS.",
                "build/local-test-results.json",
            )
        coverage_path = self.root / "build/coverage-final.json"
        if coverage_path.exists():
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            percent = float(coverage.get("totals", {}).get("percent_covered", 0.0))
            self.add(
                "LOCAL-COVERAGE-EVIDENCE",
                "Tests",
                "PASS",
                f"Lokální coverage={percent:.2f} %. UI moduly nejsou bez PySide6 runtime pokryté a tento údaj nenahrazuje Windows GUI audit.",
                "build/coverage-final.json",
            )
        else:
            self.add("LOCAL-COVERAGE-EVIDENCE", "Tests", "FAIL", "Chybí coverage report.", "build/coverage-final.json")

    def check_static_tooling(self) -> None:
        unavailable = [tool for tool in ("ruff", "mypy") if importlib.util.find_spec(tool) is None]
        self.add(
            "STATIC-LINT-TYPE-TOOLS",
            "Static",
            "BLOCKED" if unavailable else "PASS",
            f"Nedostupné nástroje na tomto hostu: {unavailable}" if unavailable else "ruff a mypy jsou dostupné.",
            "pyproject.toml",
            ".github/workflows/windows-release.yml",
        )

    def check_new_ssot_contract(self) -> None:
        if not self.is_new_ssot:
            return
        importer = self.root / "src/kajovokarty/infrastructure/importers/cashbook_xls.py"
        pairing = self.root / "src/kajovokarty/application/pairing.py"
        search = self.root / "src/kajovokarty/application/search.py"
        importer_text = importer.read_text(encoding="utf-8") if importer.exists() else ""
        pairing_text = pairing.read_text(encoding="utf-8")
        checks = {
            "cashbook-importer": importer.exists(),
            "cashbook-schema": (self.root / "migrations/006_cashbook_reconciliation.sql").exists(),
            "all-file-formats": all(value in importer_text for value in [".xls", ".xlsx", "csv"]),
            "atomic-import": "with self.database.transaction()" in importer_text,
            "no-cashbook-quarantine": "quarantine" not in importer_text.casefold(),
            "composable-groups": all(value in pairing_text for value in ["def pair_sources", "def add_sources_to_group"]),
            "exact-zero": "difference == 0" in pairing_text,
            "cashbook-search": "cashbook_card_transaction" in search.read_text(encoding="utf-8"),
            "acceptance-tests": (self.root / "tests/integration/test_cashbook_reconciliation.py").exists(),
            "cashbook-matching-view": "CASHBOOK_CARD" in (self.root / "src/kajovokarty/ui/screens/matching.py").read_text(encoding="utf-8"),
            "cashbook-led-automation": "CASHBOOK_CARD" in (self.root / "src/kajovokarty/application/payment_reconciliation.py").read_text(encoding="utf-8"),
            "bank-booking-no-quarantine": all("INSERT INTO quarantined_source_row" not in (self.root / path).read_text(encoding="utf-8") for path in ["src/kajovokarty/infrastructure/importers/bank_file.py", "src/kajovokarty/infrastructure/importers/booking_csv.py"]),
            "nested-group-ownership": all(value in pairing_text for value in ["def add_group_to_group", "def detach_group_parent", "def dissolve_group", "match_group_child"]),
        }
        failed = sorted(name for name, ok in checks.items() if not ok)
        self.add("SSOT-NEW-CONTRACT", "Implementation", "PASS" if not failed else "FAIL", f"Odchylky: {failed}", "new SSOT implementation")

    def check_traceability(self) -> None:
        if self.is_new_ssot:
            path = self.root / "docs/SSOT_NOVA_REKONSILIACE_TRACEABILITY.md"
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            ids = set(NEW_ACCEPTANCE_PATTERN.findall(self.ssot_text))
            missing = sorted(value for value in ids if value not in text)
            self.add("TRACEABILITY-NEW-SSOT", "Audit", "PASS" if not missing else "FAIL", f"Chybějící scénáře: {missing}", str(path))
            return
        path = self.root / "docs/SSOT_TRACEABILITY.md"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [row["id"] for row in self.manifest["acceptance_scenarios"] if f"| {row['id']} |" not in text]
        self.add("TRACEABILITY-162", "Audit", "PASS" if not missing else "FAIL", f"Chybějící řádky: {missing}", "docs/SSOT_TRACEABILITY.md")

    def run(self) -> dict[str, object]:
        self.check_ssot_identity()
        self.check_cardinality()
        self.check_action_registry()
        self.check_object_action_matrix()
        self.check_component_registry()
        self.check_new_ssot_contract()
        self.check_repository_hygiene()
        self.check_python_and_money()
        self.check_api_read_only()
        self.check_database()
        self.check_bootstrap_and_build()
        self.check_local_test_evidence()
        self.check_static_tooling()
        self.check_traceability()
        failed = [finding for finding in self.findings if finding.status == "FAIL"]
        blocked = [finding for finding in self.findings if finding.status == "BLOCKED"]
        verdict = "FAIL" if failed else "BLOCKED" if blocked else "PASS"
        return {
            "product": "KájovoKarty",
            "ssot_version": "nova-rekonsiliace-2026-09-07" if self.is_new_ssot else "1.1",
            "ssot_sha256": hashlib.sha256(self.ssot.read_bytes()).hexdigest(),
            "repository": str(self.root),
            "environment": {
                "platform": platform.platform(),
                "python": sys.version,
                "cwd": os.getcwd(),
            },
            "verdict": verdict,
            "local_static_checks_passed": not failed,
            "failed_findings": [finding.id for finding in failed],
            "blocked_gates": [finding.id for finding in blocked],
            "findings": [asdict(finding) for finding in self.findings],
        }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Forenzní audit KájovoKarty proti SSOT 1.1",
        "",
        f"**Verdikt: {report['verdict']}**",
        "",
        f"SSOT SHA-256: `{report['ssot_sha256']}`",
        "",
        "| ID | Oblast | Stav | Zjištění |",
        "|---|---|---|---|",
    ]
    for finding in report["findings"]:
        detail = str(finding["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {finding['id']} | {finding['area']} | {finding['status']} | {detail} |")
    lines.extend(["", "## Blokované release gate", ""])
    for gate in report["blocked_gates"]:
        lines.append(f"- `{gate}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Forenzní audit repozitáře proti autoritativnímu SSOT DOCX")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ssot", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    report = ForensicAudit(args.root, args.ssot).run()
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
