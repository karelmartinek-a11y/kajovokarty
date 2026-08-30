from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QPalette


@dataclass(frozen=True, slots=True)
class ThemeColors:
    window: str
    surface: str
    surface_alt: str
    text: str
    muted_text: str
    border: str
    disabled_bg: str
    disabled_text: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    primary: str
    primary_hover: str
    primary_pressed: str
    primary_text: str
    danger: str
    danger_text: str
    warning_bg: str
    warning_text: str
    success_bg: str
    success_text: str
    topbar: str
    topbar_text: str
    topbar_button: str
    topbar_button_hover: str
    topbar_button_pressed: str
    topbar_button_text: str
    nav_bg: str
    nav_selected: str
    nav_selected_text: str
    input_bg: str
    input_text: str
    placeholder: str
    selection: str
    selection_text: str
    header_bg: str
    header_text: str
    tooltip_bg: str
    tooltip_text: str
    focus: str
    link: str
    progress_bg: str
    progress_chunk: str
    progress_text: str


NORMAL_THEME = ThemeColors(
    window="#F4F6F8",
    surface="#FFFFFF",
    surface_alt="#EEF2F6",
    text="#17202A",
    muted_text="#44515F",
    border="#647382",
    disabled_bg="#E5E7EB",
    disabled_text="#4B5563",
    accent="#005A9C",
    accent_hover="#00487D",
    accent_pressed="#003A65",
    accent_text="#FFFFFF",
    primary="#006B4F",
    primary_hover="#00553F",
    primary_pressed="#003F2F",
    primary_text="#FFFFFF",
    danger="#A61B1B",
    danger_text="#FFFFFF",
    warning_bg="#FFF4CC",
    warning_text="#111111",
    success_bg="#E4F3E9",
    success_text="#174B2A",
    topbar="#17385F",
    topbar_text="#FFFFFF",
    topbar_button="#FFFFFF",
    topbar_button_hover="#E8F0F7",
    topbar_button_pressed="#D5E3EF",
    topbar_button_text="#17385F",
    nav_bg="#E6ECF2",
    nav_selected="#005A9C",
    nav_selected_text="#FFFFFF",
    input_bg="#FFFFFF",
    input_text="#17202A",
    placeholder="#5A6673",
    selection="#0B5EA8",
    selection_text="#FFFFFF",
    header_bg="#D9E2EC",
    header_text="#102A43",
    tooltip_bg="#FFF4CC",
    tooltip_text="#111111",
    focus="#C2410C",
    link="#005A9C",
    progress_bg="#FFFFFF",
    progress_chunk="#B9DDF5",
    progress_text="#17202A",
)


HIGH_CONTRAST_THEME = ThemeColors(
    window="#FFFFFF",
    surface="#FFFFFF",
    surface_alt="#F2F2F2",
    text="#000000",
    muted_text="#202020",
    border="#000000",
    disabled_bg="#E0E0E0",
    disabled_text="#333333",
    accent="#000000",
    accent_hover="#1A1A1A",
    accent_pressed="#333333",
    accent_text="#FFFFFF",
    primary="#FFD800",
    primary_hover="#FFE34D",
    primary_pressed="#E6C200",
    primary_text="#000000",
    danger="#8B0000",
    danger_text="#FFFFFF",
    warning_bg="#FFD800",
    warning_text="#000000",
    success_bg="#FFFFFF",
    success_text="#000000",
    topbar="#000000",
    topbar_text="#FFFFFF",
    topbar_button="#FFFFFF",
    topbar_button_hover="#FFD800",
    topbar_button_pressed="#E6C200",
    topbar_button_text="#000000",
    nav_bg="#FFFFFF",
    nav_selected="#000000",
    nav_selected_text="#FFFFFF",
    input_bg="#FFFFFF",
    input_text="#000000",
    placeholder="#333333",
    selection="#000000",
    selection_text="#FFFFFF",
    header_bg="#000000",
    header_text="#FFFFFF",
    tooltip_bg="#FFD800",
    tooltip_text="#000000",
    focus="#C00000",
    link="#0000CC",
    progress_bg="#FFFFFF",
    progress_chunk="#FFD800",
    progress_text="#000000",
)


def _channel_to_linear(channel: int) -> float:
    value = channel / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    value = color.removeprefix("#")
    if len(value) != 6:
        raise ValueError(f"Unsupported color value: {color}")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return (
        0.2126 * _channel_to_linear(red)
        + 0.7152 * _channel_to_linear(green)
        + 0.0722 * _channel_to_linear(blue)
    )


def contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (relative_luminance(foreground), relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def critical_contrast_pairs(theme: ThemeColors) -> dict[str, tuple[str, str]]:
    return {
        "window text": (theme.text, theme.window),
        "surface text": (theme.text, theme.surface),
        "muted text": (theme.muted_text, theme.surface),
        "button": (theme.text, theme.surface),
        "disabled button": (theme.disabled_text, theme.disabled_bg),
        "accent button": (theme.accent_text, theme.accent),
        "accent hover": (theme.accent_text, theme.accent_hover),
        "accent pressed": (theme.accent_text, theme.accent_pressed),
        "primary button": (theme.primary_text, theme.primary),
        "primary hover": (theme.primary_text, theme.primary_hover),
        "primary pressed": (theme.primary_text, theme.primary_pressed),
        "top bar": (theme.topbar_text, theme.topbar),
        "top bar button": (theme.topbar_button_text, theme.topbar_button),
        "top bar button hover": (theme.topbar_button_text, theme.topbar_button_hover),
        "top bar button pressed": (theme.topbar_button_text, theme.topbar_button_pressed),
        "navigation selected": (theme.nav_selected_text, theme.nav_selected),
        "input": (theme.input_text, theme.input_bg),
        "placeholder": (theme.placeholder, theme.input_bg),
        "selection": (theme.selection_text, theme.selection),
        "table header": (theme.header_text, theme.header_bg),
        "tooltip": (theme.tooltip_text, theme.tooltip_bg),
        "danger": (theme.danger_text, theme.danger),
        "warning": (theme.warning_text, theme.warning_bg),
        "success": (theme.success_text, theme.success_bg),
        "progress empty": (theme.progress_text, theme.progress_bg),
        "progress filled": (theme.progress_text, theme.progress_chunk),
    }


def validate_theme_contrast(theme: ThemeColors, minimum: float = 4.5) -> dict[str, float]:
    ratios = {
        name: contrast_ratio(foreground, background)
        for name, (foreground, background) in critical_contrast_pairs(theme).items()
    }
    failures = {name: ratio for name, ratio in ratios.items() if ratio < minimum}
    if failures:
        details = ", ".join(f"{name}={ratio:.2f}" for name, ratio in failures.items())
        raise ValueError(f"Theme has insufficient contrast: {details}")
    return ratios


def build_palette(theme: ThemeColors) -> QPalette:
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    role_values = {
        QPalette.ColorRole.Window: theme.window,
        QPalette.ColorRole.WindowText: theme.text,
        QPalette.ColorRole.Base: theme.input_bg,
        QPalette.ColorRole.AlternateBase: theme.surface_alt,
        QPalette.ColorRole.ToolTipBase: theme.tooltip_bg,
        QPalette.ColorRole.ToolTipText: theme.tooltip_text,
        QPalette.ColorRole.Text: theme.input_text,
        QPalette.ColorRole.Button: theme.surface,
        QPalette.ColorRole.ButtonText: theme.text,
        QPalette.ColorRole.BrightText: theme.danger_text,
        QPalette.ColorRole.Link: theme.link,
        QPalette.ColorRole.Highlight: theme.selection,
        QPalette.ColorRole.HighlightedText: theme.selection_text,
        QPalette.ColorRole.PlaceholderText: theme.placeholder,
        QPalette.ColorRole.Mid: theme.border,
        QPalette.ColorRole.Dark: theme.text,
        QPalette.ColorRole.Light: theme.surface,
        QPalette.ColorRole.Shadow: theme.text,
    }
    for role, color in role_values.items():
        palette.setColor(QPalette.ColorGroup.Active, role, QColor(color))
        palette.setColor(QPalette.ColorGroup.Inactive, role, QColor(color))
    disabled_values = {
        QPalette.ColorRole.WindowText: theme.disabled_text,
        QPalette.ColorRole.Text: theme.disabled_text,
        QPalette.ColorRole.ButtonText: theme.disabled_text,
        QPalette.ColorRole.Button: theme.disabled_bg,
        QPalette.ColorRole.Base: theme.disabled_bg,
        QPalette.ColorRole.Highlight: theme.disabled_text,
        QPalette.ColorRole.HighlightedText: theme.disabled_bg,
        QPalette.ColorRole.PlaceholderText: theme.disabled_text,
    }
    for role, color in disabled_values.items():
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    return palette


def build_stylesheet(base_point_size: int, theme: ThemeColors) -> str:
    validate_theme_contrast(theme)
    return f"""
        QWidget {{
            color: {theme.text};
            font-family: Arial;
            font-size: {base_point_size}pt;
        }}
        QMainWindow, QDialog {{
            background-color: {theme.window};
        }}
        QLabel {{
            color: {theme.text};
            background-color: transparent;
        }}
        QLabel:disabled {{
            color: {theme.disabled_text};
        }}
        #screenTitle {{
            color: {theme.text};
            font-size: {base_point_size + 5}pt;
            font-weight: 700;
        }}
        #brand {{
            color: {theme.topbar_text};
            font-size: {base_point_size + 6}pt;
            font-weight: 700;
        }}
        #topBar {{
            background-color: {theme.topbar};
            border: none;
        }}
        #topBar QLabel {{
            color: {theme.topbar_text};
            background-color: transparent;
        }}
        QPushButton, QToolButton {{
            min-height: 30px;
            padding: 5px 10px;
            color: {theme.text};
            background-color: {theme.surface};
            border: 1px solid {theme.border};
            border-radius: 4px;
            font-weight: 600;
        }}
        QPushButton:hover, QToolButton:hover {{
            color: {theme.accent_text};
            background-color: {theme.accent};
            border-color: {theme.accent};
        }}
        QPushButton:pressed, QToolButton:pressed {{
            color: {theme.accent_text};
            background-color: {theme.accent_pressed};
            border-color: {theme.accent_pressed};
        }}
        QPushButton:checked, QToolButton:checked {{
            color: {theme.accent_text};
            background-color: {theme.accent};
            border-color: {theme.accent};
        }}
        QPushButton:disabled, QToolButton:disabled {{
            color: {theme.disabled_text};
            background-color: {theme.disabled_bg};
            border-color: {theme.border};
        }}
        #topBar QPushButton, #topBar QToolButton {{
            color: {theme.topbar_button_text};
            background-color: {theme.topbar_button};
            border: 1px solid {theme.topbar_button};
        }}
        #topBar QPushButton:hover, #topBar QToolButton:hover {{
            color: {theme.topbar_button_text};
            background-color: {theme.topbar_button_hover};
            border-color: {theme.topbar_button_hover};
        }}
        #topBar QPushButton:pressed, #topBar QToolButton:pressed {{
            color: {theme.topbar_button_text};
            background-color: {theme.topbar_button_pressed};
            border-color: {theme.topbar_button_pressed};
        }}
        #topBar QPushButton:disabled, #topBar QToolButton:disabled {{
            color: {theme.disabled_text};
            background-color: {theme.disabled_bg};
            border-color: {theme.disabled_bg};
        }}
        #TOP_RUN_ALL, #PRIMARY_SAVE_SETTINGS, QPushButton[primary="true"] {{
            color: {theme.primary_text};
            background-color: {theme.primary};
            border: 2px solid {theme.primary};
            padding: 7px 12px;
            font-weight: 700;
        }}
        #TOP_RUN_ALL:hover, #PRIMARY_SAVE_SETTINGS:hover, QPushButton[primary="true"]:hover {{
            color: {theme.primary_text};
            background-color: {theme.primary_hover};
            border-color: {theme.primary_hover};
        }}
        #TOP_RUN_ALL:pressed, #PRIMARY_SAVE_SETTINGS:pressed, QPushButton[primary="true"]:pressed {{
            color: {theme.primary_text};
            background-color: {theme.primary_pressed};
            border-color: {theme.primary_pressed};
        }}
        #TOP_RUN_ALL:disabled, #PRIMARY_SAVE_SETTINGS:disabled, QPushButton[primary="true"]:disabled {{
            color: {theme.disabled_text};
            background-color: {theme.disabled_bg};
            border-color: {theme.border};
        }}
        QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox {{
            min-height: 28px;
            color: {theme.input_text};
            background-color: {theme.input_bg};
            border: 1px solid {theme.border};
            border-radius: 3px;
            padding: 4px 6px;
            selection-color: {theme.selection_text};
            selection-background-color: {theme.selection};
            placeholder-text-color: {theme.placeholder};
        }}
        QLineEdit:read-only, QPlainTextEdit:read-only, QTextEdit:read-only {{
            color: {theme.text};
            background-color: {theme.surface_alt};
        }}
        QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,
        QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled, QComboBox:disabled {{
            color: {theme.disabled_text};
            background-color: {theme.disabled_bg};
            border-color: {theme.border};
        }}
        QLineEdit[invalid="true"], QSpinBox[invalid="true"], QDoubleSpinBox[invalid="true"],
        QDateEdit[invalid="true"], QComboBox[invalid="true"] {{
            color: {theme.input_text};
            background-color: {theme.warning_bg};
            border: 3px solid {theme.danger};
        }}
        QComboBox QAbstractItemView {{
            color: {theme.input_text};
            background-color: {theme.input_bg};
            border: 1px solid {theme.border};
            selection-color: {theme.selection_text};
            selection-background-color: {theme.selection};
            outline: 0;
        }}
        QCheckBox, QRadioButton {{
            color: {theme.text};
            background-color: transparent;
            spacing: 7px;
        }}
        QCheckBox:disabled, QRadioButton:disabled {{
            color: {theme.disabled_text};
        }}
        QGroupBox {{
            color: {theme.text};
            background-color: {theme.surface};
            border: 1px solid {theme.border};
            border-radius: 5px;
            margin-top: 12px;
            padding-top: 8px;
            font-weight: 700;
        }}
        QGroupBox::title {{
            color: {theme.text};
            background-color: {theme.surface};
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 0 5px;
        }}
        QFrame[frameShape="6"], QFrame[interactiveCard="true"],
        QFrame[emptyState="true"], QFrame[dropZone="true"] {{
            color: {theme.text};
            background-color: {theme.surface};
            border: 1px solid {theme.border};
            border-radius: 5px;
        }}
        QFrame[dropZone="true"] {{
            border: 2px dashed {theme.accent};
        }}
        QFrame[interactiveCard="true"]:focus {{
            border: 3px solid {theme.focus};
        }}
        QAbstractItemView, QTableView, QTableWidget, QListView, QListWidget, QTreeView {{
            color: {theme.text};
            background-color: {theme.surface};
            alternate-background-color: {theme.surface_alt};
            border: 1px solid {theme.border};
            selection-color: {theme.selection_text};
            selection-background-color: {theme.selection};
            outline: 0;
        }}
        QAbstractItemView::item {{
            color: {theme.text};
            padding: 4px;
        }}
        QAbstractItemView::item:selected {{
            color: {theme.selection_text};
            background-color: {theme.selection};
        }}
        QAbstractItemView::item:disabled {{
            color: {theme.disabled_text};
            background-color: {theme.disabled_bg};
        }}
        QHeaderView::section {{
            color: {theme.header_text};
            background-color: {theme.header_bg};
            border: 0;
            border-right: 1px solid {theme.border};
            border-bottom: 1px solid {theme.border};
            padding: 6px;
            font-weight: 700;
        }}
        #navigation {{
            color: {theme.text};
            background-color: {theme.nav_bg};
            border: 0;
            padding: 8px;
        }}
        #navigation::item {{
            color: {theme.text};
            background-color: transparent;
            padding: 10px;
            margin: 2px;
            border-radius: 3px;
        }}
        #navigation::item:hover {{
            color: {theme.accent_text};
            background-color: {theme.accent};
        }}
        #navigation::item:selected {{
            color: {theme.nav_selected_text};
            background-color: {theme.nav_selected};
            border-left: 4px solid {theme.focus};
            font-weight: 700;
        }}
        QTabBar::tab {{
            color: {theme.text};
            background-color: {theme.surface_alt};
            border: 1px solid {theme.border};
            padding: 7px 11px;
            margin-right: 2px;
        }}
        QTabBar::tab:hover {{
            color: {theme.accent_text};
            background-color: {theme.accent};
        }}
        QTabBar::tab:selected {{
            color: {theme.accent_text};
            background-color: {theme.accent};
            font-weight: 700;
        }}
        QTabBar::tab:disabled {{
            color: {theme.disabled_text};
            background-color: {theme.disabled_bg};
        }}
        QMenu {{
            color: {theme.text};
            background-color: {theme.surface};
            border: 1px solid {theme.border};
            padding: 4px;
        }}
        QMenu::item {{
            color: {theme.text};
            background-color: transparent;
            padding: 6px 28px 6px 10px;
        }}
        QMenu::item:selected {{
            color: {theme.selection_text};
            background-color: {theme.selection};
        }}
        QMenu::item:disabled {{
            color: {theme.disabled_text};
            background-color: {theme.disabled_bg};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {theme.border};
            margin: 4px 8px;
        }}
        QToolTip {{
            color: {theme.tooltip_text};
            background-color: {theme.tooltip_bg};
            border: 1px solid {theme.border};
            padding: 6px;
        }}
        QStatusBar {{
            color: {theme.text};
            background-color: {theme.surface};
            border-top: 1px solid {theme.border};
        }}
        QStatusBar QLabel {{
            color: {theme.text};
            background-color: transparent;
        }}
        QDockWidget {{
            color: {theme.text};
            background-color: {theme.window};
        }}
        QDockWidget::title {{
            color: {theme.header_text};
            background-color: {theme.header_bg};
            border: 1px solid {theme.border};
            padding: 6px;
            font-weight: 700;
        }}
        QProgressBar {{
            color: {theme.progress_text};
            background-color: {theme.progress_bg};
            border: 1px solid {theme.border};
            border-radius: 3px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            background-color: {theme.progress_chunk};
        }}
        QScrollBar:vertical, QScrollBar:horizontal {{
            background-color: {theme.surface_alt};
            border: 1px solid {theme.border};
        }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            background-color: {theme.border};
            min-height: 24px;
            min-width: 24px;
        }}
        QScrollArea, QScrollArea > QWidget > QWidget {{
            background-color: {theme.window};
        }}
        #GLOBAL_SELECTION_TRAY {{
            color: {theme.success_text};
            background-color: {theme.success_bg};
            border-top: 2px solid {theme.border};
        }}
        #GLOBAL_SELECTION_TRAY QLabel {{
            color: {theme.success_text};
        }}
        #SETTINGS_VALIDATION_SUMMARY {{
            padding: 8px;
            border-radius: 4px;
        }}
        #SETTINGS_VALIDATION_SUMMARY[state="invalid"] {{
            color: {theme.danger_text};
            background-color: {theme.danger};
            border: 2px solid {theme.danger};
        }}
        #SETTINGS_VALIDATION_SUMMARY[state="valid"] {{
            color: {theme.success_text};
            background-color: {theme.success_bg};
            border: 1px solid {theme.border};
        }}
        #MATCH_REVIEW_BANNER {{
            color: {theme.warning_text};
            background-color: {theme.warning_bg};
            border: 2px solid {theme.border};
            border-radius: 4px;
            padding: 6px;
        }}
        #MATCH_REVIEW_BANNER QLabel {{
            color: {theme.warning_text};
            font-weight: 600;
        }}
        QPushButton:focus, QToolButton:focus, QLineEdit:focus, QPlainTextEdit:focus,
        QTextEdit:focus, QTableView:focus, QTableWidget:focus, QListWidget:focus,
        QListView:focus, QTreeView:focus, QComboBox:focus, QSpinBox:focus,
        QDoubleSpinBox:focus, QDateEdit:focus, QCheckBox:focus, QRadioButton:focus {{
            border: 3px solid {theme.focus};
        }}
    """
