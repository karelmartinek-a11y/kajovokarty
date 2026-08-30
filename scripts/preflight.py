from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kajovokarty.app.preflight import run_preflight  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="KájovoKarty preflight")
    parser.add_argument("--allow-non-windows", action="store_true")
    args = parser.parse_args()
    report = run_preflight(require_windows=not args.allow_non_windows)
    print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
