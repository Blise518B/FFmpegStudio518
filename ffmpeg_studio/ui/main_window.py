"""Main window: header with profiles, folder pickers, file list + actions,
run bar with live progress, collapsible log."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea,
                               QSplitter, QStatusBar, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, resource_path
from .. import profiles as prof
from ..ffmpeg import locate
from ..ffmpeg.command import BuildError, build_plan, preview_text
from ..ffmpeg.probe import MediaInfo, probe
from ..ffmpeg.runner import Job, JobRunner
from ..settings import Settings
from ..spec import JobSpec
from . import theme as theme_mod
from .actions_panel import ActionsPanel
from .dialogs import DownloadDialog, show_about
from .files_panel import FilesPanel
from .widgets import FolderRow


class _GpuDetectThread(QThread):
    found = Signal(set)

    def __init__(self, ffmpeg: Path, parent=None):
        super().__init__(parent)
        self._ffmpeg = ffmpeg

    def run(self) -> None:
        self.found.emit(locate.detect_gpu_encoders(self._ffmpeg))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.install: locate.FFmpegInstall | None = None
        # None = detection hasn't finished yet ("unknown"), which build_plan
        # treats differently from set() ("proven absent"): an explicit NVENC
        # profile keeps its codec instead of silently downgrading to CPU.
        self.gpu_encoders: set[str] | None = None
        self.runner: JobRunner | None = None
        self._jobs_by_row: dict[int, Job] = {}
        self._loaded_spec: dict | None = None
        self._gpu_thread: _GpuDetectThread | None = None

        self.setWindowTitle(APP_NAME)
        icon = resource_path("assets/icon.ico")
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1280, 840)
        self.setMinimumSize(980, 640)

        self._build_ui()
        self._wire()
        self._restore()
        self._locate_ffmpeg(first_run=True)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- header ----------------------------------------------------
        header = QWidget()
        header.setObjectName("Header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 10, 16, 10)
        hl.setSpacing(10)

        title = QLabel("FFMPEG")
        title.setObjectName("AppTitle")
        accent = QLabel("STUDIO 518")
        accent.setObjectName("AppTitleAccent")
        hl.addWidget(title)
        hl.addWidget(accent)
        hl.addSpacing(18)

        hl.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(220)
        hl.addWidget(self.profile_combo)
        self.dirty_label = QLabel("")
        self.dirty_label.setObjectName("HeaderHint")
        self.dirty_label.setToolTip("Unsaved changes to this profile")
        hl.addWidget(self.dirty_label)
        self.save_btn = QPushButton("Save")
        self.saveas_btn = QPushButton("Save as…")
        self.profile_menu_btn = QPushButton("⋯")
        self.profile_menu_btn.setFixedWidth(40)
        hl.addWidget(self.save_btn)
        hl.addWidget(self.saveas_btn)
        hl.addWidget(self.profile_menu_btn)

        hl.addStretch(1)

        self.ffmpeg_chip = QLabel("FFmpeg: …")
        self.ffmpeg_chip.setObjectName("Chip")
        hl.addWidget(self.ffmpeg_chip)
        self.gear_btn = QPushButton("⚙")
        self.gear_btn.setObjectName("GearBtn")
        self.gear_btn.setFixedWidth(42)
        self.help_btn = QPushButton("?")
        self.help_btn.setObjectName("HelpBtn")
        self.help_btn.setFixedWidth(38)
        hl.addWidget(self.gear_btn)
        hl.addWidget(self.help_btn)
        root.addWidget(header)

        # ---- folders ---------------------------------------------------
        folders = QWidget()
        fl = QVBoxLayout(folders)
        fl.setContentsMargins(16, 12, 16, 4)
        fl.setSpacing(8)
        self.in_row = FolderRow("INPUT", "folder with the files to process")
        self.out_row = FolderRow("OUTPUT", "where results are written")
        fl.addWidget(self.in_row)
        fl.addWidget(self.out_row)
        root.addWidget(folders)

        # ---- middle: files | actions ----------------------------------
        self.files = FilesPanel()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(16, 8, 8, 8)
        ll.addWidget(self.files)

        self.actions = ActionsPanel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.actions)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 16, 8)
        rl.setSpacing(8)
        rl.addWidget(scroll, 1)
        self.warn_label = QLabel("")
        self.warn_label.setObjectName("WarnNote")
        self.warn_label.setWordWrap(True)
        self.warn_label.hide()
        rl.addWidget(self.warn_label)
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("CmdPreview")
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(64)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        rl.addWidget(self.preview)

        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.h_split.addWidget(left)
        self.h_split.addWidget(right)
        self.h_split.setStretchFactor(0, 1)
        self.h_split.setStretchFactor(1, 0)
        self.h_split.setSizes([700, 470])

        # log under everything, collapsible
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        self.v_split = QSplitter(Qt.Orientation.Vertical)
        self.v_split.addWidget(self.h_split)
        self.v_split.addWidget(self.log_view)
        self.v_split.setStretchFactor(0, 1)
        self.v_split.setSizes([600, 140])
        self.log_view.setVisible(self.settings.log_visible)
        root.addWidget(self.v_split, 1)

        # ---- run bar ---------------------------------------------------
        runbar = QFrame()
        rb = QHBoxLayout(runbar)
        rb.setContentsMargins(16, 8, 16, 10)
        rb.setSpacing(10)
        self.overall_bar = QProgressBar()
        self.overall_bar.setFormat("ready")
        self.overall_bar.setFixedWidth(180)
        self.overall_bar.setRange(0, 1)
        self.overall_bar.setValue(0)
        self.file_bar = QProgressBar()
        self.file_bar.setRange(0, 1000)
        self.file_bar.setValue(0)
        self.file_bar.setTextVisible(False)
        self.speed_label = QLabel("")
        self.speed_label.setObjectName("HeaderHint")
        self.speed_label.setFixedWidth(52)
        self.log_btn = QPushButton("Log")
        self.log_btn.setCheckable(True)
        self.log_btn.setChecked(self.settings.log_visible)
        self.cancel_btn = QPushButton("■ Cancel")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.setEnabled(False)
        self.start_btn = QPushButton("▶  START")
        self.start_btn.setObjectName("BigStart")
        rb.addWidget(self.overall_bar)
        rb.addWidget(self.file_bar, 1)
        rb.addWidget(self.speed_label)
        rb.addWidget(self.log_btn)
        rb.addWidget(self.cancel_btn)
        rb.addWidget(self.start_btn)
        root.addWidget(runbar)

        self.setCentralWidget(central)

        status = QStatusBar()
        self.status_ffmpeg = QLabel("")
        self.status_right = QLabel(f"{APP_NAME} v{__version__}")
        status.addWidget(self.status_ffmpeg, 1)
        status.addPermanentWidget(self.status_right)
        self.setStatusBar(status)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(self._update_preview)

    # ------------------------------------------------------------------
    def _wire(self) -> None:
        self.in_row.changed.connect(self._on_input_changed)
        self.out_row.changed.connect(self._on_output_changed)
        self.files.selection_changed.connect(self._schedule_preview)
        self.files.folder_dropped.connect(self._on_drop)

        self.actions.changed.connect(self._on_actions_changed)

        self.profile_combo.currentIndexChanged.connect(self._on_profile_pick)
        self.save_btn.clicked.connect(self._save_profile)
        self.saveas_btn.clicked.connect(self._save_profile_as)
        self.profile_menu_btn.clicked.connect(self._profile_menu)

        self.gear_btn.clicked.connect(self._gear_menu)
        self.help_btn.clicked.connect(lambda: show_about(self))
        self.ffmpeg_chip.mousePressEvent = lambda _e: self._ffmpeg_info()

        self.log_btn.toggled.connect(self._toggle_log)
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel)

    # ------------------------------------------------------------------
    # settings / startup
    # ------------------------------------------------------------------
    def _restore(self) -> None:
        s = self.settings
        if s.window_geometry:
            try:
                self.restoreGeometry(
                    QByteArray.fromHex(s.window_geometry.encode()))
            except (ValueError, TypeError):
                pass
        self.in_row.set_path(s.input_dir)
        self.out_row.set_path(s.output_dir)

        prof.ensure_defaults()
        self._reload_profiles(select=s.last_profile)

    def _reload_profiles(self, select: str = "") -> None:
        names = prof.list_profiles()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for row, name in enumerate(names):
            self.profile_combo.addItem(name)
            # hovering an entry in the drop-down explains what it's for
            self.profile_combo.setItemData(row, prof.describe(name),
                                           Qt.ItemDataRole.ToolTipRole)
        idx = self.profile_combo.findText(select) if select else -1
        self.profile_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.profile_combo.blockSignals(False)
        if self.profile_combo.count():
            self._on_profile_pick(self.profile_combo.currentIndex())

    def _save_settings(self) -> None:
        s = self.settings
        s.input_dir = self.in_row.path()
        s.output_dir = self.out_row.path()
        s.last_profile = self.profile_combo.currentText()
        s.log_visible = self.log_btn.isChecked()
        s.window_geometry = bytes(self.saveGeometry().toHex()).decode()
        s.save()

    def closeEvent(self, event) -> None:
        if self.runner is not None and self.runner.running:
            answer = QMessageBox.question(
                self, "Still running",
                "A conversion is still running — cancel it and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.cancel()
        if self._gpu_thread is not None and self._gpu_thread.isRunning():
            self._gpu_thread.wait(5000)
        self._save_settings()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # ffmpeg presence
    # ------------------------------------------------------------------
    def _locate_ffmpeg(self, first_run: bool = False) -> None:
        self.install = locate.find_ffmpeg(self.settings.ffmpeg_path)
        if self.install is not None:
            self.ffmpeg_chip.setText(f"FFmpeg: {self.install.version}")
            self.ffmpeg_chip.setProperty("state", "ok")
            self.status_ffmpeg.setText(str(self.install.ffmpeg))
            self._gpu_thread = _GpuDetectThread(self.install.ffmpeg, self)
            self._gpu_thread.found.connect(self._on_gpu_found)
            self._gpu_thread.start()
        else:
            self.ffmpeg_chip.setText("FFmpeg: not found")
            self.ffmpeg_chip.setProperty("state", "bad")
            self.status_ffmpeg.setText(
                "FFmpeg missing — click the red chip to fix")
        self.ffmpeg_chip.style().unpolish(self.ffmpeg_chip)
        self.ffmpeg_chip.style().polish(self.ffmpeg_chip)

        self._on_input_changed(self.in_row.path())
        if first_run and self.install is None:
            QTimer.singleShot(300, self._offer_download)

    def _on_gpu_found(self, encoders: set) -> None:
        self.gpu_encoders = set(encoders)
        self.actions.set_gpu_encoders(self.gpu_encoders)
        self._schedule_preview()   # "Auto" resolves differently now
        if self.gpu_encoders:
            self.status_ffmpeg.setText(
                f"{self.install.ffmpeg}   ·   GPU: "
                + ", ".join(sorted(self.gpu_encoders)))

    def _offer_download(self) -> None:
        if sys.platform != "win32":
            # the auto-download is a Windows build; offering it here would
            # only ever fail after the full 90 MB
            QMessageBox.information(
                self, "FFmpeg not found",
                "This app drives FFmpeg, but none was found.\n\nInstall it "
                "with your package manager (e.g. sudo apt install ffmpeg "
                "or flatpak/dnf/pacman equivalents), then restart the app.")
            return
        answer = QMessageBox.question(
            self, "FFmpeg not found",
            "This app drives FFmpeg, but no ffmpeg.exe was found on this "
            "PC.\n\nDownload it automatically now? (~90 MB, one time)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._download_ffmpeg()

    def _download_ffmpeg(self) -> None:
        if sys.platform != "win32":
            self._offer_download()
            return
        dlg = DownloadDialog(self)
        if dlg.exec() and dlg.install is not None:
            self._locate_ffmpeg()

    def _ffmpeg_info(self) -> None:
        if self.install is None:
            self._offer_download()
        else:
            QMessageBox.information(
                self, "FFmpeg",
                f"Using: {self.install.ffmpeg}\nffprobe: "
                f"{self.install.ffprobe}\nVersion: {self.install.version}")

    # ------------------------------------------------------------------
    # folders / files
    # ------------------------------------------------------------------
    def _on_input_changed(self, path: str) -> None:
        ffprobe = self.install.ffprobe if self.install else None
        if path and not self.out_row.path():
            # sensible default: an "output" folder next to the input
            self.out_row.set_path(str(Path(path) / "output"))
        self.files.set_context(path, ffprobe,
                               exclude_dir=self.out_row.path())
        self._save_settings()

    def _on_output_changed(self, path: str) -> None:
        # the output folder often sits inside the input one; keep it out of
        # the scan so a recursive run can't pick up its own results
        self.files.set_exclude(path)
        self.files.refresh()
        self._save_settings()

    def _on_drop(self, folder: str, names: list) -> None:
        self.in_row.set_path(folder)
        ffprobe = self.install.ffprobe if self.install else None
        if not self.out_row.path():
            self.out_row.set_path(str(Path(folder) / "output"))
        self.files.set_context(folder, ffprobe,
                               check_names=names if names else None,
                               exclude_dir=self.out_row.path())
        self._save_settings()

    # ------------------------------------------------------------------
    # profiles
    # ------------------------------------------------------------------
    def _on_profile_pick(self, _idx: int) -> None:
        name = self.profile_combo.currentText()
        if not name:
            return
        spec = prof.load_profile(name)
        if spec is None:
            return
        # and hovering the closed combo explains the one that's loaded
        self.profile_combo.setToolTip(prof.describe(name, spec))
        self.actions.set_spec(spec)
        self._loaded_spec = spec.to_dict()
        self._set_dirty(False)
        self._save_settings()

    def _on_actions_changed(self) -> None:
        if self._loaded_spec is not None:
            self._set_dirty(
                self.actions.get_spec().to_dict() != self._loaded_spec)
        self._schedule_preview()

    def _set_dirty(self, dirty: bool) -> None:
        self.dirty_label.setText("● modified" if dirty else "")
        self.save_btn.setEnabled(dirty)

    def _save_profile(self) -> None:
        name = self.profile_combo.currentText()
        if not name:
            self._save_profile_as()
            return
        spec = self.actions.get_spec()
        prof.save_profile(name, spec)
        self._loaded_spec = spec.to_dict()
        self._set_dirty(False)

    def _save_profile_as(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save profile", "Profile name:",
            text=self.profile_combo.currentText() or "My profile")
        name = (name or "").strip()
        if not ok or not name:
            return
        spec = self.actions.get_spec()
        prof.save_profile(name, spec)
        self._loaded_spec = spec.to_dict()
        self._reload_profiles(select=name)

    def _profile_menu(self) -> None:
        menu = QMenu(self)
        rename = menu.addAction("Rename…")
        delete = menu.addAction("Delete")
        menu.addSeparator()
        exp = menu.addAction("Export profile…")
        imp = menu.addAction("Import profile…")
        menu.addSeparator()
        folder = menu.addAction("Open profiles folder")
        restore = menu.addAction("Restore default profiles")
        chosen = menu.exec(self.profile_menu_btn.mapToGlobal(
            self.profile_menu_btn.rect().bottomLeft()))
        name = self.profile_combo.currentText()
        if chosen is rename and name:
            new, ok = QInputDialog.getText(
                self, "Rename profile", "New name:", text=name)
            new = (new or "").strip()
            if ok and new and new != name:
                if prof.rename_profile(name, new):
                    self._reload_profiles(select=new)
                else:
                    QMessageBox.warning(self, "Rename",
                                        "That name is already taken.")
        elif chosen is delete and name:
            if QMessageBox.question(
                    self, "Delete profile",
                    f"Delete profile “{name}”?") == \
                    QMessageBox.StandardButton.Yes:
                prof.delete_profile(name)
                self._reload_profiles()
        elif chosen is exp and name:
            target, _f = QFileDialog.getSaveFileName(
                self, "Export profile", f"{name}.json", "Profile (*.json)")
            if target:
                prof.export_profile(name, Path(target))
        elif chosen is imp:
            source, _f = QFileDialog.getOpenFileName(
                self, "Import profile", "", "Profile (*.json)")
            if source:
                imported = prof.import_profile(Path(source))
                if imported:
                    self._reload_profiles(select=imported)
                else:
                    QMessageBox.warning(self, "Import",
                                        "That file is not a valid profile.")
        elif chosen is folder:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(prof.profiles_dir())))
        elif chosen is restore:
            for pname, pspec in prof.DEFAULT_PROFILES.items():
                prof.save_profile(pname, pspec)
            self._reload_profiles(select=name)

    # ------------------------------------------------------------------
    # gear menu
    # ------------------------------------------------------------------
    def _gear_menu(self) -> None:
        s = self.settings
        menu = QMenu(self)
        theme_menu = menu.addMenu("Theme")
        theme_actions = {}
        for key in theme_mod.THEME_ORDER:
            act = theme_menu.addAction(theme_mod.THEME_LABELS[key])
            act.setCheckable(True)
            act.setChecked(s.theme == key)
            theme_actions[act] = key
        menu.addSeparator()
        overwrite = menu.addAction("Overwrite existing outputs")
        overwrite.setCheckable(True)
        overwrite.setChecked(s.overwrite)
        open_done = menu.addAction("Open output folder when done")
        open_done.setCheckable(True)
        open_done.setChecked(s.open_when_done)
        gpu_dec = menu.addAction("Decode on the GPU when possible")
        gpu_dec.setCheckable(True)
        gpu_dec.setChecked(s.gpu_decode)
        menu.addSeparator()
        set_path = menu.addAction("Set FFmpeg location…")
        download = menu.addAction("Download FFmpeg…")
        menu.addSeparator()
        about = menu.addAction("About")

        chosen = menu.exec(self.gear_btn.mapToGlobal(
            self.gear_btn.rect().bottomLeft()))
        if chosen in theme_actions:
            s.theme = theme_actions[chosen]
            app = QApplication.instance()
            app.setStyleSheet(theme_mod.build_qss(s.theme))
            s.save()
        elif chosen is overwrite:
            s.overwrite = overwrite.isChecked()
            s.save()
            self._schedule_preview()
        elif chosen is open_done:
            s.open_when_done = open_done.isChecked()
            s.save()
        elif chosen is gpu_dec:
            s.gpu_decode = gpu_dec.isChecked()
            s.save()
            self._schedule_preview()
        elif chosen is set_path:
            exe, _f = QFileDialog.getOpenFileName(
                self, "Locate ffmpeg.exe", "", "ffmpeg (ffmpeg*)")
            if exe:
                s.ffmpeg_path = exe
                s.save()
                self._locate_ffmpeg()
        elif chosen is download:
            self._download_ffmpeg()
        elif chosen is about:
            show_about(self)

    # ------------------------------------------------------------------
    # command preview
    # ------------------------------------------------------------------
    def _schedule_preview(self) -> None:
        self._preview_timer.start()

    def _update_preview(self) -> None:
        spec = self.actions.get_spec()
        info = self.files.first_checked_info()
        if info is None:
            info = MediaInfo(path=Path("input.mp4"), duration=60.0,
                             has_video=True, has_audio=True, v_codec="h264",
                             a_codec="aac", width=1920, height=1080,
                             a_channels=2)
        out_dir = Path(self.out_row.path() or "output")
        try:
            plan = build_plan(spec, info, out_dir,
                              overwrite=self.settings.overwrite,
                              gpu_encoders=self.gpu_encoders,
                              gpu_decode=self.settings.gpu_decode)
        except BuildError as exc:
            self.preview.setPlainText(f"⚠ {exc}")
            self.warn_label.hide()
            return
        self.preview.setPlainText(preview_text(plan))
        if plan.notes:
            self.warn_label.setText("⚠ " + "   ·   ".join(plan.notes))
            self.warn_label.show()
        else:
            self.warn_label.hide()

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------
    def _start(self) -> None:
        if self.runner is not None and self.runner.running:
            return
        if self.install is None:
            self._offer_download()
            return
        files = self.files.checked_files()
        if not files:
            QMessageBox.information(self, "Nothing to do",
                                    "No files are selected in the list.")
            return
        out_text = self.out_row.path()
        if not out_text:
            # NB: test the raw string — str(Path("")) is ".", never falsy
            QMessageBox.information(self, "Output folder",
                                    "Pick an output folder first.")
            return
        out_dir = Path(out_text)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Output folder",
                                f"Can't create the output folder:\n{exc}")
            return

        spec = self.actions.get_spec()
        in_root = Path(self.in_row.path() or "")
        jobs: list[Job] = []
        taken: set[str] = set()   # outputs already claimed by this batch
        self.files.clear_statuses()
        skipped = 0
        for row, path in enumerate(files):
            info = self.files.info_for(path)
            if info is None:
                info = probe(self.install.ffprobe, path)
            try:
                target_dir = self._target_dir(out_dir, in_root, path)
                plan = build_plan(spec, info, target_dir,
                                  overwrite=self.settings.overwrite,
                                  gpu_encoders=self.gpu_encoders,
                                  gpu_decode=self.settings.gpu_decode,
                                  taken=taken)
            except BuildError as exc:
                self.files.set_status(path, f"✖ {exc}")
                skipped += 1
                continue
            except OSError as exc:
                self.files.set_status(path, f"✖ {exc.strerror or exc}")
                skipped += 1
                continue
            taken.add(str(plan.output).lower())
            jobs.append(Job(src=path, plan=plan, row=row))
            # surface the plan's decisions at run time, not just in the
            # preview — the log is where you look when a run surprises you
            for note in plan.notes:
                self.log_view.appendPlainText(f"[{path.name}] {note}")
        if not jobs:
            QMessageBox.information(
                self, "Nothing to do",
                "None of the selected files fit this profile "
                f"({skipped} skipped).")
            return

        self._jobs_by_row = {j.row: j for j in jobs}
        self.runner = JobRunner(self.install.ffmpeg, self)
        self.runner.job_started.connect(self._on_job_started)
        self.runner.job_progress.connect(self._on_job_progress)
        self.runner.job_log.connect(self._on_job_log)
        self.runner.job_finished.connect(self._on_job_finished)
        self.runner.queue_finished.connect(self._on_queue_finished)

        self.overall_bar.setFormat("%v / %m files")
        self.overall_bar.setRange(0, len(jobs))
        self.overall_bar.setValue(0)
        self.file_bar.setValue(0)
        self.file_bar.setTextVisible(True)
        self._lock_ui(True)
        self.log_view.appendPlainText(
            f"=== Starting {len(jobs)} job(s) ===")
        for job in jobs:
            self.files.set_status(job.src, "waiting")
        self.runner.start(jobs)

    @staticmethod
    def _target_dir(out_dir: Path, in_root: Path, src: Path) -> Path:
        """Mirror the source's sub-folder under the output folder, so a
        recursive run keeps its tree instead of colliding on equal names."""
        try:
            rel = src.parent.relative_to(in_root)
        except ValueError:
            rel = Path()
        target = out_dir / rel
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _cancel(self) -> None:
        if self.runner is not None:
            self.runner.cancel()

    def _lock_ui(self, locked: bool) -> None:
        for w in (self.actions, self.in_row, self.out_row,
                  self.profile_combo, self.saveas_btn, self.profile_menu_btn):
            w.setEnabled(not locked)
        self.save_btn.setEnabled(not locked and bool(self.dirty_label.text()))
        self.start_btn.setEnabled(not locked)
        self.cancel_btn.setEnabled(locked)
        self.files.set_locked(locked)

    # -- runner feedback -------------------------------------------------
    def _on_job_started(self, row: int) -> None:
        job = self._jobs_by_row.get(row)
        if job:
            self.files.set_status(job.src, "running 0%")
            self.file_bar.setValue(0)
            self.speed_label.setText("")

    def _on_job_progress(self, row: int, pct: float, speed: str) -> None:
        job = self._jobs_by_row.get(row)
        if job:
            self.files.set_status(job.src, f"running {pct:.0f}%")
            self.file_bar.setValue(int(pct * 10))
            self.speed_label.setText(speed)

    def _on_job_log(self, _row: int, text: str) -> None:
        self.log_view.appendPlainText(text.rstrip("\n"))

    def _on_job_finished(self, row: int, ok: bool, message: str) -> None:
        job = self._jobs_by_row.get(row)
        if job:
            self.files.set_status(job.src,
                                  "✔ done" if ok else f"✖ {message[:60]}")
        self.overall_bar.setValue(self.overall_bar.value() + 1)
        self.file_bar.setValue(1000 if ok else 0)

    def _on_queue_finished(self, done: int, failed: int,
                           cancelled: int) -> None:
        self._lock_ui(False)
        self.speed_label.setText("")
        bits = [f"{done} done"]
        if failed:
            bits.append(f"{failed} failed")
        if cancelled:
            bits.append(f"{cancelled} cancelled")
        summary = " · ".join(bits)
        self.log_view.appendPlainText(f"=== Finished: {summary} ===")
        self.statusBar().showMessage(summary, 15000)
        if done and self.settings.open_when_done and not cancelled:
            out = self.out_row.path()
            if out and Path(out).is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    # ------------------------------------------------------------------
    def _toggle_log(self, on: bool) -> None:
        self.log_view.setVisible(on)
        self.settings.log_visible = on
