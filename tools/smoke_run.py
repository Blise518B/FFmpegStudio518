"""Full end-to-end smoke test of the real UI.

Generates two clips into .testdata/in, opens the actual window, waits for the
file list to populate, presses START programmatically, waits for the queue to
finish and asserts both outputs exist. Saves docs/screenshot_run.png mid-run.

Run:  .venv\\Scripts\\python tools\\smoke_run.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ffmpeg_studio.ffmpeg import locate
from ffmpeg_studio.settings import Settings
from ffmpeg_studio.spec import JobSpec
from ffmpeg_studio.ui import theme
from ffmpeg_studio.ui.main_window import MainWindow

ROOT = Path(__file__).parent.parent
IN_DIR = ROOT / ".testdata" / "in"
OUT_DIR = ROOT / ".testdata" / "out"
SHOT = ROOT / "docs" / "screenshot_run.png"


def make_clips(install: locate.FFmpegInstall) -> None:
    IN_DIR.mkdir(parents=True, exist_ok=True)
    for name, src in [("city timelapse.mp4", "testsrc2"),
                      ("game clip.mp4", "smptebars")]:
        target = IN_DIR / name
        if target.exists():
            continue
        run = subprocess.run(
            [str(install.ffmpeg), "-hide_banner", "-y",
             "-f", "lavfi", "-i", f"{src}=size=1280x720:rate=30:duration=4",
             "-f", "lavfi", "-i", "sine=frequency=330:duration=4",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(target)],
            capture_output=True, timeout=60, creationflags=locate.popen_flags())
        assert run.returncode == 0, run.stderr.decode()[-400:]


def main() -> int:
    install = locate.find_ffmpeg()
    assert install is not None, "ffmpeg needed for the smoke test"
    make_clips(install)
    for old in OUT_DIR.glob("*"):
        old.unlink()

    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(theme.build_qss("neon"))

    settings = Settings()
    settings.input_dir = str(IN_DIR)
    settings.output_dir = str(OUT_DIR)
    settings.open_when_done = False
    settings.save = lambda: None          # don't touch the real settings file

    win = MainWindow(settings)
    win.resize(1400, 900)
    win.show()

    state = {"started": False, "shot": False, "result": 1}

    def fail(msg: str) -> None:
        print(f"FAIL: {msg}")
        state["result"] = 1
        app.quit()

    def tick() -> None:
        if not state["started"]:
            if win.files.tree.topLevelItemCount() == 2:
                win.actions.set_spec(JobSpec(
                    container="mp4", video_codec="h264", crf=30,
                    preset="ultrafast", scale_mode="480",
                    audio_mode="encode", audio_bitrate=96, suffix="_test"))
                win.start_btn.click()
                state["started"] = True
            return
        if win.runner is not None and win.runner.running and not state["shot"]:
            SHOT.parent.mkdir(parents=True, exist_ok=True)
            win.grab().save(str(SHOT))
            state["shot"] = True
        if win.runner is not None and not win.runner.running:
            outs = sorted(p.name for p in OUT_DIR.glob("*.mp4"))
            expected = ["city timelapse_test.mp4", "game clip_test.mp4"]
            if outs == expected:
                print(f"OK: {outs}")
                state["result"] = 0
            else:
                print(f"FAIL: outputs = {outs}")
            app.quit()

    poll = QTimer()
    poll.timeout.connect(tick)
    poll.start(200)
    QTimer.singleShot(90_000, lambda: fail("timeout"))

    app.exec()
    win.close()
    app.processEvents()
    return state["result"]


if __name__ == "__main__":
    raise SystemExit(main())
