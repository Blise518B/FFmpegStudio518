"""ffprobe wrapper — media info the command builder and progress bars need."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .locate import popen_flags


@dataclass
class MediaInfo:
    path: Path
    size_bytes: int = 0
    duration: float | None = None      # seconds
    has_video: bool = False
    has_audio: bool = False
    has_subs: bool = False
    v_codec: str = ""
    pix_fmt: str = ""                  # yuv420p, gbrp, yuv420p10le, …
    a_codec: str = ""
    a_bitrate: int | None = None       # kbps, when the file reports it
    a_channels: int = 0                # 0 = unknown
    width: int = 0
    height: int = 0
    fps: float | None = None

    def channel_name(self) -> str:
        return {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(
            self.a_channels, f"{self.a_channels}ch" if self.a_channels else "")

    def summary(self) -> str:
        bits = []
        if self.has_video and self.width:
            bits.append(f"{self.width}x{self.height}")
        if self.v_codec:
            bits.append(self.v_codec)
        if self.a_codec:
            channels = self.channel_name()
            bits.append(f"{self.a_codec} {channels}".strip())
        return " · ".join(bits)


_cache: dict[tuple[str, int, int], MediaInfo] = {}


def probe(ffprobe: Path, path: Path) -> MediaInfo:
    """Probe ``path``; results are cached by (path, mtime, size)."""
    try:
        stat = path.stat()
        key = (str(path).lower(), stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = (str(path).lower(), 0, 0)
        stat = None
    hit = _cache.get(key)
    if hit is not None:
        return hit

    info = MediaInfo(path=path, size_bytes=stat.st_size if stat else 0)
    try:
        res = subprocess.run(
            [str(ffprobe), "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, creationflags=popen_flags())
        data = json.loads(res.stdout) if res.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        data = {}

    fmt = data.get("format") or {}
    try:
        info.duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        info.duration = None

    for stream in data.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video" and not info.has_video:
            # attached cover art shows up as a video stream; ignore it
            if stream.get("disposition", {}).get("attached_pic"):
                continue
            info.has_video = True
            info.v_codec = stream.get("codec_name") or ""
            info.pix_fmt = stream.get("pix_fmt") or ""
            info.width = int(stream.get("width") or 0)
            info.height = int(stream.get("height") or 0)
            rate = stream.get("avg_frame_rate") or ""
            if "/" in rate:
                num, _, den = rate.partition("/")
                try:
                    info.fps = float(num) / float(den) if float(den) else None
                except ValueError:
                    pass
        elif kind == "audio" and not info.has_audio:
            info.has_audio = True
            info.a_codec = stream.get("codec_name") or ""
            try:
                info.a_bitrate = int(stream.get("bit_rate")) // 1000
            except (TypeError, ValueError):
                info.a_bitrate = None
            try:
                info.a_channels = int(stream.get("channels") or 0)
            except (TypeError, ValueError):
                info.a_channels = 0
        elif kind == "subtitle":
            info.has_subs = True

    _cache[key] = info
    return info
