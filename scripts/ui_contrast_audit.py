from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from kajovokarty.ui.theme import (
    HIGH_CONTRAST_THEME,
    NORMAL_THEME,
    ThemeColors,
    build_stylesheet,
    critical_contrast_pairs,
    contrast_ratio,
)

ROOT = Path(__file__).resolve().parents[1]
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b")


def audit_theme(name: str, theme: ThemeColors) -> dict[str, object]:
    pairs = critical_contrast_pairs(theme)
    results = {
        pair_name: {
            "foreground": foreground,
            "background": background,
            "ratio": round(contrast_ratio(foreground, background), 3),
            "minimum": 4.5,
            "status": "PASS" if contrast_ratio(foreground, background) >= 4.5 else "FAIL",
        }
        for pair_name, (foreground, background) in pairs.items()
    }
    stylesheet = build_stylesheet(10, theme)
    required_selectors = (
        "QPushButton, QToolButton",
        "QPushButton:hover, QToolButton:hover",
        "QPushButton:pressed, QToolButton:pressed",
        "QPushButton:disabled, QToolButton:disabled",
        "#topBar QPushButton, #topBar QToolButton",
        "#topBar QPushButton:hover, #topBar QToolButton:hover",
        "#topBar QPushButton:pressed, #topBar QToolButton:pressed",
        "#topBar QPushButton:disabled, #topBar QToolButton:disabled",
        "#TOP_RUN_ALL, #PRIMARY_SAVE_SETTINGS",
        "QTabBar::tab:selected",
        "QMenu::item:selected",
        "QAbstractItemView::item:selected",
    )
    missing_selectors = [selector for selector in required_selectors if selector not in stylesheet]
    return {
        "theme": name,
        "status": "PASS"
        if all(item["status"] == "PASS" for item in results.values()) and not missing_selectors
        else "FAIL",
        "pairs": results,
        "stylesheet": {
            "balanced_braces": stylesheet.count("{") == stylesheet.count("}"),
            "missing_required_selectors": missing_selectors,
        },
    }


def audit_source(root: Path) -> dict[str, Any]:
    ui_root = root / "src" / "kajovokarty" / "ui"
    color_leaks: list[str] = []
    for path in sorted(ui_root.rglob("*.py")):
        if path.name == "theme.py":
            continue
        text = path.read_text(encoding="utf-8")
        for match in HEX_COLOR.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            color_leaks.append(f"{path.relative_to(root).as_posix()}:{line}:{match.group(0)}")

    main_window = (ui_root / "main_window.py").read_text(encoding="utf-8")
    legacy_faults = [
        fragment
        for fragment in (
            '#topBar QLabel, #topBar QPushButton { color: white; }',
            "QMainWindow, QWidget { background:",
        )
        if fragment in main_window
    ]
    central_theme = all(
        fragment in main_window
        for fragment in (
            "build_palette(theme)",
            "build_stylesheet(base, theme)",
            "application.setPalette(palette)",
            "application.setStyleSheet(stylesheet)",
            "HIGH_CONTRAST_THEME if high_contrast else NORMAL_THEME",
            'application.setStyle("Fusion")',
        )
    )
    status = "PASS" if not color_leaks and not legacy_faults and central_theme else "FAIL"
    return {
        "status": status,
        "hardcoded_colors_outside_theme": color_leaks,
        "legacy_fault_patterns": legacy_faults,
        "central_theme_applied": central_theme,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Forenzní audit kontrastu UI KájovoKarty.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    themes = [
        audit_theme("normal", NORMAL_THEME),
        audit_theme("high_contrast", HIGH_CONTRAST_THEME),
    ]
    source = audit_source(root)
    payload = {
        "standard": "WCAG 2.x AA normal text",
        "minimum_ratio": 4.5,
        "status": "PASS"
        if all(theme["status"] == "PASS" for theme in themes) and source["status"] == "PASS"
        else "FAIL",
        "themes": themes,
        "source_audit": source,
    }
    output = args.output or root / "build" / "ui-contrast-audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
