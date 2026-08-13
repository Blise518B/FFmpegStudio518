"""Unit tests for the ffmpeg command builder (pure logic, no Qt/ffmpeg)."""
from __future__ import annotations

import unittest
from pathlib import Path

from ffmpeg_studio.ffmpeg.command import (BuildError, build_plan, parse_time,
                                          resolve_output)
from ffmpeg_studio.ffmpeg.probe import MediaInfo
from ffmpeg_studio.spec import JobSpec

SRC = Path(r"C:\in\clip one.mp4")
OUT = Path(r"C:\out")


def info(**kw) -> MediaInfo:
    base = dict(path=SRC, duration=120.0, has_video=True, has_audio=True,
                v_codec="h264", a_codec="aac", width=1920, height=1080,
                a_bitrate=160, a_channels=2)
    base.update(kw)
    return MediaInfo(**base)


def flat(plan) -> list[str]:
    return [a for p in plan.passes for a in p]


class TestParseTime(unittest.TestCase):
    def test_colon_form_reads_right_to_left(self):
        self.assertEqual(parse_time("1:30"), 90.0)
        self.assertEqual(parse_time("01:02:03.5"), 3723.5)
        self.assertEqual(parse_time("0:05"), 5.0)

    def test_bare_number_is_seconds(self):
        self.assertEqual(parse_time("90"), 90.0)
        self.assertEqual(parse_time("90.5"), 90.5)
        self.assertEqual(parse_time("5"), 5.0)

    def test_unit_suffixes(self):
        self.assertEqual(parse_time("90s"), 90.0)
        self.assertEqual(parse_time("2m"), 120.0)
        self.assertEqual(parse_time("1h"), 3600.0)
        self.assertEqual(parse_time("2m30s"), 150.0)
        self.assertEqual(parse_time("1h30m"), 5400.0)
        self.assertEqual(parse_time("1h2m3s"), 3723.0)
        self.assertEqual(parse_time("1.5m"), 90.0)

    def test_units_are_forgiving_about_spelling_and_spaces(self):
        for text in ("1h 30m", "1 hour 30 min", "90 sec", "1hr30mins"):
            parse_time(text)          # must not raise
        self.assertEqual(parse_time("1 hour 30 min"), 5400.0)
        self.assertEqual(parse_time("90 SEC"), 90.0)

    def test_the_three_forms_agree(self):
        self.assertEqual(parse_time("1:30"), parse_time("90"))
        self.assertEqual(parse_time("90"), parse_time("1m30s"))

    def test_bad(self):
        for bad in ("", "a", "1:2:3:4", "1::2", "-5", "5x", "m", "1m2h",
                    "banana", "1:2:3s"):
            with self.assertRaises(ValueError):
                parse_time(bad)


class TestResolveOutput(unittest.TestCase):
    def test_suffix_and_ext(self):
        out = resolve_output(SRC, OUT, "mkv", "_x", overwrite=True)
        self.assertEqual(out, OUT / "clip one_x.mkv")

    def test_never_source_itself(self):
        out = resolve_output(SRC, SRC.parent, "mp4", "", overwrite=True)
        self.assertNotEqual(str(out).lower(), str(SRC).lower())
        self.assertIn("_out", out.name)


class TestVideoBuilds(unittest.TestCase):
    def test_basic_h264_crf(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="h264",
                                  crf=20), info(), OUT)
        args = flat(plan)
        self.assertEqual(len(plan.passes), 1)
        self.assertIn("libx264", args)
        self.assertIn("-crf", args)
        self.assertEqual(args[args.index("-crf") + 1], "20")
        self.assertIn("+faststart", args)
        self.assertIn("-c:a", args)
        self.assertEqual(args[args.index("-c:a") + 1], "copy")
        self.assertEqual(args[-1], str(OUT / "clip one.mp4"))

    def test_copy_remux(self):
        plan = build_plan(JobSpec(container="mkv", video_codec="copy"),
                          info(), OUT)
        args = flat(plan)
        self.assertEqual(args[args.index("-c:v") + 1], "copy")
        self.assertEqual(plan.notes, [])

    def test_copy_with_filters_falls_back(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="copy",
                                  scale_mode="720"), info(), OUT)
        args = flat(plan)
        self.assertIn("libx264", args)
        self.assertTrue(any("re-encod" in n or "encoding" in n
                            for n in plan.notes))

    def test_copy_incompatible_container(self):
        plan = build_plan(JobSpec(container="webm", video_codec="copy"),
                          info(v_codec="h264"), OUT)
        args = flat(plan)
        self.assertIn("libvpx-vp9", args)

    def test_no_upscale(self):
        plan = build_plan(JobSpec(container="mp4", scale_mode="2160"),
                          info(width=1280, height=720), OUT)
        self.assertNotIn("-vf", flat(plan))

    def test_downscale_landscape(self):
        plan = build_plan(JobSpec(container="mp4", scale_mode="720"),
                          info(), OUT)
        args = flat(plan)
        vf = args[args.index("-vf") + 1]
        self.assertIn("scale=-2:720", vf)

    def test_downscale_portrait_targets_short_side(self):
        plan = build_plan(JobSpec(container="mp4", scale_mode="720"),
                          info(width=1080, height=1920), OUT)
        args = flat(plan)
        vf = args[args.index("-vf") + 1]
        self.assertIn("scale=720:-2", vf)

    def test_percent_scale(self):
        plan = build_plan(JobSpec(container="mp4", scale_mode="percent",
                                  scale_percent=50), info(), OUT)
        args = flat(plan)
        self.assertIn("scale=960:540", args[args.index("-vf") + 1])

    def test_rotate_uses_postrotate_dims(self):
        # 1920x1080 rotated 90° becomes 1080x1920 (portrait): target short side
        plan = build_plan(JobSpec(container="mp4", scale_mode="720",
                                  rotate=90), info(), OUT)
        vf = flat(plan)[flat(plan).index("-vf") + 1]
        self.assertIn("transpose=1", vf)
        self.assertIn("scale=720:-2", vf)

    def test_fps_filter(self):
        plan = build_plan(JobSpec(container="mp4", fps_mode="custom",
                                  fps=30.0), info(), OUT)
        self.assertIn("fps=30", flat(plan)[flat(plan).index("-vf") + 1])

    def test_two_pass_size(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="h264",
                                  rate_mode="size", target_mb=10.0,
                                  audio_mode="encode", audio_bitrate=96),
                          info(), OUT)
        self.assertEqual(len(plan.passes), 2)
        p1, p2 = plan.passes
        self.assertIn("null", p1)
        self.assertIn("-an", p1)
        self.assertNotIn("-an", p2)
        self.assertIsNotNone(plan.passlog)
        # 10 MiB * 8192 kbit * 0.97 / 120 s - 96 kbps audio = 566 kbps
        idx = p2.index("-b:v")
        self.assertEqual(p2[idx + 1], "566k")

    def test_size_mode_nvenc_single_pass(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="h264_nvenc",
                                  rate_mode="size", target_mb=10.0),
                          info(), OUT, gpu_encoders={"h264_nvenc"})
        self.assertEqual(len(plan.passes), 1)
        self.assertTrue(any("single-pass" in n for n in plan.notes))

    def test_nvenc_fallback_when_missing(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="hevc_nvenc"),
                          info(), OUT, gpu_encoders=set())
        args = flat(plan)
        self.assertIn("libx265", args)
        self.assertTrue(any("NVENC" in n for n in plan.notes))

    def test_nvenc_used_when_available(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="h264_nvenc"),
                          info(), OUT, gpu_encoders={"h264_nvenc"})
        args = flat(plan)
        self.assertIn("h264_nvenc", args)
        self.assertIn("-cq", args)

    def test_webm_audio_copy_incompatible(self):
        plan = build_plan(JobSpec(container="webm", audio_mode="keep"),
                          info(a_codec="aac"), OUT)
        args = flat(plan)
        self.assertIn("libopus", args)

    def test_mkv_keeps_subs_mp4_drops(self):
        keep = build_plan(JobSpec(container="mkv"), info(has_subs=True), OUT)
        drop = build_plan(JobSpec(container="mp4"), info(has_subs=True), OUT)
        self.assertIn("-c:s", flat(keep))
        self.assertIn("-sn", flat(drop))

    def test_trim(self):
        plan = build_plan(JobSpec(container="mp4", trim=True,
                                  trim_start="0:10", trim_end="0:40"),
                          info(), OUT)
        args = flat(plan)
        self.assertLess(args.index("-ss"), args.index("-i"))
        self.assertEqual(args[args.index("-ss") + 1], "10")
        self.assertEqual(args[args.index("-t") + 1], "30")
        self.assertEqual(plan.duration, 30.0)

    def test_no_video_stream_raises(self):
        with self.assertRaises(BuildError):
            build_plan(JobSpec(container="mp4"), info(has_video=False), OUT)

    def test_custom_args_appended(self):
        plan = build_plan(JobSpec(container="mp4",
                                  custom_args='-metadata title="my clip"'),
                          info(), OUT)
        args = flat(plan)
        self.assertIn("-metadata", args)
        self.assertIn("title=my clip", args)


class TestRgbMastering(unittest.TestCase):
    """libx264rgb — what the friend's batch script reaches for."""

    def test_uses_libx264rgb_without_forcing_yuv(self):
        plan = build_plan(JobSpec(container="mkv", video_codec="h264rgb",
                                  crf=12), info(), OUT)
        args = flat(plan)
        self.assertIn("libx264rgb", args)
        # forcing yuv420p would throw the chroma away again
        self.assertNotIn("yuv420p", args)
        self.assertEqual(args[args.index("-crf") + 1], "12")

    def test_warns_about_playback(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="h264rgb"),
                          info(), OUT)
        self.assertTrue(any("hardware-decode" in n for n in plan.notes))

    def test_crf_zero_allowed_for_lossless(self):
        plan = build_plan(JobSpec(container="mkv", video_codec="h264rgb",
                                  crf=0), info(), OUT)
        args = flat(plan)
        self.assertEqual(args[args.index("-crf") + 1], "0")

    def test_falls_back_for_incompatible_container(self):
        plan = build_plan(JobSpec(container="webm", video_codec="h264rgb"),
                          info(), OUT)
        args = flat(plan)
        self.assertNotIn("libx264rgb", args)
        self.assertIn("libvpx-vp9", args)
        self.assertTrue(any("can't carry RGB" in n for n in plan.notes))

    def test_audio_copy_survives(self):
        # the script's "-c:a copy"
        plan = build_plan(JobSpec(container="mkv", video_codec="h264rgb",
                                  audio_mode="keep"), info(), OUT)
        args = flat(plan)
        self.assertEqual(args[args.index("-c:a") + 1], "copy")

    def test_preset_still_applies(self):
        plan = build_plan(JobSpec(container="mkv", video_codec="h264rgb",
                                  preset="slow"), info(), OUT)
        args = flat(plan)
        self.assertEqual(args[args.index("-preset") + 1], "slow")


class TestWebSafeSharing(unittest.TestCase):
    """h264_compat: copy when it already plays on Discord, else convert."""

    MB = 1024 * 1024

    def _plan(self, **kw):
        spec = JobSpec(container="mp4", video_codec="h264_compat", crf=16,
                       max_mb=kw.pop("max_mb", 500.0), audio_mode="keep")
        return build_plan(spec, info(**kw), OUT)

    def test_ready_file_is_stream_copied(self):
        plan = self._plan(pix_fmt="yuv420p", size_bytes=200 * self.MB)
        args = flat(plan)
        self.assertEqual(args[args.index("-c:v") + 1], "copy")
        self.assertEqual(args[args.index("-c:a") + 1], "copy")
        self.assertIn("+faststart", args)      # required for inline embeds

    def test_rgb_master_is_converted_to_yuv420p(self):
        plan = self._plan(pix_fmt="gbrp", size_bytes=100 * self.MB)
        args = flat(plan)
        self.assertIn("libx264", args)
        self.assertEqual(args[args.index("-pix_fmt") + 1], "yuv420p")
        self.assertTrue(any("gbrp" in n for n in plan.notes))

    def test_ten_bit_is_converted(self):
        plan = self._plan(pix_fmt="yuv420p10le", size_bytes=10 * self.MB)
        self.assertIn("libx264", flat(plan))

    def test_hevc_is_converted(self):
        plan = self._plan(v_codec="hevc", pix_fmt="yuv420p",
                          size_bytes=10 * self.MB)
        args = flat(plan)
        self.assertIn("libx264", args)
        self.assertTrue(any("HEVC" in n for n in plan.notes))

    def test_oversized_file_is_reencoded_even_though_it_would_play(self):
        plan = self._plan(pix_fmt="yuv420p", size_bytes=900 * self.MB)
        args = flat(plan)
        self.assertIn("libx264", args)
        self.assertIn("-maxrate", args)
        self.assertTrue(any("500 MB limit" in n for n in plan.notes))

    def test_ac3_audio_reencodes_without_touching_video(self):
        plan = self._plan(pix_fmt="yuv420p", a_codec="ac3",
                          size_bytes=10 * self.MB)
        args = flat(plan)
        self.assertEqual(args[args.index("-c:v") + 1], "copy")
        self.assertEqual(args[args.index("-c:a") + 1], "aac")

    def test_no_limit_lets_a_huge_ready_file_copy(self):
        plan = self._plan(pix_fmt="yuv420p", size_bytes=5000 * self.MB,
                          max_mb=0.0)
        self.assertEqual(flat(plan)[flat(plan).index("-c:v") + 1], "copy")


class TestSizeCeiling(unittest.TestCase):
    """max_mb caps quality mode without inflating small files."""

    def test_cap_becomes_maxrate_and_bufsize(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="h264",
                                  crf=18, max_mb=500.0, audio_mode="encode",
                                  audio_bitrate=128),
                          info(duration=600.0), OUT)
        args = flat(plan)
        # 500 MiB * 8192 kbit * 0.97 / 600 s - 128 kbps audio
        self.assertEqual(args[args.index("-maxrate") + 1], "6493k")
        self.assertEqual(args[args.index("-bufsize") + 1], "12986k")
        self.assertIn("-crf", args)          # quality still drives it
        self.assertEqual(len(plan.passes), 1)

    def test_no_cap_by_default(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="h264"),
                          info(), OUT)
        self.assertNotIn("-maxrate", flat(plan))

    def test_cap_needs_a_duration(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="h264",
                                  max_mb=100.0), info(duration=None), OUT)
        self.assertNotIn("-maxrate", flat(plan))
        self.assertTrue(any("Unknown duration" in n for n in plan.notes))

    def test_short_clip_drops_an_unreachable_cap(self):
        """A 2 s clip under a 500 MB budget works out to ~2 Gbps, which x264
        rejects outright (bufsize overflows int32). The cap can't bind, so it
        must not be emitted at all."""
        plan = build_plan(JobSpec(container="mp4", video_codec="h264",
                                  crf=16, max_mb=500.0),
                          info(duration=2.0), OUT)
        args = flat(plan)
        self.assertNotIn("-maxrate", args)
        self.assertNotIn("-bufsize", args)
        self.assertIn("-crf", args)

    def test_cap_still_applies_at_realistic_lengths(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="h264",
                                  crf=16, max_mb=500.0),
                          info(duration=3600.0), OUT)
        args = flat(plan)
        self.assertIn("-maxrate", args)
        rate = int(args[args.index("-maxrate") + 1].rstrip("k"))
        self.assertLess(rate, 200_000)
        self.assertGreater(rate, 0)

    def test_cap_ignored_in_target_size_mode(self):
        plan = build_plan(JobSpec(container="mp4", video_codec="h264",
                                  rate_mode="size", target_mb=20.0,
                                  max_mb=500.0), info(), OUT)
        args = flat(plan)
        self.assertIn("-b:v", args)          # target-size math, not the cap
        self.assertNotIn("-crf", args)


class TestAudioBuilds(unittest.TestCase):
    def test_extract_mp3(self):
        plan = build_plan(JobSpec(container="mp3", audio_mode="encode",
                                  audio_bitrate=320), info(), OUT)
        args = flat(plan)
        self.assertIn("-vn", args)
        self.assertIn("libmp3lame", args)
        self.assertEqual(args[args.index("-b:a") + 1], "320k")

    def test_m4a_copy_when_source_is_aac(self):
        plan = build_plan(JobSpec(container="m4a", audio_mode="keep"),
                          info(a_codec="aac"), OUT)
        args = flat(plan)
        self.assertEqual(args[args.index("-c:a") + 1], "copy")

    def test_mp3_from_aac_reencodes(self):
        plan = build_plan(JobSpec(container="mp3", audio_mode="keep"),
                          info(a_codec="aac"), OUT)
        self.assertIn("libmp3lame", flat(plan))

    def test_no_audio_raises(self):
        with self.assertRaises(BuildError):
            build_plan(JobSpec(container="mp3"), info(has_audio=False), OUT)

    def test_normalize(self):
        plan = build_plan(JobSpec(container="mp3", audio_mode="encode",
                                  normalize=True), info(), OUT)
        args = flat(plan)
        self.assertIn("-af", args)
        self.assertIn("loudnorm", args[args.index("-af") + 1])


class TestMonoDownmix(unittest.TestCase):
    def test_stereo_uses_equal_pan(self):
        plan = build_plan(JobSpec(container="mp4", audio_mode="encode",
                                  mono=True), info(), OUT)
        args = flat(plan)
        self.assertEqual(args[args.index("-af") + 1],
                         "pan=mono|c0=0.5*c0+0.5*c1")

    def test_forces_reencode_from_keep(self):
        plan = build_plan(JobSpec(container="mp4", audio_mode="keep",
                                  mono=True), info(), OUT)
        args = flat(plan)
        self.assertNotIn("copy", args[args.index("-c:a") + 1])
        self.assertIn("aac", args)
        self.assertTrue(any("Mono downmix" in n for n in plan.notes))

    def test_video_stream_still_copied(self):
        # the whole point of the VRC profile: fix audio, don't re-encode video
        plan = build_plan(JobSpec(container="same", video_codec="copy",
                                  audio_mode="encode", mono=True),
                          info(), OUT)
        args = flat(plan)
        self.assertEqual(args[args.index("-c:v") + 1], "copy")
        self.assertIn("pan=mono|c0=0.5*c0+0.5*c1", args)
        self.assertEqual(len(plan.passes), 1)

    def test_already_mono_source_still_copies(self):
        plan = build_plan(JobSpec(container="mp4", audio_mode="keep",
                                  mono=True), info(a_channels=1), OUT)
        args = flat(plan)
        self.assertEqual(args[args.index("-c:a") + 1], "copy")
        self.assertNotIn("-af", args)

    def test_surround_uses_ac_matrix(self):
        plan = build_plan(JobSpec(container="mp4", audio_mode="encode",
                                  mono=True), info(a_channels=6), OUT)
        args = flat(plan)
        self.assertEqual(args[args.index("-ac") + 1], "1")
        self.assertNotIn("-af", args)

    def test_unknown_channels_falls_back_to_ac(self):
        plan = build_plan(JobSpec(container="mp4", audio_mode="encode",
                                  mono=True), info(a_channels=0), OUT)
        self.assertIn("-ac", flat(plan))

    def test_mono_then_normalize_order(self):
        plan = build_plan(JobSpec(container="mp4", audio_mode="encode",
                                  mono=True, normalize=True), info(), OUT)
        chain = flat(plan)[flat(plan).index("-af") + 1]
        self.assertTrue(chain.startswith("pan=mono"))
        self.assertIn("loudnorm", chain)
        self.assertLess(chain.index("pan=mono"), chain.index("loudnorm"))

    def test_audio_only_target_downmixes(self):
        plan = build_plan(JobSpec(container="mp3", audio_mode="encode",
                                  mono=True), info(), OUT)
        args = flat(plan)
        self.assertIn("libmp3lame", args)
        self.assertIn("pan=mono|c0=0.5*c0+0.5*c1", args)

    def test_remove_audio_wins(self):
        plan = build_plan(JobSpec(container="mp4", audio_mode="remove",
                                  mono=True), info(), OUT)
        args = flat(plan)
        self.assertIn("-an", args)
        self.assertNotIn("-af", args)


class TestTimelapse(unittest.TestCase):
    """Pick an output length; the speed-up is derived per file."""

    def _plan(self, seconds=30.0, **kw):
        spec = JobSpec(container="mp4", video_codec="h264",
                       timelapse=True, timelapse_seconds=seconds,
                       audio_mode=kw.pop("audio_mode", "remove"), **kw)
        return build_plan(spec, info(**{"duration": kw.pop("src", 600.0),
                                        **kw.pop("info_kw", {})}), OUT)

    def test_speed_matches_the_target_length(self):
        # 600 s squeezed into 30 s is 20x
        plan = self._plan(seconds=30.0)
        vf = flat(plan)[flat(plan).index("-vf") + 1]
        self.assertIn("setpts=PTS/20", vf)

    def test_progress_uses_the_output_length(self):
        plan = self._plan(seconds=30.0)
        self.assertEqual(plan.duration, 30.0)

    def test_output_frame_rate_is_normalised(self):
        plan = self._plan(seconds=30.0)
        vf = flat(plan)[flat(plan).index("-vf") + 1]
        self.assertRegex(vf, r"fps=\d")
        self.assertLess(vf.index("setpts"), vf.index("fps="))

    def test_trim_bounds_the_read_not_the_output(self):
        """-t must sit before -i. After it, it limits the *output*, and a
        retiming filter then reads to the end of the file instead of the
        trim end — asking for 3 s of 0:10–0:40 silently gave 5 s."""
        spec = JobSpec(container="mp4", video_codec="h264", timelapse=True,
                       timelapse_seconds=3.0, audio_mode="remove",
                       trim=True, trim_start="0:10", trim_end="0:40")
        args = flat(build_plan(spec, info(duration=60.0), OUT))
        self.assertLess(args.index("-t"), args.index("-i"))
        self.assertLess(args.index("-ss"), args.index("-i"))
        self.assertEqual(args[args.index("-t") + 1], "30")

    def test_trim_defines_the_source_length(self):
        # 60 s of a 600 s clip, into 30 s, is 2x — not 20x
        spec = JobSpec(container="mp4", video_codec="h264", timelapse=True,
                       timelapse_seconds=30.0, audio_mode="remove",
                       trim=True, trim_start="0:10", trim_end="1:10")
        plan = build_plan(spec, info(duration=600.0), OUT)
        vf = flat(plan)[flat(plan).index("-vf") + 1]
        self.assertIn("setpts=PTS/2", vf)

    def test_longer_target_slows_it_down(self):
        plan = self._plan(seconds=1200.0)      # 600 s -> 1200 s
        vf = flat(plan)[flat(plan).index("-vf") + 1]
        self.assertIn("setpts=PTS/0.5", vf)
        self.assertTrue(any("slower" in n for n in plan.notes))

    def test_unknown_duration_is_reported_not_guessed(self):
        spec = JobSpec(container="mp4", timelapse=True, audio_mode="remove")
        plan = build_plan(spec, info(duration=None), OUT)
        self.assertNotIn("setpts", " ".join(flat(plan)))
        self.assertTrue(any("can't work out" in n for n in plan.notes))

    def test_copy_is_upgraded_to_a_real_encode(self):
        spec = JobSpec(container="mp4", video_codec="copy", timelapse=True,
                       timelapse_seconds=30.0, audio_mode="remove")
        plan = build_plan(spec, info(duration=600.0), OUT)
        args = flat(plan)
        self.assertIn("libx264", args)          # retiming can't stream-copy
        self.assertIn("setpts=PTS/20", args[args.index("-vf") + 1])

    def test_mild_speedup_keeps_audio_in_step(self):
        spec = JobSpec(container="mp4", video_codec="h264", timelapse=True,
                       timelapse_seconds=300.0, audio_mode="keep")
        plan = build_plan(spec, info(duration=600.0), OUT)   # 2x
        args = flat(plan)
        self.assertEqual(args[args.index("-af") + 1], "atempo=2")
        self.assertNotIn("-an", args)

    def test_big_speedup_drops_audio(self):
        spec = JobSpec(container="mp4", video_codec="h264", timelapse=True,
                       timelapse_seconds=30.0, audio_mode="keep")
        plan = build_plan(spec, info(duration=600.0), OUT)   # 20x
        args = flat(plan)
        self.assertIn("-an", args)
        self.assertTrue(any("Audio dropped" in n for n in plan.notes))

    def test_atempo_chains_past_two(self):
        spec = JobSpec(container="mp4", video_codec="h264", timelapse=True,
                       timelapse_seconds=200.0, audio_mode="keep")
        plan = build_plan(spec, info(duration=600.0), OUT)   # 3x
        chain = flat(plan)[flat(plan).index("-af") + 1]
        self.assertEqual(chain, "atempo=2,atempo=1.5")

    def test_gif_timelapse(self):
        spec = JobSpec(container="gif", timelapse=True, timelapse_seconds=5.0)
        plan = build_plan(spec, info(duration=100.0), OUT)
        graph = flat(plan)[flat(plan).index("-filter_complex") + 1]
        self.assertIn("setpts=PTS/20", graph)

    def test_ignored_for_audio_output(self):
        spec = JobSpec(container="mp3", timelapse=True, audio_mode="encode")
        plan = build_plan(spec, info(duration=600.0), OUT)
        self.assertNotIn("setpts", " ".join(flat(plan)))
        self.assertTrue(any("doesn't apply" in n for n in plan.notes))


class TestAnimAndImage(unittest.TestCase):
    def test_gif_palette(self):
        plan = build_plan(JobSpec(container="gif", anim_fps=15,
                                  anim_width=480), info(), OUT)
        args = flat(plan)
        graph = args[args.index("-filter_complex") + 1]
        self.assertIn("palettegen", graph)
        self.assertIn("paletteuse", graph)
        self.assertIn("fps=15", graph)
        self.assertIn("scale=480:-2", graph)

    def test_webp(self):
        plan = build_plan(JobSpec(container="webp"), info(), OUT)
        self.assertIn("libwebp", flat(plan))

    def test_png_single_frame(self):
        plan = build_plan(JobSpec(container="png"), info(), OUT)
        args = flat(plan)
        self.assertIn("-frames:v", args)


class TestVideoRemoveAudio(unittest.TestCase):
    def test_remove(self):
        plan = build_plan(JobSpec(container="same", video_codec="copy",
                                  audio_mode="remove"), info(), OUT)
        args = flat(plan)
        self.assertIn("-an", args)
        self.assertTrue(args[-1].endswith(".mp4"))


if __name__ == "__main__":
    unittest.main()
