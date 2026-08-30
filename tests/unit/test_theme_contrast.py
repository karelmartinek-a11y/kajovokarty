from __future__ import annotations

from kajovokarty.ui.theme import (
    HIGH_CONTRAST_THEME,
    NORMAL_THEME,
    build_stylesheet,
    critical_contrast_pairs,
    contrast_ratio,
    validate_theme_contrast,
)


def test_all_critical_theme_pairs_meet_wcag_aa() -> None:
    for theme in (NORMAL_THEME, HIGH_CONTRAST_THEME):
        ratios = validate_theme_contrast(theme)
        assert ratios
        assert min(ratios.values()) >= 4.5


def test_top_bar_buttons_have_explicit_foreground_and_background() -> None:
    stylesheet = build_stylesheet(10, NORMAL_THEME)
    assert "#topBar QPushButton" in stylesheet
    assert f"color: {NORMAL_THEME.topbar_button_text}" in stylesheet
    assert f"background-color: {NORMAL_THEME.topbar_button}" in stylesheet
    assert "#topBar QPushButton:hover" in stylesheet
    assert "#topBar QPushButton:pressed" in stylesheet
    assert "#topBar QPushButton:disabled" in stylesheet


def test_button_states_never_rely_on_native_os_colors() -> None:
    stylesheet = build_stylesheet(10, NORMAL_THEME)
    required_selectors = (
        "QPushButton, QToolButton",
        "QPushButton:hover, QToolButton:hover",
        "QPushButton:pressed, QToolButton:pressed",
        "QPushButton:disabled, QToolButton:disabled",
        "#TOP_RUN_ALL, #PRIMARY_SAVE_SETTINGS",
    )
    for selector in required_selectors:
        assert selector in stylesheet


def test_no_critical_pair_is_close_to_the_threshold() -> None:
    for theme in (NORMAL_THEME, HIGH_CONTRAST_THEME):
        for foreground, background in critical_contrast_pairs(theme).values():
            assert contrast_ratio(foreground, background) >= 4.5
