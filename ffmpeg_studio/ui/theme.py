"""App themes — the VRCParameterRelay green-on-black looks, ported.

  * "neon"     (default) — bright neon green, filled colour section headers.
  * "midnight"           — darker, hairline borders, muted (the "broker" look).

Sections of the actions panel are QFrame#Category with a ``catcolor``
property (green/blue/cyan/yellow/red/purple) that tints border + header,
exactly like the reference app's category boards.
"""
from __future__ import annotations

ACCENTS = {"neon": "#31f272", "midnight": "#4af58c"}
THEME_LABELS = {"neon": "Neon (default)", "midnight": "Midnight"}
THEME_ORDER = ["neon", "midnight"]
DEFAULT_THEME = "neon"

# key -> (vibrant, mid-border, dark tint)
CATEGORY_PALETTE = {
    "green":  ("#4af58c", "#2f5e3f", "#10291a"),
    "blue":   ("#7aa7ff", "#3a5384", "#131c30"),
    "cyan":   ("#56d9f2", "#2f6b7a", "#0e2229"),
    "yellow": ("#ffb454", "#6b5320", "#291f0c"),
    "red":    ("#ff5561", "#5c2228", "#2a1014"),
    "purple": ("#d78cff", "#5e3f78", "#221430"),
}

# neon: bright filled header bars per hue (green == the classic look)
_NEON_CAT_BARS = {
    "green":  ("#1c8a3d", "#36a35c"),
    "blue":   ("#1e5fa0", "#3b6ea3"),
    "cyan":   ("#15808f", "#2e93a3"),
    "yellow": ("#a06a14", "#b3813a"),
    "red":    ("#9c2531", "#b04552"),
    "purple": ("#7a3fa8", "#9159ba"),
}


def _neon_cat_variants() -> str:
    out = []
    for key, (bar, border) in _NEON_CAT_BARS.items():
        vib = CATEGORY_PALETTE[key][0]
        out.append(f"""
QFrame#Category[catcolor="{key}"] {{ border: 1px solid {border}; }}
QFrame#Category[catcolor="{key}"] QWidget#CatHeader {{ background: {bar}; }}
QFrame#Category[catcolor="{key}"] QLabel#CatBadge {{ color: {vib}; }}
""")
    return "".join(out)


def _midnight_cat_variants() -> str:
    out = []
    for key, (vib, mid, tint) in CATEGORY_PALETTE.items():
        out.append(f"""
QFrame#Category[catcolor="{key}"] {{ border: 1px solid {mid}; }}
QFrame#Category[catcolor="{key}"] QWidget#CatHeader {{ background: {tint}; }}
QFrame#Category[catcolor="{key}"] QLabel#CatTitle {{ color: {vib}; }}
QFrame#Category[catcolor="{key}"] QLabel#CatBadge {{ color: {vib}; }}
""")
    return "".join(out)


NEON_QSS = """
* { font-family: 'Segoe UI', sans-serif; font-size: 13px; }

QMainWindow, QDialog { background: #0a0c0a; }
QWidget { color: #e6efe8; }
QToolTip { background: #121712; color: #e6efe8; border: 1px solid %(edge)s; }

#Header { background: #0f120f; border-bottom: 1px solid %(edge)s; }
QLabel#AppTitle { font-size: 19px; font-weight: 700; color: #f2f8f3; }
QLabel#AppTitleAccent { font-size: 19px; font-weight: 800; color: %(accent)s; }
QLabel#HeaderHint { color: #5f6f63; font-size: 11px; }

QLabel#Chip {
    background: #131a15; border: 1px solid %(edge)s; border-radius: 10px;
    padding: 3px 12px; color: #94a698; font-size: 12px;
}
QLabel#Chip[state="ok"] { color: #3af0a0; border-color: #22c55e; }
QLabel#Chip[state="bad"] { color: #f87171; border-color: #542a2a; }

QPushButton {
    background: transparent; border: 1px solid %(edge)s; border-radius: 8px;
    padding: 7px 14px; color: #e6efe8;
}
QPushButton:hover { background: #142418; }
QPushButton:pressed { background: #0f150f; }
QPushButton:disabled { color: #4f5c53; border-color: #1d2a20; }
QPushButton#Primary {
    background: %(accent)s; border-color: %(accent)s;
    font-weight: 650; color: #04150b;
}
QPushButton#Primary:hover { background: #62ff97; }
QPushButton#Primary:disabled { background: #1d5a32; border-color: #1d5a32; color: #0a1f12; }
QPushButton#Danger { color: #f87171; border-color: #542a2a; }
QPushButton#Danger:hover { background: #2a1216; }
QPushButton#Danger:disabled { color: #5c3a3e; border-color: #2d2226; background: transparent; }

QPushButton#BigStart {
    background: %(accent)s; border-color: %(accent)s; border-radius: 10px;
    font-weight: 800; font-size: 15px; letter-spacing: 1px;
    color: #04150b; padding: 10px 30px;
}
QPushButton#BigStart:hover { background: #62ff97; }
QPushButton#BigStart:disabled { background: #1d5a32; border-color: #1d5a32; color: #0a1f12; }

QPushButton#GearBtn, QPushButton#HelpBtn { font-weight: 700; padding: 7px 0; }

QToolButton {
    border: 1px solid %(edge)s; border-radius: 8px; padding: 6px 10px;
    color: #e6efe8; background: transparent;
}
QToolButton:hover { background: #142418; }
QToolButton::menu-indicator { image: none; }

/* folder rows */
QLabel#FolderTag {
    color: %(accent)s; font-weight: 700; font-size: 12px;
}

QFrame#Category {
    background: #0e120e; border: 1px solid %(edge)s; border-radius: 14px;
}
QWidget#CatHeader { background: #1c8a3d; border-radius: 9px; }
QLabel#CatTitle {
    background: transparent; font-size: 14px; font-weight: 700; color: #eafaee;
}
QLabel#CatBadge { background: transparent; color: #eafaee; font-size: 11px; }

QLabel#FieldName { color: #94a698; }
QLabel#Hint { color: #5f6f63; font-size: 11px; }
QLabel#WarnNote { color: #ffb454; font-size: 12px; }

QPlainTextEdit#CmdPreview, QPlainTextEdit#LogView {
    background: #070907; border: 1px solid #1d2a20; border-radius: 8px;
    color: #7fdf9f; font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px; padding: 6px;
}
QPlainTextEdit#LogView { color: #9fb3a6; }

QSlider::groove:horizontal { height: 5px; background: #1d5a32; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: %(accent)s;
}
QSlider::sub-page:horizontal { background: #22d968; border-radius: 2px; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator {
    border: 1px solid %(edge)s; border-radius: 4px; background: #121a13;
}
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; }
QRadioButton::indicator {
    border: 1px solid %(edge)s; border-radius: 8px; background: #121a13;
}
QRadioButton::indicator:checked { background: %(accent)s; border-color: %(accent)s; }

QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox {
    background: #121a13; border: 1px solid %(edge)s; border-radius: 7px; padding: 5px 8px;
    selection-background-color: %(accent)s;
    selection-color: #04150b;
}
QSpinBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled, QComboBox:disabled {
    color: #4f5c53; border-color: #1d2a20; background: #0d120e;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #121a13; border: 1px solid %(edge)s;
    selection-background-color: #1b5a30;
}

QTreeWidget {
    background: #0f120f; border: 1px solid #1d2a20; border-radius: 10px;
    alternate-background-color: #121712;
}
QTreeWidget::item { height: 26px; }
QTreeWidget::item:selected { background: #1b5a30; }
QTreeWidget::indicator {
    width: 15px; height: 15px; border: 1px solid %(edge)s;
    border-radius: 4px; background: #121a13;
}
QTreeWidget::indicator:checked { background: %(accent)s; border-color: %(accent)s; }
QHeaderView::section {
    background: #0f120f; border: none; border-bottom: 1px solid %(edge)s;
    padding: 6px 8px; color: #7f8f81;
}

QStatusBar {
    background: #0f120f; color: #5f6f63; font-size: 11px;
    border-top: 1px solid %(edge)s;
}
QStatusBar::item { border: none; }
QMenu { background: #121712; border: 1px solid %(edge)s; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 5px; }
QMenu::item:selected { background: #16311e; }
QMenu::separator { height: 1px; background: #1d2a20; margin: 4px 8px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #245c38; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(accent)s; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #245c38; border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: %(accent)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QProgressBar {
    background: #121a13; border: 1px solid %(edge)s; border-radius: 6px;
    text-align: center; color: #e6efe8; font-size: 11px;
}
QProgressBar::chunk { background: %(accent)s; border-radius: 5px; }

QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: #1d2a20; }
QSplitter::handle:hover { background: %(accent)s; }
""" % {"accent": "#31f272", "edge": "#36a35c"} + _neon_cat_variants()


MIDNIGHT_QSS = """
* { font-family: 'Segoe UI', sans-serif; font-size: 13px; }

QMainWindow, QDialog { background: #07090c; }
QWidget { color: #c9d4cc; }
QToolTip { background: #0b0f0c; color: #c9d4cc; border: 1px solid #243029; }

#Header { background: #090d0a; border-bottom: 1px solid #243029; }
QLabel#AppTitle { font-size: 19px; font-weight: 700; color: #c9d4cc; }
QLabel#AppTitleAccent { font-size: 19px; font-weight: 800; color: #4af58c; }
QLabel#HeaderHint { color: #5f6f64; font-size: 11px; }

QLabel#Chip {
    background: #0b0f0c; border: 1px solid #243029; border-radius: 10px;
    padding: 3px 12px; color: #7c8a80; font-size: 12px;
}
QLabel#Chip[state="ok"] { color: #4af58c; border-color: #2f5e3f; }
QLabel#Chip[state="bad"] { color: #ff5561; border-color: #5c2228; }

QPushButton {
    background: transparent; border: 1px solid #243029; border-radius: 8px;
    padding: 7px 14px; color: #c9d4cc;
}
QPushButton:hover { background: #0d1712; border-color: #4af58c; color: #4af58c; }
QPushButton:pressed { background: #0b110d; }
QPushButton:disabled { color: #3f4a42; border-color: #1c2620; }
QPushButton#Primary {
    background: #4af58c; border-color: #4af58c; font-weight: 650; color: #04120a;
}
QPushButton#Primary:hover { background: #7dffb0; border-color: #7dffb0; color: #04120a; }
QPushButton#Primary:disabled { background: #1b3326; border-color: #1b3326; color: #0a1f12; }
QPushButton#Danger { color: #ff5561; border-color: #5c2228; }
QPushButton#Danger:hover { background: #170a0c; border-color: #ff5561; color: #ff5561; }
QPushButton#Danger:disabled { color: #4a2b2e; border-color: #241418; background: transparent; }

QPushButton#BigStart {
    background: #4af58c; border-color: #4af58c; border-radius: 10px;
    font-weight: 800; font-size: 15px; letter-spacing: 1px;
    color: #04120a; padding: 10px 30px;
}
QPushButton#BigStart:hover { background: #7dffb0; border-color: #7dffb0; color: #04120a; }
QPushButton#BigStart:disabled { background: #1b3326; border-color: #1b3326; color: #0a1f12; }

QPushButton#GearBtn, QPushButton#HelpBtn { font-weight: 700; padding: 7px 0; }

QToolButton {
    border: 1px solid #243029; border-radius: 8px; padding: 6px 10px;
    color: #c9d4cc; background: transparent;
}
QToolButton:hover { background: #0d1712; border-color: #4af58c; color: #4af58c; }
QToolButton::menu-indicator { image: none; }

QLabel#FolderTag { color: #4af58c; font-weight: 700; font-size: 12px; }

QFrame#Category {
    background: #090c0a; border: 1px solid #2f5e3f; border-radius: 14px;
}
QWidget#CatHeader { background: #10291a; border-radius: 9px; }
QLabel#CatTitle {
    background: transparent; font-size: 14px; font-weight: 700; color: #4af58c;
}
QLabel#CatBadge { background: transparent; color: #7c8a80; font-size: 11px; }

QLabel#FieldName { color: #7c8a80; }
QLabel#Hint { color: #5f6f64; font-size: 11px; }
QLabel#WarnNote { color: #ffb454; font-size: 12px; }

QPlainTextEdit#CmdPreview, QPlainTextEdit#LogView {
    background: #05070a; border: 1px solid #1c2620; border-radius: 8px;
    color: #4af58c; font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px; padding: 6px;
}
QPlainTextEdit#LogView { color: #8a9a8f; }

QSlider::groove:horizontal { height: 5px; background: #1b3326; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: #4af58c;
}
QSlider::sub-page:horizontal { background: #35b56a; border-radius: 2px; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator {
    border: 1px solid #243029; border-radius: 4px; background: #0a0e0b;
}
QCheckBox::indicator:checked { background: #4af58c; border-color: #4af58c; }
QRadioButton::indicator {
    border: 1px solid #243029; border-radius: 8px; background: #0a0e0b;
}
QRadioButton::indicator:checked { background: #4af58c; border-color: #4af58c; }

QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox {
    background: #0a0e0b; border: 1px solid #243029; border-radius: 7px; padding: 5px 8px;
    selection-background-color: #4af58c;
    selection-color: #04120a;
}
QSpinBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled, QComboBox:disabled {
    color: #3f4a42; border-color: #1c2620; background: #080b09;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #0a0e0b; border: 1px solid #243029;
    selection-background-color: #14311f;
}

QTreeWidget {
    background: #090d0a; border: 1px solid #1c2620; border-radius: 10px;
    alternate-background-color: #0c110e;
}
QTreeWidget::item { height: 26px; }
QTreeWidget::item:selected { background: #14311f; }
QTreeWidget::indicator {
    width: 15px; height: 15px; border: 1px solid #243029;
    border-radius: 4px; background: #0a0e0b;
}
QTreeWidget::indicator:checked { background: #4af58c; border-color: #4af58c; }
QHeaderView::section {
    background: #090d0a; border: none; border-bottom: 1px solid #243029;
    padding: 6px 8px; color: #6f8074;
}

QStatusBar {
    background: #090d0a; color: #5f6f64; font-size: 11px;
    border-top: 1px solid #243029;
}
QStatusBar::item { border: none; }
QMenu { background: #0b0f0c; border: 1px solid #243029; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 5px; }
QMenu::item:selected { background: #14311f; }
QMenu::separator { height: 1px; background: #1c2620; margin: 4px 8px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #2f4436; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4af58c; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #2f4436; border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #4af58c; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QProgressBar {
    background: #0a0e0b; border: 1px solid #243029; border-radius: 6px;
    text-align: center; color: #c9d4cc; font-size: 11px;
}
QProgressBar::chunk { background: #4af58c; border-radius: 5px; }

QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: #1c2620; }
QSplitter::handle:hover { background: #4af58c; }
""" + _midnight_cat_variants()


THEMES = {"neon": NEON_QSS, "midnight": MIDNIGHT_QSS}


def build_qss(theme: str = DEFAULT_THEME) -> str:
    return THEMES.get(theme, THEMES[DEFAULT_THEME])


def accent_of(theme: str = DEFAULT_THEME) -> str:
    return ACCENTS.get(theme, ACCENTS[DEFAULT_THEME])
