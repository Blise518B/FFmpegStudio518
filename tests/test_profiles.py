"""Profile round-trip and forward-compat tests (redirects APPDATA to a tmp)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from ffmpeg_studio.spec import JobSpec


class TestSpecSerialization(unittest.TestCase):
    def test_round_trip(self):
        spec = JobSpec(container="webm", video_codec="vp9", crf=31,
                       trim=True, trim_start="0:10", suffix="_w")
        again = JobSpec.from_dict(spec.to_dict())
        self.assertEqual(spec, again)

    def test_unknown_keys_ignored(self):
        data = JobSpec().to_dict()
        data["some_future_option"] = "whatever"
        spec = JobSpec.from_dict(data)
        self.assertEqual(spec, JobSpec())

    def test_missing_keys_default(self):
        spec = JobSpec.from_dict({"container": "mkv"})
        self.assertEqual(spec.container, "mkv")
        self.assertEqual(spec.crf, JobSpec().crf)

    def test_wrong_types_dropped(self):
        spec = JobSpec.from_dict({"crf": "not a number", "container": "mp4"})
        self.assertEqual(spec.crf, JobSpec().crf)

    def test_numeric_strings_coerced(self):
        spec = JobSpec.from_dict({"crf": "28", "target_mb": "9.5"})
        self.assertEqual(spec.crf, 28)
        self.assertEqual(spec.target_mb, 9.5)


class TestDefaultNames(unittest.TestCase):
    def test_names_survive_the_filename_scrub(self):
        """A default whose name has characters Windows forbids would be saved
        under a scrubbed name and then never match the key it was defined
        with — so it must round-trip unchanged."""
        from ffmpeg_studio import profiles as prof
        for name in prof.DEFAULT_PROFILES:
            self.assertEqual(prof._safe_name(name), name,
                             f"default profile name is not filename-safe: "
                             f"{name!r}")

    def test_v1_names_are_a_subset_of_defaults(self):
        from ffmpeg_studio import profiles as prof
        self.assertTrue(prof._V1_NAMES <= set(prof.DEFAULT_PROFILES))

    def test_rgb_normal_still_matches_x264_defaults(self):
        """This one reproduces a shared .bat that relies on x264's own
        defaults, so those values must not drift."""
        from ffmpeg_studio import profiles as prof
        spec = prof.DEFAULT_PROFILES["RGB 4-4-4 master (normal quality)"]
        self.assertEqual(spec.video_codec, "h264rgb")
        self.assertEqual(spec.crf, 23)            # x264's default CRF
        self.assertEqual(spec.preset, "medium")   # x264's default preset
        self.assertEqual(spec.container, "mp4")
        self.assertEqual(spec.audio_mode, "keep")     # -c:a copy
        self.assertEqual(spec.suffix, "")             # same base name
        self.assertFalse(spec.mono or spec.normalize or spec.trim)
        self.assertEqual(spec.scale_mode, "keep")
        self.assertEqual(spec.fps_mode, "keep")

    def test_discord_max_quality_differs_only_in_preset(self):
        """The pair must stay identical apart from the encoder preset (and
        the suffix that keeps their outputs apart), or 'max quality' stops
        being a like-for-like swap."""
        from ffmpeg_studio import profiles as prof
        import dataclasses
        base = prof.DEFAULT_PROFILES["Discord-ready (keep quality)"]
        hq = prof.DEFAULT_PROFILES["Discord-ready (max quality)"]
        differing = {f.name for f in dataclasses.fields(base)
                     if getattr(base, f.name) != getattr(hq, f.name)}
        self.assertEqual(differing, {"preset", "suffix"})
        self.assertEqual(hq.preset, "slower")
        self.assertEqual(base.max_mb, hq.max_mb)

    def test_discord_profiles_have_distinct_suffixes(self):
        from ffmpeg_studio import profiles as prof
        suffixes = [s.suffix for n, s in prof.DEFAULT_PROFILES.items()
                    if n.startswith("Discord-ready")]
        self.assertEqual(len(suffixes), len(set(suffixes)))

    def test_rgb_high_quality_differs_only_in_quality_and_container(self):
        from ffmpeg_studio import profiles as prof
        normal = prof.DEFAULT_PROFILES["RGB 4-4-4 master (normal quality)"]
        hq = prof.DEFAULT_PROFILES["RGB 4-4-4 master (high quality)"]
        self.assertEqual(hq.video_codec, normal.video_codec)
        self.assertEqual(hq.audio_mode, normal.audio_mode)
        self.assertLess(hq.crf, normal.crf)
        self.assertEqual(hq.container, "mkv")


class TestProfileFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ffs_test_")
        self._old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        # profiles module resolves the dir per call, so no reload needed

    def tearDown(self):
        if self._old is not None:
            os.environ["APPDATA"] = self._old
        self._tmp.cleanup()

    def test_save_load_delete(self):
        from ffmpeg_studio import profiles as prof
        spec = JobSpec(container="gif", anim_fps=12)
        prof.save_profile("My GIF: test?", spec)      # illegal chars scrubbed
        names = prof.list_profiles()
        self.assertEqual(len(names), 1)
        loaded = prof.load_profile(names[0])
        self.assertEqual(loaded.container, "gif")
        self.assertEqual(loaded.anim_fps, 12)
        prof.delete_profile(names[0])
        self.assertEqual(prof.list_profiles(), [])

    def test_defaults_written_once(self):
        from ffmpeg_studio import profiles as prof
        prof.ensure_defaults()
        first = prof.list_profiles()
        self.assertGreater(len(first), 5)
        prof.delete_profile(first[0])
        prof.ensure_defaults()                        # must NOT resurrect
        self.assertEqual(len(prof.list_profiles()), len(first) - 1)

    def test_rename_carries_an_untouched_default_over(self):
        """Renaming a shipped default must move the old file, not leave the
        user staring at two near-identical profiles."""
        from ffmpeg_studio import profiles as prof
        old, new = ("RGB 4-4-4 master (original)",
                    "RGB 4-4-4 master (normal quality)")
        prof.save_profile(old, prof.DEFAULT_PROFILES[new])
        prof.ensure_defaults()
        names = prof.list_profiles()
        self.assertIn(new, names)
        self.assertNotIn(old, names)

    def test_rename_leaves_an_edited_profile_alone(self):
        """If they changed it, it's their profile now — don't touch it."""
        from ffmpeg_studio import profiles as prof
        old, new = ("RGB 4-4-4 master (original)",
                    "RGB 4-4-4 master (normal quality)")
        mine = JobSpec(container="mp4", video_codec="h264rgb", crf=5)
        prof.save_profile(old, mine)
        prof.ensure_defaults()
        names = prof.list_profiles()
        self.assertIn(old, names)               # still theirs
        self.assertIn(new, names)               # new default alongside
        self.assertEqual(prof.load_profile(old).crf, 5)

    def test_every_shipped_profile_has_a_tooltip(self):
        from ffmpeg_studio import profiles as prof
        for name, spec in prof.DEFAULT_PROFILES.items():
            self.assertIn(name, prof.PROFILE_NOTES,
                          f"no hover note for {name!r}")
            tip = prof.describe(name, spec)
            self.assertIn(prof.PROFILE_NOTES[name], tip)
            self.assertIn(spec.describe(), tip)

    def test_custom_profile_still_gets_a_description(self):
        from ffmpeg_studio import profiles as prof
        spec = JobSpec(container="webm", video_codec="vp9", crf=31,
                       scale_mode="720", audio_mode="remove")
        prof.save_profile("my own thing", spec)
        tip = prof.describe("my own thing")
        for expected in ("WEBM", "VP9", "CRF 31", "720p", "audio removed"):
            self.assertIn(expected, tip)

    def test_export_import(self):
        from ffmpeg_studio import profiles as prof
        prof.save_profile("exportme", JobSpec(container="mp3"))
        target = Path(self._tmp.name) / "out.json"
        prof.export_profile("exportme", target)
        name = prof.import_profile(target)
        self.assertEqual(name, "out")
        self.assertEqual(prof.load_profile("out").container, "mp3")


if __name__ == "__main__":
    unittest.main()
