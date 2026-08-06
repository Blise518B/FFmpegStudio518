"""Offscreen smoke test + screenshot: renders the main window without a
display and saves docs/screenshot.png. Run:  .venv\\Scripts\\python tools\\ui_preview.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication

from ffmpeg_studio.settings import Settings
from ffmpeg_studio.ui import theme
from ffmpeg_studio.ui.main_window import MainWindow

OUT = Path(__file__).parent.parent / "docs" / "screenshot.png"


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "neon"
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(theme.build_qss(which))

    settings = Settings()          # fresh, don't touch the user's real ones
    settings.theme = which
    win = MainWindow(settings)
    win.resize(1400, 900)
    win.show()
    app.processEvents()
    app.processEvents()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = OUT if which == "neon" else OUT.with_name(f"screenshot_{which}.png")
    win.grab().save(str(out))
    print(f"wrote {out}")
    win.close()
    app.processEvents()


if __name__ == "__main__":
    main()
