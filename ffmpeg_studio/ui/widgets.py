"""Small reusable UI pieces: folder pickers and the colored section frames."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout,
                               QWidget)


class FolderRow(QWidget):
    """[ INPUT ] [ path line edit          ] [Browse…] [Open]"""

    changed = Signal(str)

    def __init__(self, tag: str, placeholder: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        label = QLabel(tag)
        label.setObjectName("FolderTag")
        label.setFixedWidth(58)
        lay.addWidget(label)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.editingFinished.connect(
            lambda: self.changed.emit(self.edit.text().strip()))
        lay.addWidget(self.edit, 1)

        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        lay.addWidget(browse)

        open_btn = QPushButton("⤴")
        open_btn.setToolTip("Open this folder in Explorer")
        open_btn.setFixedWidth(36)
        open_btn.clicked.connect(self._open)
        lay.addWidget(open_btn)

        self._tag = tag

    def path(self) -> str:
        return self.edit.text().strip()

    def set_path(self, path: str) -> None:
        self.edit.setText(path)

    def _browse(self) -> None:
        start = self.path() if Path(self.path()).is_dir() else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, f"Choose {self._tag.lower()} folder", start)
        if chosen:
            self.edit.setText(chosen)
            self.changed.emit(chosen)

    def _open(self) -> None:
        p = self.path()
        if p and Path(p).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))


class Section(QFrame):
    """A colored category frame like the reference app's boards:
    tinted header bar with a title, options grid below."""

    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Category")
        self.setProperty("catcolor", color)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 10)
        outer.setSpacing(8)

        header = QWidget()
        header.setObjectName("CatHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 6, 12, 6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CatTitle")
        hl.addWidget(self.title_label)
        hl.addStretch(1)
        self.badge = QLabel("")
        self.badge.setObjectName("CatBadge")
        hl.addWidget(self.badge)
        outer.addWidget(header)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(6, 0, 6, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(8)
        self.grid.setColumnStretch(1, 1)
        outer.addLayout(self.grid)
        self._row = 0

    def add_row(self, label: str, widget: QWidget, hint: str = "") -> None:
        name = QLabel(label)
        name.setObjectName("FieldName")
        self.grid.addWidget(name, self._row, 0, Qt.AlignmentFlag.AlignRight)
        self.grid.addWidget(widget, self._row, 1)
        self._row += 1
        if hint:
            h = QLabel(hint)
            h.setObjectName("Hint")
            h.setWordWrap(True)
            self.grid.addWidget(h, self._row, 1)
            self._row += 1

    def add_wide(self, widget: QWidget) -> None:
        self.grid.addWidget(widget, self._row, 0, 1, 2)
        self._row += 1


def hrow(*widgets, stretch_last: bool = False) -> QWidget:
    """Pack widgets into one horizontal row widget."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for item in widgets:
        lay.addWidget(item)
    if stretch_last:
        lay.addStretch(1)
    return w
