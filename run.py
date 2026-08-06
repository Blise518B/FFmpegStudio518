"""PyInstaller entry point (and a plain `python run.py` launcher)."""
from ffmpeg_studio.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
