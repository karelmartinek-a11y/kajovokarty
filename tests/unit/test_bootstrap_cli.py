from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load_bootstrap_module():
    module_path = ROOT / "scripts" / "bootstrap.py"
    spec = importlib.util.spec_from_file_location("kajovokarty_bootstrap_cli_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode", ["--run", "--check", "--test", "--repair"])
def test_bootstrap_accepts_run_bat_mode_flags(mode: str) -> None:
    module = _load_bootstrap_module()
    args = module.build_argument_parser().parse_args([mode])
    assert args.mode == mode


def test_bootstrap_rejects_missing_mode() -> None:
    module = _load_bootstrap_module()
    with pytest.raises(SystemExit) as exc_info:
        module.build_argument_parser().parse_args([])
    assert exc_info.value.code == 2


def test_run_bat_passes_mode_flag_to_bootstrap() -> None:
    text = (ROOT / "run.bat").read_text(encoding="ascii")
    assert '"%PYTHON_EXE%" "scripts\\bootstrap.py" "%MODE%"' in text
    assert 'if not defined MODE set "MODE=--run"' in text
