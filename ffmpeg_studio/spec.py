"""JobSpec — everything the actions panel configures, and what a profile stores.

Kept as a plain dataclass with tolerant (de)serialisation so profile files
survive across app versions: unknown keys are ignored, missing keys fall back
to defaults.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field


# Output container groups (drives which sections of the UI apply).
VIDEO_CONTAINERS = ["mp4", "mkv", "webm", "mov", "avi"]
ANIM_CONTAINERS = ["gif", "webp"]
AUDIO_CONTAINERS = ["mp3", "wav", "flac", "opus", "m4a"]
IMAGE_CONTAINERS = ["png", "jpg"]

CONTAINER_LABELS = {
    "same": "Same as source",
    "mp4": "MP4 — video (most compatible)",
    "mkv": "MKV — video (flexible)",
    "webm": "WebM — video (web)",
    "mov": "MOV — video (Apple)",
    "avi": "AVI — video (legacy)",
    "gif": "GIF — animation",
    "webp": "WebP — animation",
    "mp3": "MP3 — audio",
    "m4a": "M4A/AAC — audio",
    "opus": "Opus — audio",
    "flac": "FLAC — audio (lossless)",
    "wav": "WAV — audio (uncompressed)",
    "png": "PNG — single frame",
    "jpg": "JPG — single frame",
}
CONTAINER_ORDER = ["same"] + VIDEO_CONTAINERS + ANIM_CONTAINERS + AUDIO_CONTAINERS + IMAGE_CONTAINERS

VIDEO_CODEC_LABELS = {
    "auto": "Auto (best for format)",
    "copy": "Copy (no re-encode)",
    "h264": "H.264 / x264 (CPU)",
    "h264_compat": "H.264 web-safe (copy if possible)",
    "h264rgb": "H.264 RGB 4:4:4 (mastering)",
    "hevc": "H.265 / x265 (CPU)",
    "vp9": "VP9 (CPU)",
    "av1": "AV1 / SVT (CPU)",
    "h264_nvenc": "H.264 (NVIDIA GPU)",
    "hevc_nvenc": "H.265 (NVIDIA GPU)",
    "av1_nvenc": "AV1 (NVIDIA GPU)",
}

PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
           "medium", "slow", "slower", "veryslow"]

SCALE_LABELS = {
    "keep": "Keep original",
    "2160": "4K (2160p)",
    "1440": "1440p",
    "1080": "1080p",
    "720": "720p",
    "480": "480p",
    "percent": "Percent of original…",
    "custom": "Custom size…",
}
SCALE_ORDER = ["keep", "2160", "1440", "1080", "720", "480", "percent", "custom"]

AUDIO_MODE_LABELS = {
    "keep": "Keep original (copy)",
    "encode": "Re-encode",
    "remove": "Remove audio",
}


@dataclass
class JobSpec:
    # --- format ---------------------------------------------------------
    container: str = "mp4"          # key of CONTAINER_LABELS
    # --- video ----------------------------------------------------------
    video_codec: str = "auto"       # key of VIDEO_CODEC_LABELS
    rate_mode: str = "crf"          # crf | bitrate | size
    crf: int = 23                   # 0..51 (lower = better)
    preset: str = "medium"          # PRESETS
    video_bitrate: int = 8000      # kbps, rate_mode == "bitrate"
    target_mb: float = 25.0         # MiB,  rate_mode == "size" (hit this)
    max_mb: float = 0.0             # MiB ceiling in quality mode (0 = off)
    # --- resize / fps / rotate -----------------------------------------
    scale_mode: str = "keep"        # SCALE_ORDER
    scale_percent: int = 50
    scale_w: int = 1920
    scale_h: int = -2               # -2 = keep aspect
    fps_mode: str = "keep"          # keep | custom
    fps: float = 30.0
    rotate: int = 0                 # 0 | 90 | 180 | 270 (clockwise)
    flip_h: bool = False
    flip_v: bool = False
    # --- audio ----------------------------------------------------------
    audio_mode: str = "keep"        # keep | encode | remove
    audio_bitrate: int = 192        # kbps for lossy targets
    normalize: bool = False         # loudnorm filter (forces re-encode)
    mono: bool = False              # equal L+R downmix (forces re-encode)
    # --- timelapse ------------------------------------------------------
    timelapse: bool = False         # squeeze the clip into timelapse_seconds
    timelapse_seconds: float = 30.0
    # --- trim -----------------------------------------------------------
    trim: bool = False
    trim_start: str = ""            # "HH:MM:SS(.ms)" / "M:SS" / "seconds"
    trim_end: str = ""              # empty = until the end
    # --- gif / webp -----------------------------------------------------
    anim_fps: int = 15
    anim_width: int = 480           # 0 = keep width
    # --- output / extras ------------------------------------------------
    suffix: str = ""                # appended to the output file name
    custom_args: str = ""           # raw extra ffmpeg args (power users)

    # -- helpers ---------------------------------------------------------
    def kind(self) -> str:
        """'video' | 'anim' | 'audio' | 'image' | 'same' for the target."""
        c = self.container
        if c in ANIM_CONTAINERS:
            return "anim"
        if c in AUDIO_CONTAINERS:
            return "audio"
        if c in IMAGE_CONTAINERS:
            return "image"
        if c == "same":
            return "same"
        return "video"

    def describe(self) -> str:
        """One readable line of what this profile actually does.

        Derived from the settings themselves, so a profile the user built
        gets a useful description too.
        """
        bits: list[str] = []
        kind = self.kind()
        bits.append("Same format" if self.container == "same"
                    else self.container.upper())

        if kind in ("video", "same"):
            if self.video_codec == "copy":
                bits.append("video copied, no re-encode")
            else:
                codec = {"auto": "auto codec", "h264": "H.264",
                         "h264_compat": "H.264, copied when possible",
                         "h264rgb": "H.264 RGB 4:4:4", "hevc": "H.265",
                         "vp9": "VP9", "av1": "AV1",
                         "h264_nvenc": "H.264 (GPU)",
                         "hevc_nvenc": "H.265 (GPU)",
                         "av1_nvenc": "AV1 (GPU)"}.get(
                             self.video_codec, self.video_codec)
                bits.append(codec)
                if self.rate_mode == "crf":
                    bits.append(f"quality CRF {self.crf}")
                elif self.rate_mode == "bitrate":
                    bits.append(f"{self.video_bitrate} kbps")
                else:
                    bits.append(f"aimed at {self.target_mb:g} MB")
                if self.max_mb > 0:
                    bits.append(f"max {self.max_mb:g} MB")
        elif kind == "anim":
            bits.append(f"{self.anim_fps} fps")
            if self.anim_width:
                bits.append(f"{self.anim_width}px wide")

        if self.scale_mode != "keep":
            bits.append({"percent": f"{self.scale_percent}% size",
                         "custom": f"{self.scale_w}x{self.scale_h}"}.get(
                             self.scale_mode, f"{self.scale_mode}p"))
        if self.fps_mode == "custom":
            bits.append(f"{self.fps:g} fps")
        if self.rotate:
            bits.append(f"rotated {self.rotate}°")

        if kind != "anim":
            audio = {"keep": "audio kept", "encode":
                     f"audio {self.audio_bitrate} kbps",
                     "remove": "audio removed"}.get(self.audio_mode, "")
            if audio:
                bits.append(audio)
        if self.timelapse:
            bits.append(f"timelapse to {self.timelapse_seconds:g}s")
        if self.mono:
            bits.append("mono downmix")
        if self.normalize:
            bits.append("loudness normalised")
        if self.trim:
            bits.append("trimmed")
        return " · ".join(b for b in bits if b)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "JobSpec":
        known = {f.name: f for f in dataclasses.fields(cls)}
        kwargs = {}
        for key, value in (data or {}).items():
            f = known.get(key)
            if f is None:
                continue
            try:
                if f.type in ("int", int):
                    value = int(value)
                elif f.type in ("float", float):
                    value = float(value)
                elif f.type in ("bool", bool):
                    value = bool(value)
                elif f.type in ("str", str):
                    value = str(value)
            except (TypeError, ValueError):
                continue
            kwargs[key] = value
        return cls(**kwargs)
