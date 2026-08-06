"""App settings — one JSON file in %APPDATA%/FFmpegStudio518."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import config_dir

_FILE = "settings.json"


@dataclass
class Settings:
    input_dir: str = ""
    output_dir: str = ""
    theme: str = "neon"             # "neon" | "midnight"
    last_profile: str = ""
    overwrite: bool = False         # overwrite existing outputs instead of "(1)"
    open_when_done: bool = True     # open the output folder after a run
    ffmpeg_path: str = ""           # user-set folder or ffmpeg.exe (empty = auto)
    window_geometry: str = ""       # hex-encoded QByteArray
    log_visible: bool = False

    @property
    def path(self) -> Path:
        return config_dir() / _FILE

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass  # never crash on a settings write

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            data = json.loads((config_dir() / _FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return s
        known = {f.name for f in fields(cls)}
        for key, value in (data or {}).items():
            if key in known and isinstance(value, type(getattr(s, key))):
                setattr(s, key, value)
        return s
