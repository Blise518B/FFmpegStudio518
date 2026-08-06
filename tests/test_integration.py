"""End-to-end: generate a real clip with ffmpeg, run built plans, verify.

Skipped automatically when ffmpeg isn't installed.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from ffmpeg_studio.ffmpeg import locate
from ffmpeg_studio.ffmpeg.command import build_plan
from ffmpeg_studio.ffmpeg.probe import probe
from ffmpeg_studio.spec import JobSpec

INSTALL = locate.find_ffmpeg()


@unittest.skipIf(INSTALL is None, "ffmpeg not available")
class TestRealFFmpeg(unittest.TestCase):
    tmp: tempfile.TemporaryDirectory
    src: Path

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="ffs_it_")
        cls.src = Path(cls.tmp.name) / "test clip.mp4"
        run = subprocess.run(
            [str(INSTALL.ffmpeg), "-hide_banner", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ac", "2", "-shortest", str(cls.src)],
            capture_output=True, timeout=60,
            creationflags=locate.popen_flags())
        assert run.returncode == 0, run.stderr.decode()[-500:]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _run_plan(self, spec: JobSpec) -> Path:
        info = probe(INSTALL.ffprobe, self.src)
        out_dir = Path(self.tmp.name) / "out"
        out_dir.mkdir(exist_ok=True)
        plan = build_plan(spec, info, out_dir, overwrite=True,
                          gpu_encoders=set())
        for args in plan.passes:
            res = subprocess.run(
                [str(INSTALL.ffmpeg)] + args, capture_output=True,
                timeout=120, creationflags=locate.popen_flags())
            self.assertEqual(res.returncode, 0,
                             res.stderr.decode(errors="replace")[-800:])
        self.assertTrue(plan.output.is_file())
        self.assertGreater(plan.output.stat().st_size, 0)
        return plan.output

    def test_convert_scale(self):
        out = self._run_plan(JobSpec(container="mkv", video_codec="h264",
                                     crf=30, preset="ultrafast",
                                     scale_mode="percent", scale_percent=50))
        info = probe(INSTALL.ffprobe, out)
        self.assertEqual((info.width, info.height), (320, 180))

    def test_extract_mp3(self):
        out = self._run_plan(JobSpec(container="mp3", audio_mode="encode",
                                     audio_bitrate=128))
        info = probe(INSTALL.ffprobe, out)
        self.assertTrue(info.has_audio)
        self.assertFalse(info.has_video)

    def test_gif(self):
        out = self._run_plan(JobSpec(container="gif", anim_fps=10,
                                     anim_width=160))
        self.assertEqual(out.suffix, ".gif")

    def test_two_pass_size(self):
        out = self._run_plan(JobSpec(container="mp4", video_codec="h264",
                                     preset="ultrafast", rate_mode="size",
                                     target_mb=1.0, audio_mode="remove"))
        # 2s clip aimed at 1 MiB: just verify it encoded and is in the
        # right ballpark (x264 respects vbv loosely on tiny inputs)
        self.assertLess(out.stat().st_size, 2 * 1024 * 1024)

    def test_trim(self):
        out = self._run_plan(JobSpec(container="mp4", preset="ultrafast",
                                     trim=True, trim_start="0.5",
                                     trim_end="1.5"))
        info = probe(INSTALL.ffprobe, out)
        self.assertAlmostEqual(info.duration, 1.0, delta=0.25)

    def test_remux_copy(self):
        out = self._run_plan(JobSpec(container="mkv", video_codec="copy"))
        info = probe(INSTALL.ffprobe, out)
        self.assertEqual(info.v_codec, "h264")

    def test_rgb_master_is_444_and_audio_copied(self):
        out = self._run_plan(JobSpec(container="mkv", video_codec="h264rgb",
                                     crf=12, preset="ultrafast",
                                     audio_mode="keep"))
        res = subprocess.run(
            [str(INSTALL.ffprobe), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=profile,pix_fmt", "-of", "default=nw=1",
             str(out)], capture_output=True, text=True, timeout=30,
            creationflags=locate.popen_flags())
        self.assertIn("4:4:4", res.stdout)
        self.assertIn("gbrp", res.stdout)
        info = probe(INSTALL.ffprobe, out)
        self.assertEqual(info.a_codec, "aac")     # copied, not re-encoded

    def test_rgb_crf0_is_mathematically_lossless(self):
        """CRF 0 is what 'preserve the colours exactly' actually requires."""
        out = self._run_plan(JobSpec(container="mkv", video_codec="h264rgb",
                                     crf=0, preset="ultrafast",
                                     audio_mode="keep"))
        res = subprocess.run(
            [str(INSTALL.ffmpeg), "-hide_banner", "-i", str(out),
             "-i", str(self.src), "-lavfi", "[0:v][1:v]psnr", "-f", "null",
             "-"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180, creationflags=locate.popen_flags())
        self.assertIn("average:inf", res.stderr.replace(" ", ""))

    def _stream_md5(self, path: Path, stream: str) -> str:
        res = subprocess.run(
            [str(INSTALL.ffmpeg), "-v", "error", "-i", str(path),
             "-map", stream, "-f", "md5", "-"],
            capture_output=True, text=True, timeout=60,
            creationflags=locate.popen_flags())
        return res.stdout.strip()

    def test_discord_profile_copies_an_already_ready_file(self):
        """The headline promise: a normal MP4 comes out bit-identical."""
        from ffmpeg_studio import profiles as prof
        prof.ensure_defaults()
        spec = prof.load_profile("Discord-ready (keep quality)")
        self.assertIsNotNone(spec)
        out = self._run_plan(spec)
        self.assertEqual(self._stream_md5(out, "0:v"),
                         self._stream_md5(self.src, "0:v"))
        self.assertEqual(self._stream_md5(out, "0:a"),
                         self._stream_md5(self.src, "0:a"))

    def test_discord_profile_converts_an_rgb_master(self):
        """An RGB 4:4:4 master can't embed, so it must come back as yuv420p."""
        from ffmpeg_studio import profiles as prof
        prof.ensure_defaults()
        rgb = self._run_plan(prof.load_profile(
            "RGB 4-4-4 master (high quality)"))
        info = probe(INSTALL.ffprobe, rgb)
        self.assertEqual(info.pix_fmt, "gbrp")        # not shareable yet

        out_dir = Path(self.tmp.name) / "out2"
        out_dir.mkdir(exist_ok=True)
        plan = build_plan(prof.load_profile("Discord-ready (keep quality)"),
                          info, out_dir, overwrite=True, gpu_encoders=set())
        for args in plan.passes:
            res = subprocess.run([str(INSTALL.ffmpeg)] + args,
                                 capture_output=True, timeout=180,
                                 creationflags=locate.popen_flags())
            self.assertEqual(res.returncode, 0,
                             res.stderr.decode(errors="replace")[-500:])
        shared = probe(INSTALL.ffprobe, plan.output)
        self.assertEqual(shared.v_codec, "h264")
        self.assertEqual(shared.pix_fmt, "yuv420p")
        self.assertEqual(plan.output.suffix, ".mp4")

    def test_mono_downmix_produces_one_channel(self):
        out = self._run_plan(JobSpec(container="mp4", video_codec="copy",
                                     audio_mode="encode", mono=True))
        info = probe(INSTALL.ffprobe, out)
        self.assertEqual(info.a_channels, 1)
        self.assertEqual(info.v_codec, "h264")     # video untouched

    def test_downmix_weights_both_ears_equally(self):
        """A tone only in the left ear must come out at the same level as the
        same tone only in the right — that's what 'equal' means here."""
        levels = []
        for side, pan in (("left", "c0=c0|c1=0*c0"),
                          ("right", "c0=0*c0|c1=c0")):
            src = Path(self.tmp.name) / f"panned {side}.mp4"
            make = subprocess.run(
                [str(INSTALL.ffmpeg), "-hide_banner", "-y",
                 "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=2",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                 "-af", f"pan=stereo|{pan}",
                 "-c:v", "libx264", "-preset", "ultrafast",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)],
                capture_output=True, timeout=60,
                creationflags=locate.popen_flags())
            self.assertEqual(make.returncode, 0,
                             make.stderr.decode(errors="replace")[-400:])

            info = probe(INSTALL.ffprobe, src)
            self.assertEqual(info.a_channels, 2)
            plan = build_plan(JobSpec(container="mp4", video_codec="copy",
                                      audio_mode="encode", mono=True),
                              info, Path(self.tmp.name) / "out",
                              overwrite=True, gpu_encoders=set())
            for args in plan.passes:
                res = subprocess.run([str(INSTALL.ffmpeg)] + args,
                                     capture_output=True, timeout=120,
                                     creationflags=locate.popen_flags())
                self.assertEqual(res.returncode, 0)
            levels.append(self._rms_db(plan.output))

        left, right = levels
        self.assertGreater(left, -60.0, "left-panned audio vanished")
        self.assertAlmostEqual(left, right, delta=1.0)

    @staticmethod
    def _rms_db(path: Path) -> float:
        res = subprocess.run(
            [str(INSTALL.ffmpeg), "-hide_banner", "-i", str(path),
             "-af", "astats=metadata=1", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60, creationflags=locate.popen_flags())
        values = [float(line.split(":")[1])
                  for line in res.stderr.splitlines()
                  if "RMS level dB:" in line and "-inf" not in line]
        assert values, f"no RMS reading for {path.name}"
        return values[-1]


if __name__ == "__main__":
    unittest.main()
