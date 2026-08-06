"""The input-file list: checkable media files with size/duration/status."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRunnable, Qt, QThreadPool, Signal, QObject
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..ffmpeg.command import format_seconds
from ..ffmpeg.probe import MediaInfo, probe

MEDIA_EXTS = {
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".mpg", ".mpeg", ".ts",
    ".m2ts", ".wmv", ".flv", ".3gp", ".gif", ".webp",
    ".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aiff",
}

COL_NAME, COL_SIZE, COL_DUR, COL_STATUS = range(4)


class _ProbeSignals(QObject):
    got = Signal(str, object)          # path str, MediaInfo


class _ProbeTask(QRunnable):
    def __init__(self, ffprobe: Path, path: Path, signals: _ProbeSignals):
        super().__init__()
        self.ffprobe, self.path, self.signals = ffprobe, path, signals

    def run(self) -> None:
        info = probe(self.ffprobe, self.path)
        self.signals.got.emit(str(self.path), info)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return "?"


class FilesPanel(QWidget):
    """Lists media files of the input folder; keeps check state on refresh."""

    selection_changed = Signal()
    folder_dropped = Signal(str, list)   # folder path, [file names to check]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder: Path | None = None
        self._ffprobe: Path | None = None
        self._exclude: Path | None = None
        self._infos: dict[str, MediaInfo] = {}
        self._signals = _ProbeSignals()
        self._signals.got.connect(self._on_probed)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.refresh_btn = QPushButton("⟳ Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        self.all_btn = QPushButton("All")
        self.all_btn.clicked.connect(lambda: self._check_all(True))
        self.none_btn = QPushButton("None")
        self.none_btn.clicked.connect(lambda: self._check_all(False))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("filter…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.recurse = QCheckBox("Subfolders")
        self.recurse.setToolTip(
            "Also process files in sub-folders, mirroring the folder tree "
            "into the output folder")
        self.recurse.toggled.connect(lambda _on: self.refresh())
        self.count_label = QLabel("")
        self.count_label.setObjectName("Hint")
        for w in (self.refresh_btn, self.all_btn, self.none_btn,
                  self.recurse):
            bar.addWidget(w)
        bar.addWidget(self.filter_edit, 1)
        bar.addWidget(self.count_label)
        lay.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Size", "Length", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().resizeSection(COL_NAME, 320)
        self.tree.header().resizeSection(COL_SIZE, 80)
        self.tree.header().resizeSection(COL_DUR, 70)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.tree, 1)

        self.drop_hint = QLabel(
            "Drop a folder (or files) here,\nor pick an INPUT folder above.",
            self.tree.viewport())
        self.drop_hint.setObjectName("Hint")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.setAcceptDrops(True)

    # -- population ------------------------------------------------------
    def set_context(self, folder: str, ffprobe: Path | None,
                    check_names: list[str] | None = None,
                    exclude_dir: str = "") -> None:
        self._folder = Path(folder) if folder else None
        self._ffprobe = ffprobe
        self.set_exclude(exclude_dir)
        self.refresh(check_names)

    def set_exclude(self, folder: str) -> None:
        """Never list files under here — it's where results are written, so
        recursing into it would feed outputs back in as inputs."""
        self._exclude = Path(folder).resolve() if folder else None

    def _is_excluded(self, path: Path) -> bool:
        if self._exclude is None:
            return False
        try:
            return self._exclude in path.resolve().parents
        except OSError:
            return False

    def _scan(self) -> list[Path]:
        if not (self._folder and self._folder.is_dir()):
            return []
        pattern = "**/*" if self.recurse.isChecked() else "*"
        try:
            found = [p for p in self._folder.glob(pattern)
                     if p.is_file() and p.suffix.lower() in MEDIA_EXTS
                     and not self._is_excluded(p)]
        except OSError:
            return []
        return sorted(found, key=lambda p: str(p).lower())

    def display_name(self, path: Path) -> str:
        """File name, or the sub-path when recursing so duplicates are clear."""
        if self._folder is not None:
            try:
                return str(path.relative_to(self._folder))
            except ValueError:
                pass
        return path.name

    def refresh(self, check_names: list[str] | None = None) -> None:
        had_items = self.tree.topLevelItemCount() > 0
        listed_before = {self._path_of(item) for item in self._items()}
        checked_before = {
            self._path_of(item)
            for item in self._items()
            if item.checkState(COL_NAME) == Qt.CheckState.Checked}
        self.tree.blockSignals(True)
        self.tree.clear()

        for path in self._scan():
            item = QTreeWidgetItem(
                [self.display_name(path), human_size(path.stat().st_size),
                 "…", ""])
            item.setData(COL_NAME, Qt.ItemDataRole.UserRole, str(path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if check_names is not None:
                on = path.name in check_names
            elif not had_items:
                on = True                      # fresh folder: all selected
            elif str(path) in listed_before:
                on = str(path) in checked_before   # keep what the user set
            else:
                # newly revealed — a new file on disk, or "Subfolders" was
                # just switched on. Opting these in is what you'd expect.
                on = True
            item.setCheckState(
                COL_NAME,
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            item.setTextAlignment(COL_SIZE, Qt.AlignmentFlag.AlignRight)
            item.setTextAlignment(COL_DUR, Qt.AlignmentFlag.AlignRight)
            self.tree.addTopLevelItem(item)
            key = str(path)
            cached = self._infos.get(key)
            if cached is not None:
                self._fill_info(item, cached)
            elif self._ffprobe is not None:
                self._pool.start(_ProbeTask(self._ffprobe, path, self._signals))

        self.tree.blockSignals(False)
        self._apply_filter(self.filter_edit.text())
        self._update_count()
        self.drop_hint.setVisible(self.tree.topLevelItemCount() == 0)
        self.selection_changed.emit()

    def _on_probed(self, path_str: str, info: MediaInfo) -> None:
        self._infos[path_str] = info
        for item in self._items():
            if self._path_of(item) == path_str:
                self._fill_info(item, info)
                break

    def _fill_info(self, item: QTreeWidgetItem, info: MediaInfo) -> None:
        item.setText(COL_DUR, format_seconds(info.duration))
        tip = info.summary()
        if tip:
            item.setToolTip(COL_NAME, tip)

    # -- checking / filtering -------------------------------------------
    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            yield self.tree.topLevelItem(i)

    @staticmethod
    def _path_of(item: QTreeWidgetItem) -> str:
        return item.data(COL_NAME, Qt.ItemDataRole.UserRole) or ""

    def _check_all(self, on: bool) -> None:
        self.tree.blockSignals(True)
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for item in self._items():
            if not item.isHidden():
                item.setCheckState(COL_NAME, state)
        self.tree.blockSignals(False)
        self._update_count()
        self.selection_changed.emit()

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for item in self._items():
            item.setHidden(bool(text) and text not in item.text(COL_NAME).lower())

    def _on_item_changed(self, _item, col: int) -> None:
        if col == COL_NAME:
            self._update_count()
            self.selection_changed.emit()

    def _update_count(self) -> None:
        total = self.tree.topLevelItemCount()
        checked = len(self.checked_files())
        self.count_label.setText(f"{checked}/{total} selected")

    def checked_files(self) -> list[Path]:
        return [Path(self._path_of(item)) for item in self._items()
                if item.checkState(COL_NAME) == Qt.CheckState.Checked
                and self._path_of(item)]

    def info_for(self, path: Path) -> MediaInfo | None:
        return self._infos.get(str(path))

    def first_checked_info(self) -> MediaInfo | None:
        for path in self.checked_files():
            info = self._infos.get(str(path))
            if info is not None:
                return info
        return None

    # -- status column ---------------------------------------------------
    def set_status(self, path: Path, text: str) -> None:
        target = str(path)
        for item in self._items():
            if self._path_of(item) == target:
                item.setText(COL_STATUS, text)
                break

    def clear_statuses(self) -> None:
        for item in self._items():
            item.setText(COL_STATUS, "")

    def set_locked(self, locked: bool) -> None:
        for w in (self.refresh_btn, self.all_btn, self.none_btn, self.tree,
                  self.recurse):
            w.setEnabled(not locked)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.drop_hint.setGeometry(self.tree.viewport().rect())

    # -- drag & drop -----------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if not paths:
            return
        if paths[0].is_dir():
            self.folder_dropped.emit(str(paths[0]), [])
            return
        files = [p for p in paths
                 if p.is_file() and p.suffix.lower() in MEDIA_EXTS]
        if files:
            self.folder_dropped.emit(str(files[0].parent),
                                     [p.name for p in files])
