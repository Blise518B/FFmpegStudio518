"""Find (or fetch) ffmpeg/ffprobe so shared exes work on machines without it.

Search order:
  1. the user-set path from settings (a folder or ffmpeg.exe itself)
  2. next to the exe / repo root (portable: drop ffmpeg.exe beside the app)
  3. a ``bin`` folder next to the exe
  4. our own download dir  (%LOCALAPPDATA%/FFmpegStudio518/bin)
  5. anything on PATH
  6. a few common install locations

If nothing is found the UI offers a one-click download of the gyan.dev
release-essentials build into (4).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .. import data_dir, exe_dir

DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

_EXE = ".exe" if sys.platform == "win32" else ""

# Hide the console window subprocesses would otherwise flash on Windows.
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def popen_flags() -> int:
    return CREATE_NO_WINDOW


@dataclass
class FFmpegInstall:
    ffmpeg: Path
    ffprobe: Path
    version: str  # e.g. "8.1"


def download_dir() -> Path:
    return data_dir() / "bin"


def _version_of(ffmpeg: Path) -> str | None:
    try:
        out = subprocess.run(
            [str(ffmpeg), "-version"], capture_output=True, text=True,
            timeout=10, creationflags=popen_flags())
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout:
        return None
    first = out.stdout.splitlines()[0]  # "ffmpeg version 8.1-full_build..."
    parts = first.split()
    if len(parts) >= 3 and parts[1] == "version":
        return parts[2].split("-")[0]
    return "?"


def _probe_for(ffmpeg: Path) -> Path | None:
    sibling = ffmpeg.with_name("ffprobe" + _EXE)
    if sibling.is_file():
        return sibling
    which = shutil.which("ffprobe")
    return Path(which) if which else None


def _candidates(user_path: str) -> list[Path]:
    cands: list[Path] = []
    if user_path:
        p = Path(user_path)
        cands += [p if p.suffix else p / ("ffmpeg" + _EXE),
                  p / "bin" / ("ffmpeg" + _EXE)]
    for base in (exe_dir(), exe_dir() / "bin", download_dir()):
        cands.append(base / ("ffmpeg" + _EXE))
    which = shutil.which("ffmpeg")
    if which:
        cands.append(Path(which))
    for common in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"):
        cands.append(Path(common) / ("ffmpeg" + _EXE))
    return cands


def find_ffmpeg(user_path: str = "") -> FFmpegInstall | None:
    seen = set()
    for cand in _candidates(user_path):
        try:
            key = str(cand.resolve()).lower()
        except OSError:
            continue
        if key in seen or not cand.is_file():
            continue
        seen.add(key)
        version = _version_of(cand)
        if not version:
            continue
        probe = _probe_for(cand)
        if probe is None:
            continue
        return FFmpegInstall(ffmpeg=cand, ffprobe=probe, version=version)
    return None


def detect_gpu_encoders(ffmpeg: Path) -> set[str]:
    """NVENC encoders that actually work on this machine.

    ``-encoders`` lists nvenc in every build, even without an NVIDIA card,
    so run a tiny null encode for each and keep the ones that succeed.
    """
    working: set[str] = set()
    for enc in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
        try:
            res = subprocess.run(
                [str(ffmpeg), "-hide_banner", "-v", "error",
                 "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1",
                 "-c:v", enc, "-f", "null", "-"],
                capture_output=True, timeout=15, creationflags=popen_flags())
        except (OSError, subprocess.TimeoutExpired):
            continue
        if res.returncode == 0:
            working.add(enc)
    return working


def download_ffmpeg(progress, is_cancelled) -> FFmpegInstall:
    """Download + extract ffmpeg.exe/ffprobe.exe into our data dir.

    ``progress(done_bytes, total_bytes, message)`` is called along the way;
    ``is_cancelled()`` is polled so the UI can abort. Raises on failure.
    """
    if sys.platform != "win32":
        # DOWNLOAD_URL is a Windows build (bin/ffmpeg.exe) — extracting it
        # here could only ever fail after the full 90 MB download
        raise RuntimeError(
            "automatic download is Windows-only — install ffmpeg with your "
            "package manager (e.g. sudo apt install ffmpeg)")

    dest = download_dir()
    dest.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ffstudio_dl_") as tmp:
        zip_path = Path(tmp) / "ffmpeg.zip"
        progress(0, 0, "Connecting…")
        req = urllib.request.Request(
            DOWNLOAD_URL, headers={"User-Agent": "FFmpegStudio518"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(zip_path, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if is_cancelled():
                    raise RuntimeError("cancelled")
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                progress(done, total, "Downloading FFmpeg…")

        progress(0, 0, "Extracting…")
        wanted = {"ffmpeg" + _EXE: None, "ffprobe" + _EXE: None}
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                base = os.path.basename(name)
                if base in wanted and "/bin/" in name.replace("\\", "/"):
                    with zf.open(name) as src, open(dest / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    wanted[base] = dest / base
        missing = [k for k, v in wanted.items() if v is None]
        if missing:
            raise RuntimeError(f"archive had no {'/'.join(missing)}")

    install = find_ffmpeg()
    if install is None:
        raise RuntimeError("downloaded ffmpeg failed to run")
    return install
