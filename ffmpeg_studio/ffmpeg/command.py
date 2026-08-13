"""Turn a JobSpec + probed source file into runnable ffmpeg argument lists.

Pure logic, no Qt and no subprocess — this is the part unit tests cover.
A build never hard-fails on odd combinations: it fixes what it can (e.g.
"copy" + filters silently switches to an encode) and reports every such
decision in ``JobPlan.notes`` so the UI can show what will really happen.
"""
from __future__ import annotations

import re
import shlex
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..spec import (ANIM_CONTAINERS, AUDIO_CONTAINERS, IMAGE_CONTAINERS,
                    VIDEO_CONTAINERS, JobSpec)
from .probe import MediaInfo


class BuildError(Exception):
    """Job can't be built at all (e.g. audio output from a silent video)."""


@dataclass
class JobPlan:
    passes: list[list[str]]            # argv tails (everything after "ffmpeg")
    output: Path
    duration: float | None             # effective seconds, for progress bars
    notes: list[str] = field(default_factory=list)
    passlog: str | None = None         # prefix of 2-pass stat files to clean up


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

# "1h30m", "2m30s", "90s" — longest spellings first so "min" doesn't get
# eaten by the "m" branch.
_UNIT_TIME = re.compile(
    r"""^\s*
        (?:(?P<h>\d+(?:\.\d+)?)\s*(?:hours|hour|hrs|hr|h)\s*)?
        (?:(?P<m>\d+(?:\.\d+)?)\s*(?:minutes|minute|mins|min|m)\s*)?
        (?:(?P<s>\d+(?:\.\d+)?)\s*(?:seconds|second|secs|sec|s)\s*)?
        $""",
    re.VERBOSE | re.IGNORECASE)


def parse_time(text: str) -> float:
    """Read a length the way a video player writes one.

    Accepted, all meaning the same 90 seconds::

        1:30        colons, right to left: [hh:]mm:ss
        90          a bare number is seconds
        1m30s       explicit units (h/m/s, also min, secs, hours…)

    Raises ValueError on anything else.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty time")

    if ":" in text:
        parts = text.split(":")
        if len(parts) > 3 or any(p.strip() == "" for p in parts):
            raise ValueError(f"bad time: {text!r}")
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
    else:
        match = _UNIT_TIME.match(text)
        if match and any(match.group(g) for g in ("h", "m", "s")):
            seconds = (float(match.group("h") or 0) * 3600
                       + float(match.group("m") or 0) * 60
                       + float(match.group("s") or 0))
        else:
            seconds = float(text)          # bare number: seconds

    if seconds < 0:
        raise ValueError("negative time")
    return seconds


def format_seconds(secs: float | None) -> str:
    if secs is None:
        return "–"
    secs = int(round(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _even(n: float) -> int:
    return max(2, int(round(n / 2)) * 2)


def _fnum(x: float) -> str:
    """30.0 -> '30', 29.97 -> '29.97'."""
    return f"{x:g}"


def resolve_output(src: Path, out_dir: Path, ext: str, suffix: str,
                   overwrite: bool) -> Path:
    """Output path: same stem + optional suffix; never the source file itself;
    appends ' (1)', ' (2)'… instead of clobbering unless overwrite is on."""
    stem = src.stem + (suffix or "")
    cand = out_dir / f"{stem}.{ext}"
    if _same_file(cand, src):
        stem += "_out"
        cand = out_dir / f"{stem}.{ext}"
    if overwrite:
        return cand
    n = 1
    while cand.exists():
        cand = out_dir / f"{stem} ({n}).{ext}"
        n += 1
    return cand


def _same_file(a: Path, b: Path) -> bool:
    try:
        return str(a.resolve()).lower() == str(b.resolve()).lower()
    except OSError:
        return str(a).lower() == str(b).lower()


def effective_container(spec: JobSpec, info: MediaInfo) -> tuple[str, str]:
    """(extension, kind) actually produced, resolving 'Same as source'."""
    if spec.container != "same":
        return spec.container, spec.kind()
    ext = info.path.suffix.lower().lstrip(".") or "mp4"
    if ext in AUDIO_CONTAINERS:
        kind = "audio"
    elif ext in ANIM_CONTAINERS:
        kind = "anim"
    elif ext in IMAGE_CONTAINERS:
        kind = "image"
    elif ext in VIDEO_CONTAINERS:
        kind = "video"
    else:
        kind = "video" if info.has_video else "audio"
    return ext, kind


# ---------------------------------------------------------------------------
# codec tables
# ---------------------------------------------------------------------------

_ENCODER = {"h264": "libx264", "h264rgb": "libx264rgb", "hevc": "libx265",
            "vp9": "libvpx-vp9", "av1": "libsvtav1",
            "h264_nvenc": "h264_nvenc", "hevc_nvenc": "hevc_nvenc",
            "av1_nvenc": "av1_nvenc"}

# Containers that can actually hold RGB H.264 (High 4:4:4 Predictive).
_RGB_CONTAINERS = {"mp4", "mkv", "mov"}

# What Discord (and browsers generally) will decode and play inline. The
# pixel format matters as much as the codec: an RGB 4:4:4 or 10-bit stream is
# still "h264" to ffprobe but nothing on the web will play it.
_WEB_SAFE_PIX = {"yuv420p", "yuvj420p"}
_WEB_SAFE_AUDIO = {"aac", "mp3"}
_MIB = 1024 * 1024


def is_web_safe(info: MediaInfo) -> bool:
    """True when the video stream can be shared as-is, no re-encode needed."""
    return info.v_codec == "h264" and info.pix_fmt in _WEB_SAFE_PIX


def _too_big(info: MediaInfo, max_mb: float) -> bool:
    return max_mb > 0 and info.size_bytes > max_mb * _MIB

_AUTO_VIDEO = {"mp4": "h264", "mov": "h264", "mkv": "h264", "avi": "h264",
               "webm": "vp9"}

# codecs a container can hold via "-c:v copy" without drama
_COPY_OK = {"mp4": {"h264", "hevc", "av1", "mpeg4"},
            "mov": {"h264", "hevc", "av1", "mpeg4", "prores"},
            "webm": {"vp8", "vp9", "av1"},
            "avi": {"mpeg4", "mjpeg", "h264"},
            "mkv": None}          # None = anything goes

_SVT_PRESET = {"ultrafast": 12, "superfast": 11, "veryfast": 10, "faster": 9,
               "fast": 9, "medium": 8, "slow": 6, "slower": 4, "veryslow": 2}
_NVENC_PRESET = {"ultrafast": "p1", "superfast": "p2", "veryfast": "p2",
                 "faster": "p3", "fast": "p3", "medium": "p4", "slow": "p5",
                 "slower": "p6", "veryslow": "p7"}
_VP9_CPU_USED = {"ultrafast": 8, "superfast": 6, "veryfast": 5, "faster": 4,
                 "fast": 3, "medium": 2, "slow": 1, "slower": 1, "veryslow": 0}

# audio codecs that may be stream-copied into each video container
_ACOPY_OK = {"mp4": {"aac", "mp3", "ac3", "eac3"},
             "mov": {"aac", "mp3", "ac3", "eac3", "alac", "pcm_s16le"},
             "webm": {"opus", "vorbis"},
             "avi": {"mp3", "ac3", "pcm_s16le"},
             "mkv": None}
_AENC = {"mp4": "aac", "mov": "aac", "mkv": "aac", "avi": "libmp3lame",
         "webm": "libopus"}

# audio-only targets: (encoder, takes_bitrate, copy-compatible source codecs)
_AUDIO_TARGETS = {
    "mp3": ("libmp3lame", True, {"mp3"}),
    "m4a": ("aac", True, {"aac", "alac"}),
    "opus": ("libopus", True, {"opus"}),
    "flac": ("flac", False, {"flac"}),
    "wav": ("pcm_s16le", False, {"pcm_s16le", "pcm_s24le"}),
}

_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"

# Equal-weight stereo fold-down: both channels contribute the same amount, so
# hard-panned content lands dead centre instead of in one ear. Halving keeps
# the sum inside full scale (L+R at full amplitude would clip).
_MONO_PAN = "pan=mono|c0=0.5*c0+0.5*c1"


def needs_mono(spec: JobSpec, info: MediaInfo) -> bool:
    """True when a downmix is asked for AND the source isn't already mono."""
    return spec.mono and info.a_channels != 1


def _audio_filters(spec: JobSpec, info: MediaInfo,
                   speed: float | None = None) -> list[str]:
    """-af chain (and -ac where a filter can't express it) for mono/loudnorm,
    plus the tempo change when the video is being retimed."""
    chain: list[str] = []
    args: list[str] = []
    if speed is not None:
        chain += _atempo_chain(speed)
    if needs_mono(spec, info):
        if info.a_channels == 2:
            chain.append(_MONO_PAN)
        else:
            # surround (or unknown): ffmpeg's own downmix matrix is built for
            # this and handles centre/LFE sanely — a 2-channel pan can't.
            args += ["-ac", "1"]
    if spec.normalize:
        chain.append(_LOUDNORM)
    if chain:
        args += ["-af", ",".join(chain)]
    return args


# ---------------------------------------------------------------------------
# the builder
# ---------------------------------------------------------------------------

def build_plan(spec: JobSpec, info: MediaInfo, out_dir: Path,
               overwrite: bool = False,
               gpu_encoders: set[str] | None = None) -> JobPlan:
    """Build the ffmpeg invocation(s) for one source file."""
    notes: list[str] = []
    ext, kind = effective_container(spec, info)

    if kind in ("video", "anim", "image") and not info.has_video:
        raise BuildError("source has no video stream")
    if kind == "audio" and not info.has_audio:
        raise BuildError("source has no audio stream")

    trim_start, trim_dur, duration = _trim(spec, info, notes)
    out = resolve_output(info.path, out_dir, ext, spec.suffix, overwrite)

    # `duration` stays the length being read, which the filters need;
    # `out_duration` is what the result will be, which progress needs.
    speed = None
    out_duration = duration
    if spec.timelapse:
        if kind in ("audio", "image"):
            notes.append(f"Timelapse doesn't apply to .{ext} — ignored")
        elif not duration:
            notes.append("Unknown length — can't work out the timelapse speed")
        else:
            speed = timelapse_speed(spec, duration)
            if speed and speed < 1:
                notes.append(f"Target is longer than the clip — playing it "
                             f"{1 / speed:.3g}x slower instead")
            elif speed:
                notes.append(f"Timelapse {speed:.4g}x — "
                             f"{format_seconds(duration)} → "
                             f"{format_seconds(spec.timelapse_seconds)}")
            if speed:
                out_duration = spec.timelapse_seconds

    head: list[str] = ["-hide_banner", "-y"]
    if trim_start is not None:
        head += ["-ss", _fnum(trim_start)]
    head += ["-i", str(info.path)]
    if trim_dur is not None:
        head += ["-t", _fnum(trim_dur)]

    if kind == "audio":
        body = _audio_only(spec, info, ext, notes)
    elif kind == "image":
        body = _image(spec, info, ext, notes)
    elif kind == "anim":
        body = _anim(spec, info, ext, notes, speed)
    else:
        return _video(spec, info, ext, head, out, out_duration, notes,
                      gpu_encoders, speed)

    body += _custom(spec, notes)
    return JobPlan(passes=[head + body + [str(out)]], output=out,
                   duration=out_duration, notes=notes)


def _trim(spec: JobSpec, info: MediaInfo, notes: list[str]):
    """-> (start | None, duration_arg | None, effective_duration | None)"""
    total = info.duration
    if not spec.trim:
        return None, None, total
    start = end = None
    try:
        start = parse_time(spec.trim_start) if spec.trim_start.strip() else 0.0
    except ValueError:
        notes.append(f"Ignored bad trim start {spec.trim_start!r}")
        start = 0.0
    if spec.trim_end.strip():
        try:
            end = parse_time(spec.trim_end)
        except ValueError:
            notes.append(f"Ignored bad trim end {spec.trim_end!r}")
    if end is not None and end <= start:
        notes.append("Trim end is before start — ignored")
        end = None
    dur = None
    if end is not None:
        dur = end - start
    elif total is not None:
        dur = max(0.1, total - start)
    return (start if start > 0 else None,
            (end - start) if end is not None else None,
            dur if dur is not None else total)


# beyond this a sped-up soundtrack is unlistenable, so it gets dropped
_MAX_AUDIO_SPEED = 4.0


def timelapse_speed(spec: JobSpec, duration: float | None) -> float | None:
    """How much faster the clip has to run to land on the target length.

    ``duration`` is the length actually being encoded, so a trim is already
    taken into account. Returns None when it can't be worked out.
    """
    if not spec.timelapse or not duration or spec.timelapse_seconds <= 0:
        return None
    speed = duration / spec.timelapse_seconds
    return speed if speed > 0 else None


def _timelapse_fps(spec: JobSpec, info: MediaInfo) -> float:
    """Frame rate for the sped-up result."""
    if spec.fps_mode == "custom" and spec.fps > 0:
        return spec.fps
    if info.fps and info.fps > 0:
        return min(info.fps, 60.0)
    return 30.0


def _atempo_chain(speed: float) -> list[str]:
    """atempo stages for ``speed``; it only handles 0.5–2x per stage."""
    stages: list[str] = []
    remaining = speed
    while remaining > 2.0:
        stages.append(f"atempo={_fnum(2.0)}")
        remaining /= 2.0
    while remaining < 0.5:
        stages.append(f"atempo={_fnum(0.5)}")
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-6:
        stages.append(f"atempo={_fnum(round(remaining, 6))}")
    return stages


def _vf_chain(spec: JobSpec, info: MediaInfo, notes: list[str],
              include_fps: bool = True) -> list[str]:
    """Shared geometry filters: rotate/flip -> scale -> fps."""
    chain: list[str] = []
    if spec.rotate == 90:
        chain.append("transpose=1")
    elif spec.rotate == 180:
        chain += ["hflip", "vflip"]
    elif spec.rotate == 270:
        chain.append("transpose=2")
    if spec.flip_h:
        chain.append("hflip")
    if spec.flip_v:
        chain.append("vflip")

    rotated = spec.rotate in (90, 270)
    w, h = (info.height, info.width) if rotated else (info.width, info.height)

    mode = spec.scale_mode
    if mode in ("2160", "1440", "1080", "720", "480"):
        target = int(mode)
        if w > 0 and h > 0:
            short = min(w, h)
            if short > target:                    # never upscale
                chain.append(f"scale=-2:{target}" if w >= h
                             else f"scale={target}:-2")
        else:  # dimensions unknown — decide inside ffmpeg
            chain.append(
                f"scale=w=if(gt(iw\\,ih)\\,-2\\,{target}):"
                f"h=if(gt(iw\\,ih)\\,{target}\\,-2)")
    elif mode == "percent":
        pct = max(1, min(400, spec.scale_percent))
        if pct != 100:
            if w > 0 and h > 0:
                chain.append(f"scale={_even(w * pct / 100)}:{_even(h * pct / 100)}")
            else:
                f = pct / 100.0
                chain.append(f"scale=trunc(iw*{f}/2)*2:trunc(ih*{f}/2)*2")
    elif mode == "custom":
        sw = spec.scale_w if spec.scale_w in (-1, -2) else _even(spec.scale_w)
        sh = spec.scale_h if spec.scale_h in (-1, -2) else _even(spec.scale_h)
        if sw in (-1, -2) and sh in (-1, -2):
            notes.append("Custom size has no fixed side — scale skipped")
        else:
            chain.append(f"scale={sw}:{sh}")

    if include_fps and spec.fps_mode == "custom" and spec.fps > 0:
        chain.append(f"fps={_fnum(spec.fps)}")
    return chain


def _custom(spec: JobSpec, notes: list[str]) -> list[str]:
    text = spec.custom_args.strip()
    if not text:
        return []
    try:
        args = shlex.split(text.replace("\\", "\\\\"))
    except ValueError:
        notes.append("Custom args have unbalanced quotes — ignored")
        return []
    return args


# --- audio-only targets ----------------------------------------------------

def _audio_only(spec: JobSpec, info: MediaInfo, ext: str,
                notes: list[str]) -> list[str]:
    enc, takes_bitrate, copy_ok = _AUDIO_TARGETS[ext]
    args = ["-vn"]
    if spec.audio_mode == "remove":
        notes.append("'Remove audio' makes no sense for an audio file — kept")
    filters = _audio_filters(spec, info)
    want_copy = spec.audio_mode == "keep" and not filters
    if want_copy and info.a_codec in copy_ok:
        args += ["-c:a", "copy"]
    else:
        if spec.audio_mode == "keep" and filters:
            notes.append(f"{_filter_why(spec, info)} needs a re-encode")
        elif want_copy and info.a_codec:
            notes.append(
                f"{info.a_codec} can't be copied into .{ext} — re-encoding")
        args += ["-c:a", enc]
        if takes_bitrate:
            args += ["-b:a", f"{spec.audio_bitrate}k"]
        args += filters
    if ext == "m4a":
        args += ["-movflags", "+faststart"]
    return args


# --- single frame ----------------------------------------------------------

def _image(spec: JobSpec, info: MediaInfo, ext: str,
           notes: list[str]) -> list[str]:
    args: list[str] = []
    vf = _vf_chain(spec, info, notes, include_fps=False)
    if vf:
        args += ["-vf", ",".join(vf)]
    args += ["-frames:v", "1"]
    if ext == "jpg":
        args += ["-q:v", "2"]
    args += ["-an"]
    return args


# --- gif / webp ------------------------------------------------------------

def _anim(spec: JobSpec, info: MediaInfo, ext: str,
          notes: list[str], speed: float | None = None) -> list[str]:
    pre = []
    if speed is not None:
        pre.append(f"setpts=PTS/{_fnum(speed)}")   # retime before resampling
    if spec.anim_fps > 0:
        pre.append(f"fps={spec.anim_fps}")
    if spec.anim_width > 0:
        pre.append(f"scale={_even(spec.anim_width)}:-2:flags=lanczos")
    pre += _vf_chain_rotate_only(spec)

    if ext == "gif":
        chain = ",".join(pre)
        graph = (f"[0:v]{chain + ',' if chain else ''}split[s0][s1];"
                 "[s0]palettegen=stats_mode=diff[p];"
                 "[s1][p]paletteuse=dither=bayer:bayer_scale=5:"
                 "diff_mode=rectangle")
        return ["-filter_complex", graph, "-loop", "0", "-an"]
    # webp
    args: list[str] = []
    if pre:
        args += ["-vf", ",".join(pre)]
    args += ["-c:v", "libwebp", "-quality", "80", "-loop", "0", "-an"]
    return args


def _vf_chain_rotate_only(spec: JobSpec) -> list[str]:
    chain = []
    if spec.rotate == 90:
        chain.append("transpose=1")
    elif spec.rotate == 180:
        chain += ["hflip", "vflip"]
    elif spec.rotate == 270:
        chain.append("transpose=2")
    if spec.flip_h:
        chain.append("hflip")
    if spec.flip_v:
        chain.append("vflip")
    return chain


# --- full video ------------------------------------------------------------

def _video(spec: JobSpec, info: MediaInfo, ext: str, head: list[str],
           out: Path, duration: float | None, notes: list[str],
           gpu_encoders: set[str] | None,
           speed: float | None = None) -> JobPlan:
    # in timelapse mode the frame rate is set after the retime, not before
    vf = _vf_chain(spec, info, notes, include_fps=speed is None)
    if speed is not None:
        vf.append(f"setpts=PTS/{_fnum(speed)}")
        vf.append(f"fps={_fnum(_timelapse_fps(spec, info))}")
    codec = spec.video_codec
    rate_mode = spec.rate_mode

    # resolve nvenc on machines without it
    if codec.endswith("_nvenc") and gpu_encoders is not None \
            and codec not in gpu_encoders:
        cpu = codec.replace("_nvenc", "")
        notes.append(f"NVENC not available here — using CPU {cpu}")
        codec = cpu

    if codec == "auto":
        codec = _AUTO_VIDEO.get(ext, "h264")

    if codec == "h264rgb":
        if ext not in _RGB_CONTAINERS:
            notes.append(f".{ext} can't carry RGB H.264 — using MKV-safe "
                         "H.264 instead")
            codec = _AUTO_VIDEO.get(ext, "h264")
        else:
            notes.append("RGB 4:4:4 won't hardware-decode — great as a master,"
                         " re-encode before sharing")

    # "copy if it already plays everywhere, otherwise make it play" — the
    # decision is per file, so a folder of mixed sources sorts itself out.
    want_compat = codec == "h264_compat"
    if want_compat:
        if not is_web_safe(info):
            reason = (info.v_codec.upper() if info.v_codec != "h264"
                      else info.pix_fmt or "this pixel format")
            notes.append(f"{reason} won't play on Discord — converting to "
                         "H.264 yuv420p")
            codec = _AUTO_VIDEO.get(ext, "h264")
        elif _too_big(info, spec.max_mb):
            notes.append(
                f"Over the {spec.max_mb:g} MB limit "
                f"({info.size_bytes / _MIB:.0f} MB) — re-encoding to fit")
            codec = _AUTO_VIDEO.get(ext, "h264")
        else:
            notes.append("Video already Discord-ready — copied untouched")
            codec = "copy"

    if codec == "copy":
        copy_ok = _COPY_OK.get(ext, set())
        incompatible = copy_ok is not None and info.v_codec not in copy_ok
        if vf or rate_mode != "crf" or incompatible:
            fallback = _AUTO_VIDEO.get(ext, "h264")
            why = ("filters/bitrate need a re-encode" if (vf or rate_mode != "crf")
                   else f"{info.v_codec or 'source codec'} doesn't fit .{ext}")
            notes.append(f"Copy not possible ({why}) — encoding with "
                         f"{fallback} instead")
            codec = fallback
        else:
            body = ["-c:v", "copy"] + _video_audio(spec, info, ext, notes,
                                                   want_compat, speed)
            body += _subs(info, ext, notes)
            body += _mux_extras(ext)
            body += _custom(spec, notes)
            return JobPlan(passes=[head + body + [str(out)]], output=out,
                           duration=duration, notes=notes)

    # size mode needs a duration to do math with
    if rate_mode == "size" and not duration:
        notes.append("Unknown duration — can't hit a target size, "
                     "using quality mode instead")
        rate_mode = "crf"

    audio_args = _video_audio(spec, info, ext, notes, want_compat, speed)
    common = []
    if vf:
        common += ["-vf", ",".join(vf)]
    common += ["-c:v", _ENCODER[codec]]
    common += _codec_tuning(codec, spec)

    if rate_mode == "crf":
        common += _crf_args(codec, spec.crf)
        common += _size_ceiling(spec, info, duration, codec, notes)
        body = common + audio_args + _subs(info, ext, notes) + _mux_extras(ext)
        body += _custom(spec, notes)
        return JobPlan(passes=[head + body + [str(out)]], output=out,
                       duration=duration, notes=notes)

    if rate_mode == "bitrate":
        kbps = max(50, spec.video_bitrate)
    else:  # size
        kbps = _size_to_kbps(spec, info, duration, notes)

    rate = ["-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k",
            "-bufsize", f"{kbps * 2}k"]

    two_pass = rate_mode == "size" and codec in ("h264", "h264rgb", "hevc",
                                                 "vp9")
    if not two_pass:
        if rate_mode == "size":
            notes.append("Size targeting with this codec is single-pass "
                         "(approximate)")
        body = common + rate + audio_args + _subs(info, ext, notes)
        body += _mux_extras(ext) + _custom(spec, notes)
        return JobPlan(passes=[head + body + [str(out)]], output=out,
                       duration=duration, notes=notes)

    passlog = str(Path(tempfile.gettempdir()) /
                  f"ffstudio_2pass_{uuid.uuid4().hex[:10]}")
    p1 = head + common + rate + ["-pass", "1", "-passlogfile", passlog,
                                 "-an", "-sn", "-f", "null", "-"]
    p2 = head + common + rate + ["-pass", "2", "-passlogfile", passlog]
    p2 += audio_args + _subs(info, ext, notes) + _mux_extras(ext)
    p2 += _custom(spec, notes) + [str(out)]
    return JobPlan(passes=[p1, p2], output=out, duration=duration,
                   notes=notes, passlog=passlog)


def _codec_tuning(codec: str, spec: JobSpec) -> list[str]:
    if codec == "h264rgb":
        # no -pix_fmt: forcing yuv420p here would throw the chroma away again,
        # which is the whole reason for picking this encoder
        return ["-preset", spec.preset]
    if codec in ("h264", "hevc"):
        return ["-preset", spec.preset, "-pix_fmt", "yuv420p"]
    if codec == "vp9":
        return ["-deadline", "good", "-cpu-used",
                str(_VP9_CPU_USED[spec.preset]), "-row-mt", "1"]
    if codec == "av1":
        return ["-preset", str(_SVT_PRESET[spec.preset])]
    if codec.endswith("_nvenc"):
        args = ["-preset", _NVENC_PRESET[spec.preset]]
        if codec in ("h264_nvenc", "hevc_nvenc"):
            args += ["-pix_fmt", "yuv420p"]
        return args
    return []


def _crf_args(codec: str, crf: int) -> list[str]:
    crf = max(0, min(51, crf))
    if codec == "vp9":
        return ["-crf", str(crf), "-b:v", "0"]
    if codec.endswith("_nvenc"):
        return ["-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    return ["-crf", str(crf)]


# encoders whose -maxrate/-bufsize actually constrain the output
_CAPPABLE = {"h264", "h264rgb", "hevc", "vp9", "h264_nvenc", "hevc_nvenc",
             "av1_nvenc"}

# Above this the ceiling can't bind on any real content, and a short clip
# with a generous budget produces numbers big enough to overflow x264's
# int32 bufsize — so drop the cap instead of emitting it.
_CAP_IRRELEVANT_KBPS = 200_000


def _size_ceiling(spec: JobSpec, info: MediaInfo, duration: float | None,
                  codec: str, notes: list[str]) -> list[str]:
    """Capped CRF: quality decides the size, but never past ``max_mb``.

    Unlike target-size mode this can't inflate a small file — CRF governs
    until the cap bites, so a short clip stays small and a long one lands
    just under the limit.
    """
    if spec.max_mb <= 0:
        return []
    if not duration:
        notes.append("Unknown duration — can't enforce the size limit")
        return []
    if codec not in _CAPPABLE:
        notes.append(f"{codec} can't be size-capped — limit not applied")
        return []
    kbps = _size_to_kbps(spec, info, duration, notes, mb=spec.max_mb)
    if kbps > _CAP_IRRELEVANT_KBPS:
        return []      # clip is far too short to approach the limit
    return ["-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k"]


def _size_to_kbps(spec: JobSpec, info: MediaInfo, duration: float,
                  notes: list[str], mb: float | None = None) -> int:
    total_kbits = (spec.target_mb if mb is None else mb) * 8192
    if spec.audio_mode == "remove" or not info.has_audio:
        audio_kbps = 0
    elif spec.audio_mode == "encode":
        audio_kbps = spec.audio_bitrate
    else:
        audio_kbps = info.a_bitrate or 128
    kbps = int(total_kbits * 0.97 / duration) - audio_kbps
    if kbps < 50:
        notes.append("Target size is very small for this length — "
                     "quality will suffer")
        kbps = 50
    return kbps


def _video_audio(spec: JobSpec, info: MediaInfo, ext: str,
                 notes: list[str], web_safe: bool = False,
                 speed: float | None = None) -> list[str]:
    if not info.has_audio:
        return ["-an"] if spec.audio_mode == "remove" else []
    if spec.audio_mode == "remove":
        return ["-an"]

    if speed is not None and not (
            1 / _MAX_AUDIO_SPEED <= speed <= _MAX_AUDIO_SPEED):
        notes.append(f"Audio dropped — nothing survives {speed:.3g}x")
        return ["-an"]

    copy_ok = _ACOPY_OK.get(ext)
    if web_safe:
        # AC-3 and friends are legal in MP4 but silent in a browser
        copy_ok = _WEB_SAFE_AUDIO if copy_ok is None else copy_ok & _WEB_SAFE_AUDIO
    enc = _AENC.get(ext, "aac")
    filters = _audio_filters(spec, info, speed)
    want_copy = spec.audio_mode == "keep" and not filters
    if want_copy:
        if copy_ok is None or info.a_codec in copy_ok:
            return ["-c:a", "copy"]
        notes.append(f"{info.a_codec or 'source audio'} can't be copied "
                     f"into .{ext} — re-encoding")
    elif spec.audio_mode == "keep" and speed is None:
        notes.append(f"{_filter_why(spec, info)} needs a re-encode")
    return ["-c:a", enc, "-b:a", f"{spec.audio_bitrate}k"] + filters


def _filter_why(spec: JobSpec, info: MediaInfo) -> str:
    both = needs_mono(spec, info) and spec.normalize
    if both:
        return "Mono downmix + normalization"
    return "Mono downmix" if needs_mono(spec, info) else "Normalization"


def _subs(info: MediaInfo, ext: str, notes: list[str]) -> list[str]:
    if not info.has_subs:
        return []
    if ext == "mkv":
        return ["-c:s", "copy"]
    notes.append(f"Subtitle track dropped (.{ext} target)")
    return ["-sn"]


def _mux_extras(ext: str) -> list[str]:
    if ext in ("mp4", "mov"):
        return ["-movflags", "+faststart"]
    return []


def preview_text(plan: JobPlan) -> str:
    """Readable command preview for the UI."""
    def q(a: str) -> str:
        return f'"{a}"' if (" " in a or not a) else a
    lines = ["ffmpeg " + " ".join(q(a) for a in p) for p in plan.passes]
    return "\n".join(lines)
