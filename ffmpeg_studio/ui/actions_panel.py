"""The actions panel: colored sections that together edit a JobSpec.

Sections gray out depending on the chosen output format (audio targets don't
need video options, GIF has its own knobs, ...) so it is always obvious which
settings will actually do something.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox,
                               QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit,
                               QRadioButton, QSlider, QSpinBox, QVBoxLayout,
                               QWidget)

from ..ffmpeg.command import format_seconds, parse_time
from ..spec import (AUDIO_MODE_LABELS, CONTAINER_LABELS, CONTAINER_ORDER,
                    PRESETS, SCALE_LABELS, SCALE_ORDER, VIDEO_CODEC_LABELS,
                    JobSpec)
from .widgets import Section, hrow

_CPU_CODECS = ["auto", "copy", "h264", "h264_compat", "h264rgb", "hevc",
               "vp9", "av1"]
_GPU_CODECS = ["h264_nvenc", "hevc_nvenc", "av1_nvenc"]


class ActionsPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._gpu: set[str] = set()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # ---- Format (green) -------------------------------------------
        fmt = Section("Format", "green")
        self.container = QComboBox()
        for key in CONTAINER_ORDER:
            self.container.addItem(CONTAINER_LABELS[key], key)
        self.container.setCurrentIndex(CONTAINER_ORDER.index("mp4"))
        fmt.add_row("Output", self.container)
        lay.addWidget(fmt)
        self.sec_format = fmt

        # ---- Video (blue) ---------------------------------------------
        vid = Section("Video", "blue")
        self.vcodec = QComboBox()
        self._rebuild_codecs()
        vid.add_row("Codec", self.vcodec)

        self.rate_crf = QRadioButton("Quality")
        self.rate_bitrate = QRadioButton("Bitrate")
        self.rate_size = QRadioButton("Target size")
        self.rate_crf.setChecked(True)
        self.rate_group = QButtonGroup(self)
        for b in (self.rate_crf, self.rate_bitrate, self.rate_size):
            self.rate_group.addButton(b)
        vid.add_row("Mode", hrow(self.rate_crf, self.rate_bitrate,
                                 self.rate_size, stretch_last=True))

        self.crf = QSlider(Qt.Orientation.Horizontal)
        self.crf.setRange(0, 51)
        self.crf.setValue(23)
        self.crf_label = QLabel("23")
        self.crf_label.setFixedWidth(24)
        vid.add_row("CRF", hrow(self.crf, self.crf_label),
                    hint="lower = better quality & bigger file · 18–28 is the sweet spot")

        self.vbitrate = QSpinBox()
        self.vbitrate.setRange(100, 100_000)
        self.vbitrate.setValue(8000)
        self.vbitrate.setSuffix(" kbps")
        vid.add_row("Bitrate", self.vbitrate)

        self.target_mb = QDoubleSpinBox()
        self.target_mb.setRange(0.5, 100_000)
        self.target_mb.setValue(25.0)
        self.target_mb.setDecimals(1)
        self.target_mb.setSuffix(" MB")
        vid.add_row("Size", self.target_mb,
                    hint="2-pass encode aimed at this file size")

        self.max_mb = QDoubleSpinBox()
        self.max_mb.setRange(0.0, 100_000)
        self.max_mb.setValue(0.0)
        self.max_mb.setDecimals(1)
        self.max_mb.setSuffix(" MB")
        self.max_mb.setSpecialValueText("no limit")
        vid.add_row("Max size", self.max_mb,
                    hint="quality still decides the size — this only stops it "
                         "going over (0 = off)")

        self.preset = QComboBox()
        self.preset.addItems(PRESETS)
        self.preset.setCurrentText("medium")
        vid.add_row("Preset", self.preset,
                    hint="slower = smaller file for the same quality")
        lay.addWidget(vid)
        self.sec_video = vid

        # ---- Resize & FPS (cyan) --------------------------------------
        rs = Section("Resize · FPS · Rotate", "cyan")
        self.scale = QComboBox()
        for key in SCALE_ORDER:
            self.scale.addItem(SCALE_LABELS[key], key)
        rs.add_row("Resolution", self.scale)

        self.scale_percent = QSpinBox()
        self.scale_percent.setRange(1, 400)
        self.scale_percent.setValue(50)
        self.scale_percent.setSuffix(" %")
        rs.add_row("Percent", self.scale_percent)

        self.scale_w = QSpinBox()
        self.scale_w.setRange(-2, 7680)
        self.scale_w.setValue(1920)
        self.scale_h = QSpinBox()
        self.scale_h.setRange(-2, 4320)
        self.scale_h.setValue(-2)
        rs.add_row("Size", hrow(self.scale_w, QLabel("×"), self.scale_h,
                                stretch_last=True),
                   hint="-2 keeps the aspect ratio for that side")

        self.fps = QComboBox()
        for label, data in [("Keep original", "keep"), ("60", "60"),
                            ("30", "30"), ("24", "24"), ("Custom…", "custom")]:
            self.fps.addItem(label, data)
        self.fps_custom = QDoubleSpinBox()
        self.fps_custom.setRange(0.1, 480)
        self.fps_custom.setValue(30.0)
        self.fps_custom.setDecimals(2)
        rs.add_row("Frame rate", hrow(self.fps, self.fps_custom))

        self.rotate = QComboBox()
        for label, deg in [("No rotation", 0), ("90° clockwise", 90),
                           ("180°", 180), ("90° counter-clockwise", 270)]:
            self.rotate.addItem(label, deg)
        self.flip_h = QCheckBox("Flip ↔")
        self.flip_v = QCheckBox("Flip ↕")
        rs.add_row("Rotate", hrow(self.rotate, self.flip_h, self.flip_v,
                                  stretch_last=True))
        lay.addWidget(rs)
        self.sec_resize = rs

        # ---- Audio (purple) -------------------------------------------
        au = Section("Audio", "purple")
        self.audio_mode = QComboBox()
        for key, label in AUDIO_MODE_LABELS.items():
            self.audio_mode.addItem(label, key)
        au.add_row("Track", self.audio_mode)

        self.abitrate = QComboBox()
        for kbps in (96, 128, 160, 192, 256, 320):
            self.abitrate.addItem(f"{kbps} kbps", kbps)
        self.abitrate.setCurrentIndex(3)
        au.add_row("Bitrate", self.abitrate)

        self.mono = QCheckBox("Downmix to mono")
        au.add_row("", self.mono,
                   hint="mixes left and right equally — fixes VRChat POV "
                        "recordings where music swings between the ears")
        self.normalize = QCheckBox("Normalize loudness (loudnorm)")
        au.add_row("", self.normalize)
        lay.addWidget(au)
        self.sec_audio = au

        # ---- Trim (yellow) --------------------------------------------
        tr = Section("Trim", "yellow")
        self.trim_on = QCheckBox("Cut a time range")
        tr.add_row("", self.trim_on)
        self.trim_start = QLineEdit()
        self.trim_start.setPlaceholderText("0:00")
        self.trim_end = QLineEdit()
        self.trim_end.setPlaceholderText("end")
        tr.add_row("From / to", hrow(self.trim_start, QLabel("→"),
                                     self.trim_end),
                   hint="formats: 90 · 1:30 · 0:01:30.5 — empty end = play out")
        lay.addWidget(tr)
        self.sec_trim = tr

        # ---- Timelapse (cyan) -----------------------------------------
        tl = Section("Timelapse", "cyan")
        self.timelapse_on = QCheckBox("Speed the clip up to a set length")
        tl.add_row("", self.timelapse_on)
        self.timelapse_len = QLineEdit()
        self.timelapse_len.setPlaceholderText("0:30")
        tl.add_row("Make it", self.timelapse_len,
                   hint="how long the result should be — the speed-up is "
                        "worked out per file · 30 · 0:30 · 1:30")
        self.timelapse_note = QLabel("")
        self.timelapse_note.setObjectName("Hint")
        self.timelapse_note.setWordWrap(True)
        tl.add_wide(self.timelapse_note)
        lay.addWidget(tl)
        self.sec_timelapse = tl

        # ---- GIF / WebP (red) -----------------------------------------
        an = Section("GIF / WebP", "red")
        self.anim_fps = QSpinBox()
        self.anim_fps.setRange(1, 60)
        self.anim_fps.setValue(15)
        self.anim_fps.setSuffix(" fps")
        an.add_row("Frame rate", self.anim_fps)
        self.anim_width = QSpinBox()
        self.anim_width.setRange(0, 3840)
        self.anim_width.setValue(480)
        self.anim_width.setSpecialValueText("keep width")
        self.anim_width.setSuffix(" px wide")
        an.add_row("Width", self.anim_width,
                   hint="GIFs get a generated color palette for max quality")
        lay.addWidget(an)
        self.sec_anim = an

        # ---- Output & extras (green) ----------------------------------
        ex = Section("Output & extras", "green")
        self.suffix = QLineEdit()
        self.suffix.setPlaceholderText("e.g.  _1080p  (empty = keep name)")
        ex.add_row("Name suffix", self.suffix)
        self.custom_args = QLineEdit()
        self.custom_args.setPlaceholderText("extra ffmpeg args (advanced)")
        ex.add_row("Custom args", self.custom_args)
        lay.addWidget(ex)
        self.sec_extras = ex

        lay.addStretch(1)

        # wire everything to the changed signal + enable logic
        self.crf.valueChanged.connect(
            lambda v: self.crf_label.setText(str(v)))
        for combo in (self.container, self.vcodec, self.preset, self.scale,
                      self.fps, self.rotate, self.audio_mode, self.abitrate):
            combo.currentIndexChanged.connect(self._on_change)
        for spin in (self.vbitrate, self.target_mb, self.max_mb,
                     self.scale_percent,
                     self.scale_w, self.scale_h, self.fps_custom,
                     self.anim_fps, self.anim_width):
            spin.valueChanged.connect(self._on_change)
        for check in (self.flip_h, self.flip_v, self.normalize, self.mono,
                      self.trim_on, self.timelapse_on):
            check.toggled.connect(self._on_change)
        for radio in (self.rate_crf, self.rate_bitrate, self.rate_size):
            radio.toggled.connect(self._on_change)
        for edit in (self.trim_start, self.trim_end, self.suffix,
                     self.custom_args, self.timelapse_len):
            edit.textChanged.connect(self._on_change)
        self.crf.valueChanged.connect(self._on_change)

        self._update_enabled()

    # -- GPU encoders ----------------------------------------------------
    def set_gpu_encoders(self, encoders: set[str]) -> None:
        self._gpu = set(encoders)
        current = self.vcodec.currentData()
        self._rebuild_codecs(keep=current)

    def _rebuild_codecs(self, keep: str | None = None) -> None:
        self.vcodec.blockSignals(True)
        self.vcodec.clear()
        for key in _CPU_CODECS + [g for g in _GPU_CODECS if g in self._gpu]:
            self.vcodec.addItem(VIDEO_CODEC_LABELS[key], key)
        if keep is not None:
            idx = self.vcodec.findData(keep)
            self.vcodec.setCurrentIndex(idx if idx >= 0 else 0)
        self.vcodec.blockSignals(False)

    # -- spec <-> widgets ------------------------------------------------
    def _timelapse_seconds(self) -> float:
        """Parse the target length; fall back to 30s while it's half-typed."""
        text = self.timelapse_len.text().strip()
        if not text:
            return 30.0
        try:
            return max(0.1, parse_time(text))
        except ValueError:
            return 30.0

    def get_spec(self) -> JobSpec:
        fps_data = self.fps.currentData()
        return JobSpec(
            container=self.container.currentData(),
            video_codec=self.vcodec.currentData() or "auto",
            rate_mode=("crf" if self.rate_crf.isChecked() else
                       "bitrate" if self.rate_bitrate.isChecked() else "size"),
            crf=self.crf.value(),
            preset=self.preset.currentText(),
            video_bitrate=self.vbitrate.value(),
            target_mb=self.target_mb.value(),
            max_mb=self.max_mb.value(),
            scale_mode=self.scale.currentData(),
            scale_percent=self.scale_percent.value(),
            scale_w=self.scale_w.value(),
            scale_h=self.scale_h.value(),
            fps_mode="keep" if fps_data == "keep" else "custom",
            fps=(self.fps_custom.value() if fps_data == "custom"
                 else float(fps_data) if fps_data != "keep" else 30.0),
            rotate=self.rotate.currentData(),
            flip_h=self.flip_h.isChecked(),
            flip_v=self.flip_v.isChecked(),
            audio_mode=self.audio_mode.currentData(),
            audio_bitrate=self.abitrate.currentData(),
            normalize=self.normalize.isChecked(),
            mono=self.mono.isChecked(),
            timelapse=self.timelapse_on.isChecked(),
            timelapse_seconds=self._timelapse_seconds(),
            trim=self.trim_on.isChecked(),
            trim_start=self.trim_start.text(),
            trim_end=self.trim_end.text(),
            anim_fps=self.anim_fps.value(),
            anim_width=self.anim_width.value(),
            suffix=self.suffix.text().strip(),
            custom_args=self.custom_args.text(),
        )

    def set_spec(self, spec: JobSpec) -> None:
        self._loading = True
        try:
            idx = self.container.findData(spec.container)
            self.container.setCurrentIndex(max(0, idx))
            idx = self.vcodec.findData(spec.video_codec)
            if idx < 0 and spec.video_codec.endswith("_nvenc"):
                # profile wants GPU but this machine has none — builder
                # falls back at run time; select the CPU twin for clarity
                idx = self.vcodec.findData(
                    spec.video_codec.replace("_nvenc", ""))
            self.vcodec.setCurrentIndex(max(0, idx))
            {"crf": self.rate_crf, "bitrate": self.rate_bitrate,
             "size": self.rate_size}.get(spec.rate_mode,
                                         self.rate_crf).setChecked(True)
            self.crf.setValue(spec.crf)
            self.preset.setCurrentText(
                spec.preset if spec.preset in PRESETS else "medium")
            self.vbitrate.setValue(spec.video_bitrate)
            self.target_mb.setValue(spec.target_mb)
            self.max_mb.setValue(spec.max_mb)
            idx = self.scale.findData(spec.scale_mode)
            self.scale.setCurrentIndex(max(0, idx))
            self.scale_percent.setValue(spec.scale_percent)
            self.scale_w.setValue(spec.scale_w)
            self.scale_h.setValue(spec.scale_h)
            if spec.fps_mode == "keep":
                self.fps.setCurrentIndex(0)
            else:
                whole = f"{spec.fps:g}"
                idx = self.fps.findData(whole)
                if idx > 0:
                    self.fps.setCurrentIndex(idx)
                else:
                    self.fps.setCurrentIndex(self.fps.findData("custom"))
                    self.fps_custom.setValue(spec.fps)
            idx = self.rotate.findData(spec.rotate)
            self.rotate.setCurrentIndex(max(0, idx))
            self.flip_h.setChecked(spec.flip_h)
            self.flip_v.setChecked(spec.flip_v)
            idx = self.audio_mode.findData(spec.audio_mode)
            self.audio_mode.setCurrentIndex(max(0, idx))
            idx = self.abitrate.findData(spec.audio_bitrate)
            if idx < 0:
                self.abitrate.addItem(f"{spec.audio_bitrate} kbps",
                                      spec.audio_bitrate)
                idx = self.abitrate.count() - 1
            self.abitrate.setCurrentIndex(idx)
            self.normalize.setChecked(spec.normalize)
            self.mono.setChecked(spec.mono)
            self.timelapse_on.setChecked(spec.timelapse)
            self.timelapse_len.setText(format_seconds(spec.timelapse_seconds))
            self.trim_on.setChecked(spec.trim)
            self.trim_start.setText(spec.trim_start)
            self.trim_end.setText(spec.trim_end)
            self.anim_fps.setValue(spec.anim_fps)
            self.anim_width.setValue(spec.anim_width)
            self.suffix.setText(spec.suffix)
            self.custom_args.setText(spec.custom_args)
        finally:
            self._loading = False
        self._update_enabled()
        self.changed.emit()

    # -- enable/disable by context --------------------------------------
    def _on_change(self, *_args) -> None:
        if self._loading:
            return
        self._update_enabled()
        self.changed.emit()

    def _update_enabled(self) -> None:
        kind = JobSpec(container=self.container.currentData() or "mp4").kind()
        is_video = kind in ("video", "same")
        is_anim = kind == "anim"
        is_audio = kind == "audio"
        is_image = kind == "image"

        self.sec_video.setEnabled(is_video)
        self.sec_resize.setEnabled(is_video or is_anim or is_image)
        self.sec_audio.setEnabled(is_video or is_audio)
        self.sec_anim.setEnabled(is_anim)

        # rate-mode sub-widgets
        crf_on = self.rate_crf.isChecked()
        self.crf.setEnabled(crf_on)
        self.crf_label.setEnabled(crf_on)
        self.vbitrate.setEnabled(self.rate_bitrate.isChecked())
        self.target_mb.setEnabled(self.rate_size.isChecked())
        # the ceiling only means anything while quality drives the bitrate
        self.max_mb.setEnabled(crf_on)
        copy = (self.vcodec.currentData() == "copy")
        for w in (self.crf, self.vbitrate, self.target_mb, self.max_mb,
                  self.preset):
            if copy:
                w.setEnabled(False)
        for b in (self.rate_crf, self.rate_bitrate, self.rate_size):
            b.setEnabled(not copy)

        # audio sub-widgets — mono/normalize both force an encode
        amode = self.audio_mode.currentData()
        encoding = (amode == "encode") or self.normalize.isChecked() \
            or self.mono.isChecked()
        self.abitrate.setEnabled(self.sec_audio.isEnabled() and encoding
                                 and self.container.currentData()
                                 not in ("flac", "wav"))
        self.normalize.setEnabled(amode != "remove")
        self.mono.setEnabled(amode != "remove")

        # anim / resize details
        self.scale_percent.setEnabled(self.scale.currentData() == "percent")
        for w in (self.scale_w, self.scale_h):
            w.setEnabled(self.scale.currentData() == "custom")
        self.fps_custom.setEnabled(self.fps.currentData() == "custom")
        self.fps.setEnabled(is_video)

        # timelapse: length box only matters once it's switched on
        self.timelapse_len.setEnabled(self.timelapse_on.isChecked())
        self.sec_timelapse.setEnabled(is_video or is_anim)
        self.sec_timelapse.badge.setText(
            "" if (is_video or is_anim) else "video only")

        # section badges show why something is off
        self.sec_video.badge.setText("" if is_video else "n/a for this format")
        self.sec_audio.badge.setText(
            "" if self.sec_audio.isEnabled() else "n/a for this format")
        self.sec_anim.badge.setText(
            "" if is_anim else "pick GIF/WebP format")
