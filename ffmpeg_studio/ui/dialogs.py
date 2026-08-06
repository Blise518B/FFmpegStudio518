"""Dialogs: the FFmpeg downloader and the About box."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QVBoxLayout)

from .. import __version__, APP_NAME
from ..ffmpeg import locate


class _DownloadThread(QThread):
    progressed = Signal(int, int, str)
    done = Signal(object, str)            # FFmpegInstall | None, error text

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cancelled = False

    def run(self) -> None:
        try:
            install = locate.download_ffmpeg(
                lambda d, t, m: self.progressed.emit(d, t, m),
                lambda: self.cancelled)
        except Exception as exc:  # noqa: BLE001 — show any failure to the user
            self.done.emit(None, str(exc))
            return
        self.done.emit(install, "")


class DownloadDialog(QDialog):
    """One-click 'get FFmpeg' for machines that don't have it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download FFmpeg")
        self.setModal(True)
        self.setFixedWidth(420)
        self.install: locate.FFmpegInstall | None = None

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        info = QLabel(
            "This downloads the official <b>gyan.dev release-essentials</b> "
            "build of FFmpeg (~90 MB) and stores it privately for this app "
            "— nothing else on the system is touched.")
        info.setWordWrap(True)
        lay.addWidget(info)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        self.status = QLabel("Ready.")
        self.status.setObjectName("Hint")
        lay.addWidget(self.status)

        self.go_btn = QPushButton("Download")
        self.go_btn.setObjectName("Primary")
        self.go_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        lay.addWidget(self.go_btn)
        lay.addWidget(self.cancel_btn)

        self._thread: _DownloadThread | None = None

    def _start(self) -> None:
        self.go_btn.setEnabled(False)
        self._thread = _DownloadThread(self)
        self._thread.progressed.connect(self._on_progress)
        self._thread.done.connect(self._on_done)
        self._thread.start()

    def _on_progress(self, done: int, total: int, message: str) -> None:
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done / total * 1000))
            self.status.setText(
                f"{message}  {done // 1_048_576} / {total // 1_048_576} MB")
        else:
            self.bar.setRange(0, 0)
            self.status.setText(message)

    def _on_done(self, install, error: str) -> None:
        if install is None:
            self.status.setText(f"Failed: {error}")
            self.go_btn.setEnabled(True)
            return
        self.install = install
        self.accept()

    def reject(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancelled = True
            self._thread.wait(3000)
        super().reject()


def show_about(parent) -> None:
    QMessageBox.about(
        parent, f"About {APP_NAME}",
        f"<h3 style='margin-bottom:2px'>{APP_NAME}</h3>"
        f"<p>Version {__version__}</p>"
        "<p>A friendly batch front-end for FFmpeg: pick an input folder, "
        "choose actions or a saved profile, press start.</p>"
        "<p>FFmpeg is a separate project by the FFmpeg developers "
        "(<a href='https://ffmpeg.org'>ffmpeg.org</a>); Windows builds via "
        "<a href='https://www.gyan.dev/ffmpeg/builds/'>gyan.dev</a>.</p>")
