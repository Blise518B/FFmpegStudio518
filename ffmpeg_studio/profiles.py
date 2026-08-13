"""Named profiles — a JobSpec saved as JSON in %APPDATA%/FFmpegStudio518/profiles.

Ship-with defaults are offered once each (tracked in a seeded-names file, so
deleting one doesn't resurrect it on the next start).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config_dir
from .spec import JobSpec

_MARKER = "defaults_v1_written"          # legacy; only read for migration
_SEEDED = "seeded_defaults.json"

# The ten defaults the v1 marker stood for, so a v1 user who deleted one
# doesn't get it back when a newer default is added.
# Defaults that shipped under an older name. On upgrade the old file is
# renamed so the profile keeps its place instead of appearing twice — but
# only if it still matches the shipped default. An edited one is left alone,
# because that is the user's own work under a name they chose to keep.
_RENAMED = {
    "RGB 4-4-4 master (original)": "RGB 4-4-4 master (normal quality)",
}

_V1_NAMES = frozenset({
    "MP4 1080p (share)", "Discord clip (under 10 MB)",
    "Compress small (H.265)", "WebM for web", "Remux to MKV (no re-encode)",
    "Remove audio", "Extract MP3 (320k)", "Extract audio untouched (M4A)",
    "High-quality GIF", "720p 30fps (small share)",
})


def profiles_dir() -> Path:
    d = config_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip().strip(".")
    return name[:80] or "profile"


def _path(name: str) -> Path:
    return profiles_dir() / f"{_safe_name(name)}.json"


def list_profiles() -> list[str]:
    return sorted((p.stem for p in profiles_dir().glob("*.json")),
                  key=str.lower)


def load_profile(name: str) -> JobSpec | None:
    try:
        data = json.loads(_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return JobSpec.from_dict(data)


def save_profile(name: str, spec: JobSpec) -> None:
    _path(name).write_text(
        json.dumps(spec.to_dict(), indent=2), encoding="utf-8")


def delete_profile(name: str) -> None:
    try:
        _path(name).unlink(missing_ok=True)
    except OSError:
        pass


def rename_profile(old: str, new: str) -> bool:
    src, dst = _path(old), _path(new)
    if not src.is_file() or dst.exists():
        return False
    try:
        src.rename(dst)
        return True
    except OSError:
        return False


def export_profile(name: str, target: Path) -> None:
    target.write_text(_path(name).read_text(encoding="utf-8"),
                      encoding="utf-8")


def import_profile(source: Path) -> str | None:
    """Copy an exported .json in; returns the profile name, or None if bad."""
    try:
        spec = JobSpec.from_dict(json.loads(source.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
    name = source.stem
    n, final = 1, name
    while _path(final).exists():
        final = f"{name} ({n})"
        n += 1
    save_profile(final, spec)
    return final


DEFAULT_PROFILES: dict[str, JobSpec] = {
    "MP4 1080p (share)": JobSpec(
        container="mp4", video_codec="h264", crf=20, preset="medium",
        scale_mode="1080", audio_mode="encode", audio_bitrate=192),
    # Keeps the file exactly as-is when it already plays on Discord; only
    # re-encodes what has to be (RGB/HEVC/10-bit, or over the size limit).
    "Discord-ready (keep quality)": JobSpec(
        container="mp4", video_codec="h264_compat", crf=16, preset="medium",
        max_mb=500.0, audio_mode="keep", audio_bitrate=192,
        suffix="_discord"),
    # Same decisions, but a slower x264 preset: identical size budget, more
    # detail per byte. Only matters when a re-encode is actually needed —
    # an already-shareable file is copied either way.
    "Discord-ready (max quality)": JobSpec(
        container="mp4", video_codec="h264_compat", crf=16, preset="slower",
        max_mb=500.0, audio_mode="keep", audio_bitrate=192,
        suffix="_discord_hq"),
    "Discord clip (under 10 MB)": JobSpec(
        container="mp4", video_codec="h264", rate_mode="size", target_mb=9.5,
        preset="medium", scale_mode="720", audio_mode="encode",
        audio_bitrate=96),
    "Compress small (H.265)": JobSpec(
        container="mp4", video_codec="hevc", crf=26, preset="medium",
        audio_mode="encode", audio_bitrate=160, suffix="_small"),
    "WebM for web": JobSpec(
        container="webm", video_codec="vp9", crf=32, preset="medium",
        audio_mode="encode", audio_bitrate=160),
    "Remux to MKV (no re-encode)": JobSpec(
        container="mkv", video_codec="copy", audio_mode="keep"),
    "Remove audio": JobSpec(
        container="same", video_codec="copy", audio_mode="remove",
        suffix="_mute"),
    # libx264rgb at x264's own defaults into MP4, audio copied. CRF 23 is
    # lossy, so this is a second generation.
    "RGB 4-4-4 master (normal quality)": JobSpec(
        container="mp4", video_codec="h264rgb", crf=23, preset="medium",
        audio_mode="keep"),
    # Same encoder, quality raised to match the point of 4:4:4 (roughly
    # double the size). CRF 0 here would be mathematically lossless.
    "RGB 4-4-4 master (high quality)": JobSpec(
        container="mkv", video_codec="h264rgb", crf=12, preset="medium",
        audio_mode="keep", suffix="_rgb"),
    "Stereo to mono (VRC POV fix)": JobSpec(
        container="same", video_codec="copy", audio_mode="encode",
        audio_bitrate=192, mono=True, suffix="_mono"),
    "Extract MP3 (320k)": JobSpec(
        container="mp3", audio_mode="encode", audio_bitrate=320),
    "Extract audio untouched (M4A)": JobSpec(
        container="m4a", audio_mode="keep"),
    "High-quality GIF": JobSpec(
        container="gif", anim_fps=15, anim_width=480),
    "720p 30fps (small share)": JobSpec(
        container="mp4", video_codec="h264", crf=23, preset="medium",
        scale_mode="720", fps_mode="custom", fps=30.0,
        audio_mode="encode", audio_bitrate=128, suffix="_720p"),
}


def _apply_renames() -> None:
    """Carry untouched defaults over to their new names."""
    for old, new in _RENAMED.items():
        old_path, new_path = _path(old), _path(new)
        if not old_path.is_file() or new_path.exists():
            continue
        if load_profile(old) == DEFAULT_PROFILES.get(new):
            try:
                old_path.rename(new_path)
            except OSError:
                pass


# Why you would reach for each shipped profile. Shown above the generated
# settings line when you hover it in the picker.
PROFILE_NOTES = {
    "MP4 1080p (share)":
        "Everyday conversion to an MP4 that plays anywhere, scaled down to "
        "1080p if the source is bigger.",
    "Discord-ready (keep quality)":
        "Leaves the file exactly as it is if it already plays on Discord, "
        "and only converts the ones that don't. Stays under 500 MB (Nitro).",
    "Discord-ready (max quality)":
        "Same as above, but a slower encoder setting fits more detail into "
        "the same 500 MB. Only matters when it has to re-encode.",
    "Discord clip (under 10 MB)":
        "Squeezes a clip under Discord's free 10 MB limit — 720p, two-pass. "
        "Use this one when you don't have Nitro.",
    "Compress small (H.265)":
        "Much smaller files at the same quality. Needs a reasonably modern "
        "player — older devices and some browsers can't decode H.265.",
    "WebM for web":
        "VP9 in WebM, for putting video on a website.",
    "Remux to MKV (no re-encode)":
        "Swaps the container only. Video and audio are copied untouched, so "
        "it's near-instant and loses nothing.",
    "Remove audio":
        "Strips the sound out and leaves the picture completely untouched.",
    "RGB 4-4-4 master (normal quality)":
        "Keeps colour at full resolution instead of quartering it — for "
        "footage you'll edit or re-encode again. Won't play on Discord, "
        "phones or most browsers.",
    "RGB 4-4-4 master (high quality)":
        "The same mastering format at a much finer quality setting, roughly "
        "double the size. Set CRF to 0 for mathematically lossless.",
    "Stereo to mono (VRC POV fix)":
        "Mixes left and right together equally, so audio that swings between "
        "your ears sits in the middle. The video is copied untouched, so "
        "it's quick.",
    "Extract MP3 (320k)":
        "Pulls the sound out as a high-bitrate MP3.",
    "Extract audio untouched (M4A)":
        "Lifts the audio out without re-encoding it where possible — no "
        "quality lost.",
    "High-quality GIF":
        "Builds a colour palette per clip, so the GIF looks far better than "
        "a naive conversion.",
    "720p 30fps (small share)":
        "A smaller 720p copy at 30 fps for quick sharing.",
}


def describe(name: str, spec: JobSpec | None = None) -> str:
    """Tooltip text for a profile: what it's for, then what it does."""
    if spec is None:
        spec = load_profile(name)
    if spec is None:
        return name
    note = PROFILE_NOTES.get(name)
    return f"{note}\n\n{spec.describe()}" if note else spec.describe()


def ensure_defaults() -> None:
    """Write any ship-with profile the user has never been offered.

    The seeded-names file remembers what was already handed out, so a default
    you delete stays deleted, while genuinely new ones still turn up after an
    update. (The old v1 marker meant "all ten originals were offered".)
    """
    _apply_renames()
    state = config_dir() / _SEEDED
    try:
        seeded = set(json.loads(state.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        # first run under this scheme: whatever is already on disk counts as
        # seen, plus the originals if the v1 marker says they were written
        seeded = set(list_profiles())
        if (config_dir() / _MARKER).exists():
            seeded |= _V1_NAMES

    for name, spec in DEFAULT_PROFILES.items():
        if name not in seeded and not _path(name).exists():
            save_profile(name, spec)
        seeded.add(name)
    try:
        state.write_text(json.dumps(sorted(seeded), indent=2), encoding="utf-8")
    except OSError:
        pass
