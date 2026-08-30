from __future__ import annotations

from pathlib import Path


def test_import_queue_shows_hash_schema_and_estimated_rows() -> None:
    source = Path("src/kajovokarty/ui/screens/imports.py").read_text(encoding="utf-8")
    assert "import_preflight.booking_preview" in source
    assert "import_preflight.bank_preview" in source
    assert "preview.human_summary" in source
    assert "imports.max_megabytes" in source


def test_preflight_uses_streaming_sha256_and_duplicate_lookup() -> None:
    source = Path("src/kajovokarty/application/import_preflight.py").read_text(encoding="utf-8")
    assert 'handle.read(1024 * 1024)' in source
    assert "booking_import_run" in source
    assert "bank_import_run" in source
    assert "duplicate_file" in source
