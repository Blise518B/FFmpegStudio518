"""FFmpeg Studio 518 — a friendly batch front-end for FFmpeg.

Point it at an input folder, pick the actions (convert, compress, resize,
trim, extract audio, make GIFs...), hit start. Named profiles store a whole
actions setup so common jobs are one click.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

__version__ = "1.3.1"

APP_NAME = "FFmpeg Studio 518"
APP_DIRNAME = "FFmpegStudio518"


def is_frozen() -> bool:
    """True when running from the PyInstaller one-file exe."""
    return getattr(sys, "frozen", False)


def resource_path(rel: str) -> Path:
    """Path to a bundled resource (works from source and from the exe)."""
    if is_frozen():
        return Path(sys._MEIPASS) / "ffmpeg_studio" / rel  # type: ignore[attr-defined]
    return Path(__file__).parent / rel


def exe_dir() -> Path:
    """Folder the exe (or repo) lives in — checked for a portable ffmpeg."""
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def config_dir() -> Path:
    """%APPDATA%/FFmpegStudio518 — settings and profiles."""
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_dir() -> Path:
    """%LOCALAPPDATA%/FFmpegStudio518 — bigger local-only files (ffmpeg download)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / APP_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d
