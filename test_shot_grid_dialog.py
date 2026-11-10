import os
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from shot_grid import FitStrategy
from shot_grid_dialog import ShotGridDialog
from shot_grid_render import ShotGridMedia
from ui_main import MainWindow


class _ProjectStub:
    def __init__(self):
        self.is_video = True
        self.video_path = os.path.join("C:\\", "clips", "clip.mp4")
        self.folder = os.path.dirname(self.video_path)
        self.sources = []


class _WindowStub:
    def __init__(self):
        self.total_frames = 205
        self.fps = 24
        self.project = _ProjectStub()
        self.bookmarks = []
        self.shot_grid_settings = {}
        self.remembered = []

    def get_loaded_source_name(self):
        return "clip"

    def get_default_export_folder(self):
        return os.getcwd()

    def remember_export_folder(self, path):
        self.remembered.append(path)


class ShotGridDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.media = ShotGridMedia(
            source_name="clip",
            total_frames=205,
            fps=24.0,
            kind="sequence",
            files=tuple(),
        )
        self.bookmarks = [
            {"frame": 0, "name": "Start"},
            {"frame": 10, "name": "Second"},
            {"frame": 75, "name": "Third"},
        ]

    def _dialog(self, **kwargs):
        values = dict(
            media=self.media,
            bookmarks=self.bookmarks,
            settings={},
            default_folder=os.getcwd(),
        )
        values.update(kwargs)
        return ShotGridDialog(**values)

    def test_preview_builds_rows_and_respects_checks(self):
        dialog = self._dialog()
        try:
            self.assertEqual(dialog.table.rowCount(), 3)
            self.assertEqual(dialog.table.item(0, 2).text(), "Start")
            self.assertEqual(dialog.table.item(1, 2).text(), "Second")
            self.assertTrue(dialog.export_button.isEnabled())
            self.assertIn("3 shots", dialog.summary_label.text())

            dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
            self.assertIn("2 shots", dialog.summary_label.text())
            self.assertEqual(
                dialog._collect_options().include_shots,
                frozenset({2, 3}),
            )
        finally:
            dialog.close()

    def test_custom_range_replans_the_table(self):
        dialog = self._dialog()
        try:
            dialog.range_combo.setCurrentIndex(
                dialog.range_combo.findData("custom")
            )
            dialog.range_start_spin.setValue(10)
            dialog.range_end_spin.setValue(74)

            self.assertEqual(dialog.table.rowCount(), 1)
            self.assertEqual(dialog.table.item(0, 2).text(), "Second")
            self.assertIn("1 shot", dialog.summary_label.text())
        finally:
            dialog.close()

    def test_interval_and_layout_options_flow_into_export_options(self):
        dialog = self._dialog(settings={"interval": 8})
        try:
            self.assertEqual(dialog.interval_spin.value(), 8)
            self.assertTrue(dialog.interval_chips[8].isChecked())
            dialog.interval_spin.setValue(4)

            dialog.fit_combo.setCurrentIndex(
                dialog.fit_combo.findData(FitStrategy.TRIM)
            )
            dialog.layout_combo.setCurrentIndex(
                dialog.layout_combo.findData(True)
            )
            options = dialog._collect_options()

            self.assertEqual(options.interval, 4)
            self.assertEqual(options.strategy, FitStrategy.TRIM)
            self.assertTrue(options.rectangular)
            self.assertEqual(options.include_shots, frozenset({1, 2, 3}))
            self.assertGreater(options.grid_side, 0)
        finally:
            dialog.close()

    def test_settings_round_trip(self):
        dialog = self._dialog()
        try:
            dialog.interval_spin.setValue(12)
            dialog.max_grid_combo.setCurrentIndex(
                dialog.max_grid_combo.findData(3)
            )
            dialog.gap_spin.setValue(6)
            dialog.subfolder_check.setChecked(True)
            dialog.format_combo.setCurrentText("JPEG")
            collected = dialog.collect_settings()
        finally:
            dialog.close()

        second = self._dialog(settings=collected)
        try:
            self.assertEqual(second.interval_spin.value(), 12)
            self.assertEqual(second.max_grid_combo.currentData(), 3)
            self.assertEqual(second.gap_spin.value(), 6)
            self.assertTrue(second.subfolder_check.isChecked())
            self.assertEqual(second.format_combo.currentText(), "JPEG")
        finally:
            second.close()

    def test_native_grid_warns_above_100_megapixels(self):
        media = ShotGridMedia(
            source_name="clip",
            total_frames=205,
            fps=24.0,
            kind="sequence",
            files=tuple(),
            width=4000,
            height=4000,
        )
        dialog = self._dialog(media=media)
        try:
            dialog.grid_side_combo.setCurrentIndex(
                dialog.grid_side_combo.findData(None)
            )
            with mock.patch(
                "shot_grid_dialog.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ) as question:
                dialog._on_export_clicked()
            question.assert_called_once()
            self.assertIsNone(dialog.export_options)
        finally:
            dialog.close()

    def test_no_media_disables_export(self):
        dialog = ShotGridDialog(
            media=None,
            bookmarks=self.bookmarks,
            settings={},
            default_folder=os.getcwd(),
            parent=None,
        )
        try:
            self.assertFalse(dialog.export_button.isEnabled())
            self.assertIn("No media", dialog.summary_label.text())
        finally:
            dialog.close()

    def test_bookmark_controls_initial_state(self):
        dialog = self._dialog()
        try:
            self.assertTrue(dialog.start_bookmark_check.isEnabled())
            self.assertTrue(dialog.end_bookmark_check.isEnabled())
            self.assertFalse(dialog.start_bookmark_check.isChecked())
            self.assertFalse(dialog.end_bookmark_check.isChecked())
            self.assertFalse(dialog.start_bookmark_combo.isEnabled())
            self.assertFalse(dialog.end_bookmark_combo.isEnabled())
            self.assertEqual(dialog.start_bookmark_combo.count(), 3)
            self.assertEqual(dialog.end_bookmark_combo.count(), 3)
            self.assertEqual(dialog.start_bookmark_combo.currentIndex(), 0)
            self.assertEqual(dialog.end_bookmark_combo.currentIndex(), 2)
        finally:
            dialog.close()

    def test_select_start_bookmark_filters_preceding(self):
        dialog = self._dialog()
        try:
            # Initially all 3 shots
            self.assertEqual(dialog.table.rowCount(), 3)

            # Toggle start bookmark and choose "Second" (frame 10)
            dialog.start_bookmark_check.setChecked(True)
            self.assertTrue(dialog.start_bookmark_combo.isEnabled())
            dialog.start_bookmark_combo.setCurrentIndex(1)

            # Preceding shot "Start" (frame 0) should be excluded
            self.assertEqual(dialog.table.rowCount(), 2)
            self.assertEqual(dialog.table.item(0, 2).text(), "Second")
            self.assertEqual(dialog.table.item(1, 2).text(), "Third")

            # Toggle off reverts to all bookmarks from start
            dialog.start_bookmark_check.setChecked(False)
            self.assertFalse(dialog.start_bookmark_combo.isEnabled())
            self.assertEqual(dialog.table.rowCount(), 3)
            self.assertEqual(dialog.table.item(0, 2).text(), "Start")
        finally:
            dialog.close()

    def test_select_end_bookmark_filters_subsequent(self):
        dialog = self._dialog()
        try:
            # Initially all 3 shots
            self.assertEqual(dialog.table.rowCount(), 3)

            # Toggle end bookmark and choose "Second" (frame 10, next is frame 75)
            dialog.end_bookmark_check.setChecked(True)
            self.assertTrue(dialog.end_bookmark_combo.isEnabled())
            dialog.end_bookmark_combo.setCurrentIndex(1)

            # "Third" (frame 75) should be excluded; shot "Second" ends at 74
            self.assertEqual(dialog.table.rowCount(), 2)
            self.assertEqual(dialog.table.item(0, 2).text(), "Start")
            self.assertEqual(dialog.table.item(1, 2).text(), "Second")
            self.assertEqual(dialog.table.item(1, 3).text(), "11–75")

            # Toggle off reverts to all bookmarks to clip end
            dialog.end_bookmark_check.setChecked(False)
            self.assertFalse(dialog.end_bookmark_combo.isEnabled())
            self.assertEqual(dialog.table.rowCount(), 3)
            self.assertEqual(dialog.table.item(2, 2).text(), "Third")
        finally:
            dialog.close()

    def test_select_start_and_end_bookmarks_isolates_middle_segment(self):
        four_bookmarks = [
            {"frame": 0, "name": "Lead"},
            {"frame": 20, "name": "Scene A"},
            {"frame": 60, "name": "Scene B"},
            {"frame": 120, "name": "Tail"},
        ]
        dialog = self._dialog(bookmarks=four_bookmarks)
        try:
            self.assertEqual(dialog.table.rowCount(), 4)

            # Select start bookmark = Scene A (index 1, frame 20)
            dialog.start_bookmark_check.setChecked(True)
            dialog.start_bookmark_combo.setCurrentIndex(1)

            # Select end bookmark = Scene B (index 2, frame 60; next is Tail at 120)
            dialog.end_bookmark_check.setChecked(True)
            dialog.end_bookmark_combo.setCurrentIndex(2)

            # Only Scene A and Scene B should be planned
            self.assertEqual(dialog.table.rowCount(), 2)
            self.assertEqual(dialog.table.item(0, 2).text(), "Scene A")
            self.assertEqual(dialog.table.item(0, 3).text(), "21–60")
            self.assertEqual(dialog.table.item(1, 2).text(), "Scene B")
            self.assertEqual(dialog.table.item(1, 3).text(), "61–120")

            options = dialog._collect_options()
            self.assertEqual(options.range_start, 20)
            self.assertEqual(options.range_end, 119)
        finally:
            dialog.close()

    def test_bookmark_combos_auto_adjust_bounds(self):
        dialog = self._dialog()
        try:
            dialog.start_bookmark_check.setChecked(True)
            dialog.end_bookmark_check.setChecked(True)
            dialog.start_bookmark_combo.setCurrentIndex(0)
            dialog.end_bookmark_combo.setCurrentIndex(2)

            # Moving start past end pulls end forward
            dialog.start_bookmark_combo.setCurrentIndex(2)
            self.assertEqual(dialog.end_bookmark_combo.currentIndex(), 2)

            # Moving end before start pulls start backward
            dialog.end_bookmark_combo.setCurrentIndex(0)
            self.assertEqual(dialog.start_bookmark_combo.currentIndex(), 0)
        finally:
            dialog.close()

    def test_settings_round_trip_with_bookmark_selection(self):
        dialog = self._dialog()
        try:
            dialog.start_bookmark_check.setChecked(True)
            dialog.start_bookmark_combo.setCurrentIndex(1)
            dialog.end_bookmark_check.setChecked(True)
            dialog.end_bookmark_combo.setCurrentIndex(2)
            collected = dialog.collect_settings()
            self.assertTrue(collected["start_bookmark_enabled"])
            self.assertEqual(collected["start_bookmark_frame"], 10)
            self.assertTrue(collected["end_bookmark_enabled"])
            self.assertEqual(collected["end_bookmark_frame"], 75)
        finally:
            dialog.close()

        second = self._dialog(settings=collected)
        try:
            self.assertTrue(second.start_bookmark_check.isChecked())
            self.assertEqual(second.start_bookmark_combo.currentData(), 10)
            self.assertTrue(second.end_bookmark_check.isChecked())
            self.assertEqual(second.end_bookmark_combo.currentData(), 75)
            self.assertEqual(second.table.rowCount(), 2)
        finally:
            second.close()

    def test_empty_bookmarks_disables_bookmark_toggles(self):
        dialog = self._dialog(bookmarks=[])
        try:
            self.assertFalse(dialog.start_bookmark_check.isEnabled())
            self.assertFalse(dialog.end_bookmark_check.isEnabled())
            self.assertFalse(dialog.start_bookmark_combo.isEnabled())
            self.assertFalse(dialog.end_bookmark_combo.isEnabled())
        finally:
            dialog.close()


class MainWindowShotGridIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_build_media_for_video(self):
        window = _WindowStub()
        media = MainWindow.build_shot_grid_media(window)
        self.assertIsNotNone(media)
        self.assertEqual(media.kind, "video")
        self.assertEqual(media.path, window.project.video_path)
        self.assertEqual(media.total_frames, 205)

    def test_build_media_for_gif(self):
        window = _WindowStub()
        window.project.video_path = os.path.join("C:\\", "clips", "clip.gif")
        media = MainWindow.build_shot_grid_media(window)
        self.assertEqual(media.kind, "gif")

    def test_build_media_falls_back_to_sequence_scan(self):
        window = _WindowStub()
        window.project.is_video = False
        files = ("a.png", "b.png")
        with mock.patch(
            "viewer.detect_sequence",
            return_value=[{"files": list(files)}],
        ):
            media = MainWindow.build_shot_grid_media(window)
        self.assertEqual(media.kind, "sequence")
        self.assertEqual(media.files, files)

    def test_main_window_menu_action_is_disabled_without_media(self):
        window = MainWindow()
        try:
            self.assertEqual(
                window.export_shot_grids_action.text(), "Shot Grids..."
            )
            self.assertFalse(window.export_shot_grids_action.isEnabled())
        finally:
            window.close()

    def test_show_dialog_exports_and_remembers_folder(self):
        window = _WindowStub()
        window.build_shot_grid_media = types.MethodType(
            MainWindow.build_shot_grid_media, window
        )

        class _Options:
            output_folder = os.path.join(os.getcwd(), "out")

        class _Result:
            image_count = 2

        class _Dialog:
            def __init__(self, *args, **kwargs):
                self.export_options = _Options()

            def exec(self):
                return QDialog.DialogCode.Accepted

        with mock.patch("ui_main.ShotGridDialog", _Dialog), mock.patch(
            "ui_main.show_shot_grid_export", return_value=_Result()
        ) as export:
            MainWindow.show_shot_grid_dialog(window)

        export.assert_called_once()
        self.assertEqual(window.remembered, [_Options.output_folder])


if __name__ == "__main__":
    unittest.main()
