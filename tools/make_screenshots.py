"""Generates the README screenshots — with no personal data in them.

Real clips are encoded into a scratch folder so the file list shows genuine
sizes and durations, then every path that would identify this machine (the
scratch folder, the local ffmpeg location, the chosen folders) is replaced
with a neutral stand-in before the grab. The UI itself is untouched.

Run:  .venv\\Scripts\\python tools\\make_screenshots.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication

from ffmpeg_studio.ffmpeg import locate
from ffmpeg_studio.settings import Settings
from ffmpeg_studio.ui import theme
from ffmpeg_studio.ui.main_window import MainWindow

DOCS = Path(__file__).parent.parent / "docs"

# what the screenshots show instead of this machine's real paths
SHOWN_IN = r"D:\Recordings\raw"
SHOWN_OUT = r"D:\Recordings\converted"
SHOWN_FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"

# (file name, lavfi source, seconds) — varied so the list looks like real work
CLIPS = [
    ("VRChat_POV_2026-07-31.mp4", "testsrc2", 96),
    ("gameplay_capture.mp4", "smptebars", 41),
    ("stream_highlight.mp4", "testsrc2", 12),
    ("desk_recording.mp4", "smptebars", 63),
]


def make_clips(install: locate.FFmpegInstall, folder: Path) -> None:
    for name, source, seconds in CLIPS:
        target = folder / name
        if target.exists():
            continue
        subprocess.run(
            [str(install.ffmpeg), "-hide_banner", "-y",
             "-f", "lavfi", "-i",
             f"{source}=size=1920x1080:rate=30:duration={seconds}",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
             "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
             "-crf", "34", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2",
             "-shortest", str(target)],
            capture_output=True, timeout=300,
            creationflags=locate.popen_flags())


def scrub(win: MainWindow, scratch: Path) -> None:
    """Replace anything that names this machine with the stand-ins."""
    win.in_row.set_path(SHOWN_IN)
    win.out_row.set_path(SHOWN_OUT)
    win.status_ffmpeg.setText(SHOWN_FFMPEG)
    # the preview is the real command; only its paths get anonymised
    text = (win.preview.toPlainText()
            .replace(str(scratch / "output"), SHOWN_OUT)
            .replace(str(scratch), SHOWN_IN))
    win.preview.setPlainText(text)
    win.log_view.setPlainText("")


def wait_for_probes(app: QApplication, win: MainWindow,
                    timeout: float = 60.0) -> None:
    """Spin until every row has its duration, so no '…' placeholders show."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        rows = list(win.files._items())
        if rows and all(item.text(2) not in ("…", "") for item in rows):
            return
        time.sleep(0.05)
    print("warning: probes did not finish in time")


def shoot(app: QApplication, which: str, scratch: Path, profile: str,
          out_name: str) -> None:
    app.setStyleSheet(theme.build_qss(which))
    settings = Settings()
    settings.theme = which
    settings.input_dir = str(scratch)
    settings.output_dir = str(scratch / "output")
    settings.open_when_done = False
    settings.save = lambda: None          # never touch the real settings

    win = MainWindow(settings)
    win.resize(1400, 900)
    win.show()
    for _ in range(4):
        app.processEvents()

    idx = win.profile_combo.findText(profile)
    if idx >= 0:
        win.profile_combo.setCurrentIndex(idx)
    wait_for_probes(app, win)
    win._update_preview()
    app.processEvents()
    scrub(win, scratch)
    app.processEvents()

    DOCS.mkdir(parents=True, exist_ok=True)
    win.grab().save(str(DOCS / out_name))
    print(f"wrote {DOCS / out_name}")
    win.close()
    app.processEvents()


def main() -> None:
    install = locate.find_ffmpeg()
    if install is None:
        raise SystemExit("ffmpeg needed to build the demo clips")

    app = QApplication([])
    app.setStyle("Fusion")
    with tempfile.TemporaryDirectory(prefix="ffs_shots_") as tmp:
        scratch = Path(tmp)
        make_clips(install, scratch)
        shoot(app, "neon", scratch, "Discord-ready (max quality)",
              "screenshot.png")
        shoot(app, "midnight", scratch, "RGB 4-4-4 master (high quality)",
              "screenshot_midnight.png")


if __name__ == "__main__":
    main()
