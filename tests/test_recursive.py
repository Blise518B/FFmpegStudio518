"""Sub-folder handling: output mirroring and the output-inside-input trap."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from ffmpeg_studio.ui.main_window import MainWindow

_app = None


def setUpModule() -> None:
    """FilesPanel is a QWidget, so it needs a QApplication to exist."""
    global _app
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])


class TestTargetDir(unittest.TestCase):
    """_target_dir mirrors the source tree instead of flattening it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ffs_rec_")
        self.root = Path(self._tmp.name)
        self.out = self.root / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def test_top_level_file_lands_in_output_root(self):
        src = self.root / "in" / "clip.mp4"
        got = MainWindow._target_dir(self.out, self.root / "in", src)
        self.assertEqual(got, self.out)
        self.assertTrue(got.is_dir())

    def test_nested_file_keeps_its_subfolder(self):
        in_root = self.root / "in"
        src = in_root / "2026" / "vrc" / "clip.mp4"
        got = MainWindow._target_dir(self.out, in_root, src)
        self.assertEqual(got, self.out / "2026" / "vrc")
        self.assertTrue(got.is_dir())

    def test_same_name_in_two_folders_does_not_collide(self):
        in_root = self.root / "in"
        a = MainWindow._target_dir(self.out, in_root, in_root / "a" / "x.mp4")
        b = MainWindow._target_dir(self.out, in_root, in_root / "b" / "x.mp4")
        self.assertNotEqual(a, b)

    def test_file_outside_input_root_falls_back_to_root(self):
        got = MainWindow._target_dir(self.out, self.root / "in",
                                     Path(r"D:\elsewhere\clip.mp4"))
        self.assertEqual(got, self.out)


class TestScanExclusion(unittest.TestCase):
    """The output folder usually sits inside the input one; a recursive scan
    must not pick up its own results (the friend's script does)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ffs_scan_")
        self.root = Path(self._tmp.name)
        (self.root / "sub").mkdir()
        (self.root / "output").mkdir()
        for rel in ("a.mp4", "sub/b.mp4", "output/a_done.mp4"):
            (self.root / rel).write_bytes(b"\x00")

    def tearDown(self):
        self._tmp.cleanup()

    def _panel(self, recurse: bool, exclude: str):
        from ffmpeg_studio.ui.files_panel import FilesPanel
        panel = FilesPanel()
        panel._folder = self.root
        panel.set_exclude(exclude)
        panel.recurse.setChecked(recurse)
        return panel

    def test_flat_scan_ignores_subfolders(self):
        names = [p.name for p in self._panel(False, "")._scan()]
        self.assertEqual(names, ["a.mp4"])

    def test_recursive_scan_finds_nested(self):
        panel = self._panel(True, str(self.root / "output"))
        names = sorted(p.name for p in panel._scan())
        self.assertEqual(names, ["a.mp4", "b.mp4"])

    def test_recursive_scan_excludes_output_folder(self):
        panel = self._panel(True, str(self.root / "output"))
        self.assertNotIn("a_done.mp4", [p.name for p in panel._scan()])

    def test_without_exclusion_outputs_would_be_picked_up(self):
        # documents exactly the bug the exclusion prevents
        panel = self._panel(True, "")
        self.assertIn("a_done.mp4", [p.name for p in panel._scan()])

    def test_display_name_shows_subpath(self):
        panel = self._panel(True, str(self.root / "output"))
        nested = self.root / "sub" / "b.mp4"
        self.assertEqual(panel.display_name(nested), str(Path("sub/b.mp4")))


class TestCheckStateOnRefresh(unittest.TestCase):
    """Refresh keeps the user's ticks, but files that only just appeared —
    including everything revealed by switching Subfolders on — start ticked,
    otherwise enabling it looks like it silently did nothing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ffs_chk_")
        self.root = Path(self._tmp.name)
        (self.root / "sub").mkdir()
        (self.root / "a.mp4").write_bytes(b"\x00")
        (self.root / "sub" / "b.mp4").write_bytes(b"\x00")

        from ffmpeg_studio.ui.files_panel import FilesPanel
        self.panel = FilesPanel()
        self.panel.set_context(str(self.root), None)

    def tearDown(self):
        self._tmp.cleanup()

    def _checked(self) -> set[str]:
        return {p.name for p in self.panel.checked_files()}

    def test_enabling_subfolders_ticks_the_new_files(self):
        self.assertEqual(self._checked(), {"a.mp4"})
        self.panel.recurse.setChecked(True)
        self.assertEqual(self._checked(), {"a.mp4", "b.mp4"})

    def test_manual_unticks_survive_a_refresh(self):
        self.panel.recurse.setChecked(True)
        for item in self.panel._items():
            if item.text(0).endswith("b.mp4"):
                item.setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual(self._checked(), {"a.mp4"})
        self.panel.refresh()
        self.assertEqual(self._checked(), {"a.mp4"})

    def test_brand_new_file_on_disk_is_ticked(self):
        for item in self.panel._items():
            item.setCheckState(0, Qt.CheckState.Unchecked)
        (self.root / "c.mp4").write_bytes(b"\x00")
        self.panel.refresh()
        self.assertEqual(self._checked(), {"c.mp4"})


if __name__ == "__main__":
    unittest.main()
