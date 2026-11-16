import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from app_utils import build_bookmark_data_export_filename
from bookmark_io import (
    BOOKMARK_EXPORT_SCHEMA_ID,
    CollisionPolicy,
    OutOfRangePolicy,
    PositionMode,
    StartAnchorMode,
    export_bookmarks_csv,
    export_bookmarks_file,
    export_bookmarks_json,
    frame_to_timecode,
    load_bookmarks_file,
    parse_timestamp_to_seconds,
    plan_bookmark_import,
    recommend_position_mode,
)
from ui_main import ExportBookmarksDialog, ImportBookmarksDialog, MainWindow


class _MockImportParent(QWidget):
    def __init__(self, total_frames=120, fps=30.0, bookmarks=None, current_frame=0):
        super().__init__()
        self.total_frames = total_frames
        self._fps = fps
        self.bookmarks = list(bookmarks or [])
        self.current_frame = current_frame

    def get_effective_fps(self):
        return self._fps

    def get_loaded_source_name(self):
        return "clip_b"

    def get_default_export_folder(self):
        return os.getcwd()

    def get_export_fps(self):
        return int(self._fps)


class BookmarkIoUnitTests(unittest.TestCase):
    def test_parse_timestamp_to_seconds_supports_multiple_formats(self):
        self.assertAlmostEqual(parse_timestamp_to_seconds("00:01:02.500"), 62.5)
        self.assertAlmostEqual(parse_timestamp_to_seconds("00:01:02,250"), 62.25)
        self.assertAlmostEqual(parse_timestamp_to_seconds("02:15.5"), 135.5)
        self.assertAlmostEqual(parse_timestamp_to_seconds("12.75"), 12.75)
        self.assertAlmostEqual(parse_timestamp_to_seconds(8.5), 8.5)
        self.assertAlmostEqual(
            parse_timestamp_to_seconds("00:00:02:12", fallback_fps=24.0), 2.5
        )
        self.assertIsNone(parse_timestamp_to_seconds(""))
        self.assertIsNone(parse_timestamp_to_seconds("-1.0"))
        self.assertIsNone(parse_timestamp_to_seconds("not-a-timestamp"))

    def test_frame_to_timecode_formats_smpte(self):
        self.assertEqual(frame_to_timecode(0, 24.0), "00:00:00:00")
        self.assertEqual(frame_to_timecode(48, 24.0), "00:00:02:00")
        self.assertEqual(frame_to_timecode(36, 24.0), "00:00:01:12")

    def test_build_bookmark_data_export_filename(self):
        self.assertEqual(
            build_bookmark_data_export_filename("my:clip", ".csv"),
            "my_clip_bookmarks.csv",
        )

    def test_json_export_and_load_roundtrip(self):
        bookmarks = [
            {"frame": 48, "name": "Cut B", "color": "#00a8ff"},
            {"frame": 12, "name": "Cut A", "color": "#ff6b35"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "marks.json")
            export_bookmarks_json(
                path,
                bookmarks,
                fps=24.0,
                source_name="shot_01",
                total_frames=200,
            )

            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)

            self.assertEqual(raw["format"], BOOKMARK_EXPORT_SCHEMA_ID)
            self.assertEqual(raw["source_name"], "shot_01")
            self.assertEqual(raw["fps"], 24.0)
            self.assertEqual(raw["total_frames"], 200)
            self.assertEqual([b["frame"] for b in raw["bookmarks"]], [12, 48])
            self.assertEqual([b["frame_1based"] for b in raw["bookmarks"]], [13, 49])
            self.assertEqual(raw["bookmarks"][0]["timestamp"], "00:00:00.500")
            self.assertEqual(raw["bookmarks"][1]["timestamp"], "00:00:02.000")

            doc = load_bookmarks_file(path)
            self.assertEqual(doc.detected_format, "json")
            self.assertEqual(doc.source_fps, 24.0)
            self.assertEqual(len(doc.bookmarks), 2)
            self.assertEqual(doc.bookmarks[0].name, "Cut A")
            self.assertAlmostEqual(doc.bookmarks[1].seconds, 2.0)

    def test_csv_export_and_load_roundtrip(self):
        bookmarks = [
            {"frame": 24, "name": 'Beat, "Hero"', "color": "#ff6b35"},
            {"frame": 72, "name": "End Pose", "color": "#4ec9b0"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "marks.csv")
            export_bookmarks_csv(path, bookmarks, fps=24.0)

            doc = load_bookmarks_file(path)
            self.assertEqual(doc.detected_format, "csv")
            self.assertEqual(doc.source_fps, 24.0)
            self.assertEqual(len(doc.bookmarks), 2)
            self.assertEqual(doc.bookmarks[0].frame, 24)
            self.assertEqual(doc.bookmarks[0].name, 'Beat, "Hero"')
            self.assertEqual(doc.bookmarks[0].timestamp, "00:00:01.000")
            self.assertEqual(doc.bookmarks[1].frame, 72)
            self.assertEqual(doc.bookmarks[1].color, "#4ec9b0")

    def test_load_csv_with_only_1based_frames_or_timestamps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_1based = os.path.join(tmpdir, "one_based.csv")
            with open(csv_1based, "w", encoding="utf-8-sig") as handle:
                handle.write("frame_1based,name\n1,Start\n25,Action\n")
            doc1 = load_bookmarks_file(csv_1based)
            self.assertEqual([b.frame for b in doc1.bookmarks], [0, 24])

            csv_ts = os.path.join(tmpdir, "timestamps_only.csv")
            with open(csv_ts, "w", encoding="utf-8") as handle:
                handle.write("timestamp,name\n00:00:01.500,Mid\n00:00:03.000,End\n")
            doc2 = load_bookmarks_file(csv_ts)
            self.assertEqual([b.frame for b in doc2.bookmarks], [None, None])
            self.assertEqual(
                recommend_position_mode(doc2, target_fps=30.0),
                PositionMode.TIMESTAMP,
            )
            plan = plan_bookmark_import(
                doc2,
                existing_bookmarks=[],
                target_total_frames=150,
                target_fps=30.0,
                position_mode=PositionMode.TIMESTAMP,
            )
            self.assertEqual([b["frame"] for b in plan.final_bookmarks], [45, 90])

    def test_load_kfp_basic_and_gemma_shots_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kfp_path = os.path.join(tmpdir, "old_clip.kfp_basic")
            with open(kfp_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "version": "1.0",
                        "sources": [{"path": "old", "absolute": "old", "start": 0, "end": 99}],
                        "timeline": {"current": 0},
                        "bookmarks": [
                            {"frame": 10, "name": "Key 1", "color": "#ff6b35"}
                        ],
                        "settings": {"fps": 24},
                    },
                    handle,
                )
            kfp_doc = load_bookmarks_file(kfp_path)
            self.assertEqual(kfp_doc.detected_format, "kfp_basic")
            self.assertEqual(kfp_doc.source_fps, 24.0)
            self.assertEqual(kfp_doc.bookmarks[0].frame, 10)

            gemma_path = os.path.join(tmpdir, "clip_gemma_shots.json")
            with open(gemma_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "source_name": "clip",
                        "fps": 24,
                        "shots": [
                            {
                                "index": 1,
                                "start_frame": 0,
                                "start_seconds": 0.0,
                                "start_timestamp": "00:00:00.000",
                                "description": "Wide shot",
                            },
                            {
                                "index": 2,
                                "start_frame": 48,
                                "start_seconds": 2.0,
                                "start_timestamp": "00:00:02.000",
                                "description": "Close up",
                            },
                        ],
                    },
                    handle,
                )
            gemma_doc = load_bookmarks_file(gemma_path)
            self.assertEqual(gemma_doc.detected_format, "gemma_shots")
            self.assertEqual([b.frame for b in gemma_doc.bookmarks], [0, 48])
            self.assertEqual(gemma_doc.bookmarks[1].name, "Close up")

    def test_cross_fps_timestamp_mapping_and_policies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "source_24fps.json")
            export_bookmarks_file(
                path,
                [
                    {"frame": 24, "name": "One Sec", "color": "#ff6b35"},
                    {"frame": 48, "name": "Two Sec", "color": "#00a8ff"},
                    {"frame": 120, "name": "Five Sec", "color": "#ff6b35"},
                ],
                fps=24.0,
                source_name="clip_24",
                total_frames=200,
            )
            doc = load_bookmarks_file(path)

            # Target clip is 30fps, 100 frames (frames 0..99).
            # 1s -> 30, 2s -> 60, 5s -> 150 (out of range).
            self.assertEqual(
                recommend_position_mode(doc, target_fps=30.0),
                PositionMode.TIMESTAMP,
            )

            existing = [{"frame": 30, "name": "Existing 30", "color": "#ffffff", "annotations": ["keep"]}]

            # Keep existing + Skip out-of-range
            plan_keep = plan_bookmark_import(
                doc,
                existing_bookmarks=existing,
                target_total_frames=100,
                target_fps=30.0,
                position_mode=PositionMode.TIMESTAMP,
                out_of_range=OutOfRangePolicy.SKIP,
                collision_policy=CollisionPolicy.KEEP_EXISTING,
            )
            self.assertEqual(plan_keep.imported_count, 1)
            self.assertEqual(plan_keep.skipped_count, 2)
            self.assertEqual(
                [(b["frame"], b["name"]) for b in plan_keep.final_bookmarks],
                [(30, "Existing 30"), (60, "Two Sec")],
            )
            self.assertEqual(plan_keep.final_bookmarks[0]["annotations"], ["keep"])

            # Overwrite + Clamp out-of-range
            plan_overwrite = plan_bookmark_import(
                doc,
                existing_bookmarks=existing,
                target_total_frames=100,
                target_fps=30.0,
                position_mode=PositionMode.TIMESTAMP,
                out_of_range=OutOfRangePolicy.CLAMP,
                collision_policy=CollisionPolicy.OVERWRITE,
            )
            self.assertEqual(plan_overwrite.overwritten_count, 1)
            self.assertEqual(plan_overwrite.imported_count, 2)
            self.assertEqual(plan_overwrite.clamped_count, 1)
            self.assertEqual(
                [(b["frame"], b["name"]) for b in plan_overwrite.final_bookmarks],
                [(30, "One Sec"), (60, "Two Sec"), (99, "Five Sec")],
            )

            # Replace all
            plan_replace = plan_bookmark_import(
                doc,
                existing_bookmarks=[{"frame": 5, "name": "Old", "color": "#ff6b35"}],
                target_total_frames=100,
                target_fps=30.0,
                position_mode=PositionMode.FRAME,
                out_of_range=OutOfRangePolicy.SKIP,
                collision_policy=CollisionPolicy.REPLACE_ALL,
            )
            self.assertEqual(
                [(b["frame"], b["name"]) for b in plan_replace.final_bookmarks],
                [(24, "One Sec"), (48, "Two Sec")],
            )

    def test_invalid_files_raise_clear_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_json = os.path.join(tmpdir, "bad.json")
            with open(bad_json, "w", encoding="utf-8") as handle:
                handle.write("{not valid json")
            with self.assertRaises(ValueError):
                load_bookmarks_file(bad_json)

            empty_csv = os.path.join(tmpdir, "empty.csv")
            with open(empty_csv, "w", encoding="utf-8") as handle:
                handle.write("")
            with self.assertRaises(ValueError):
                load_bookmarks_file(empty_csv)

    def test_fractional_fps_roundtrip_and_intra_import_duplicates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 60fps frames 60 (1.000s) and 61 (1.016667s) both round to frame 24 at 24fps
            path_60 = os.path.join(tmpdir, "high_fps.csv")
            export_bookmarks_csv(
                path_60,
                [
                    {"frame": 60, "name": "First", "color": "#ff6b35"},
                    {"frame": 61, "name": "Second", "color": "#00a8ff"},
                ],
                fps=60.0,
            )
            doc_60 = load_bookmarks_file(path_60)
            plan = plan_bookmark_import(
                doc_60,
                existing_bookmarks=[],
                target_total_frames=100,
                target_fps=24.0,
                position_mode=PositionMode.TIMESTAMP,
            )
            self.assertEqual(plan.imported_count, 1)
            self.assertEqual(plan.skipped_count, 1)
            self.assertEqual(plan.items[1].status, "skip_duplicate")
            self.assertEqual(plan.final_bookmarks, [{"frame": 24, "name": "First", "color": "#ff6b35"}])

            # Fractional 23.976 -> 59.94 preserves 2.5x frame index accurately
            path_23976 = os.path.join(tmpdir, "ntsc.json")
            export_bookmarks_json(
                path_23976,
                [{"frame": 24, "name": "Sec One", "color": "#ff6b35"}],
                fps=24000 / 1001,
            )
            doc_ntsc = load_bookmarks_file(path_23976)
            plan_ntsc = plan_bookmark_import(
                doc_ntsc,
                existing_bookmarks=[],
                target_total_frames=200,
                target_fps=60000 / 1001,
                position_mode=PositionMode.TIMESTAMP,
            )
            self.assertEqual(plan_ntsc.final_bookmarks[0]["frame"], 60)

    def test_clamp_collision_respects_keep_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "long.json")
            export_bookmarks_json(
                path,
                [{"frame": 200, "name": "Tail", "color": "#ff6b35"}],
                fps=24.0,
            )
            doc = load_bookmarks_file(path)
            plan = plan_bookmark_import(
                doc,
                existing_bookmarks=[{"frame": 49, "name": "Keep End", "color": "#00a8ff"}],
                target_total_frames=50,
                target_fps=24.0,
                position_mode=PositionMode.FRAME,
                out_of_range=OutOfRangePolicy.CLAMP,
                collision_policy=CollisionPolicy.KEEP_EXISTING,
            )
            self.assertEqual(plan.imported_count, 0)
            self.assertEqual(plan.skipped_count, 1)
            self.assertEqual(plan.items[0].status, "skip_existing")
            self.assertEqual(plan.final_bookmarks[0]["name"], "Keep End")

    def test_start_frame_anchor_modes_frame_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Unsorted rows starting at frame 24 (1.0s at 24fps)
            csv_path = os.path.join(tmpdir, "shifted.csv")
            with open(csv_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "frame,timestamp,seconds,fps,name\n"
                    "48,00:00:02.000,2.0,24,Second\n"
                    "24,00:00:01.000,1.0,24,First\n"
                    "72,00:00:03.000,3.0,24,Third\n"
                )
            doc = load_bookmarks_file(csv_path)

            # Frame mode, FIRST_BOOKMARK at 100 -> [100, 124, 148]
            plan_first_frame = plan_bookmark_import(
                doc,
                existing_bookmarks=[],
                target_total_frames=250,
                target_fps=24.0,
                position_mode=PositionMode.FRAME,
                start_frame=100,
                start_anchor=StartAnchorMode.FIRST_BOOKMARK,
            )
            self.assertEqual(
                [(b["frame"], b["name"]) for b in plan_first_frame.final_bookmarks],
                [(100, "First"), (124, "Second"), (148, "Third")],
            )

            # Frame mode, CLIP_START at 100 -> [124, 148, 172]
            plan_clip_frame = plan_bookmark_import(
                doc,
                existing_bookmarks=[],
                target_total_frames=250,
                target_fps=24.0,
                position_mode=PositionMode.FRAME,
                start_frame=100,
                start_anchor=StartAnchorMode.CLIP_START,
            )
            self.assertEqual(
                [(b["frame"], b["name"]) for b in plan_clip_frame.final_bookmarks],
                [(124, "First"), (148, "Second"), (172, "Third")],
            )

            # Timestamp mode 24fps -> 30fps, FIRST_BOOKMARK at 50 -> [50, 80, 110]
            plan_first_ts = plan_bookmark_import(
                doc,
                existing_bookmarks=[],
                target_total_frames=250,
                target_fps=30.0,
                position_mode=PositionMode.TIMESTAMP,
                start_frame=50,
                start_anchor=StartAnchorMode.FIRST_BOOKMARK,
            )
            self.assertEqual(
                [b["frame"] for b in plan_first_ts.final_bookmarks],
                [50, 80, 110],
            )

            # Timestamp mode 24fps -> 30fps, CLIP_START at 50 -> [80, 110, 140]
            plan_clip_ts = plan_bookmark_import(
                doc,
                existing_bookmarks=[],
                target_total_frames=250,
                target_fps=30.0,
                position_mode=PositionMode.TIMESTAMP,
                start_frame=50,
                start_anchor=StartAnchorMode.CLIP_START,
            )
            self.assertEqual(
                [b["frame"] for b in plan_clip_ts.final_bookmarks],
                [80, 110, 140],
            )

            # Shifting beyond target clip end respects SKIP policy
            plan_trimmed = plan_bookmark_import(
                doc,
                existing_bookmarks=[],
                target_total_frames=130,
                target_fps=24.0,
                position_mode=PositionMode.FRAME,
                out_of_range=OutOfRangePolicy.SKIP,
                start_frame=100,
                start_anchor=StartAnchorMode.FIRST_BOOKMARK,
            )
            self.assertEqual(
                [b["frame"] for b in plan_trimmed.final_bookmarks], [100, 124]
            )
            self.assertEqual(plan_trimmed.skipped_count, 1)


class BookmarkIoUiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = MainWindow()
        self.win.total_frames = 120
        self.win.fps = 24
        self.win.timeline.set_total_frames(120)
        self.win.overview_timeline.set_total_frames(120)
        self.win.current_frame = 0

    def tearDown(self):
        self.win.close()

    def test_bookmark_panel_buttons_and_export_enable_state(self):
        win = self.win
        self.assertEqual(win.import_bookmarks_btn.width(), 28)
        self.assertEqual(win.export_bookmark_data_btn.width(), 28)
        self.assertTrue(win.import_bookmarks_btn.isEnabled())
        self.assertFalse(win.export_bookmark_data_btn.isEnabled())

        win.seek_to_frame(10)
        win.add_bookmark()
        self.assertTrue(win.export_bookmark_data_btn.isEnabled())

        win.remove_current_bookmark()
        self.assertFalse(win.export_bookmark_data_btn.isEnabled())

    def test_export_bookmarks_dialog_supports_json_and_csv_modes(self):
        parent = _MockImportParent(
            total_frames=100,
            fps=24.0,
            bookmarks=[{"frame": 0, "name": "Start"}],
        )
        dialog = ExportBookmarksDialog(parent)

        self.assertEqual(dialog.mode_combo.currentData(), "images")
        self.assertFalse(dialog.is_data_mode())

        json_idx = dialog.mode_combo.findData("json")
        self.assertGreaterEqual(json_idx, 0)
        dialog.mode_combo.setCurrentIndex(json_idx)
        self.assertTrue(dialog.is_data_mode())
        self.assertEqual(dialog.get_data_format(), "json")
        self.assertTrue(dialog.output_path.isEnabled())
        self.assertTrue(dialog.output_path.text().endswith(".json"))
        self.assertFalse(dialog.output_folder.isEnabled())
        self.assertFalse(dialog.hold_spinbox.isEnabled())

        csv_idx = dialog.mode_combo.findData("csv")
        self.assertGreaterEqual(csv_idx, 0)
        dialog.mode_combo.setCurrentIndex(csv_idx)
        self.assertEqual(dialog.get_data_format(), "csv")
        self.assertTrue(dialog.output_path.text().endswith(".csv"))

        dialog.close()
        parent.close()

    def test_import_bookmarks_dialog_live_replan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "clip_a.json")
            export_bookmarks_json(
                json_path,
                [
                    {"frame": 24, "name": "Beat 1", "color": "#ff6b35"},
                    {"frame": 48, "name": "Beat 2", "color": "#00a8ff"},
                ],
                fps=24.0,
                source_name="clip_a",
                total_frames=100,
            )

            parent = _MockImportParent(
                total_frames=120,
                fps=30.0,
                bookmarks=[{"frame": 30, "name": "Existing", "color": "#ff6b35"}],
            )
            dialog = ImportBookmarksDialog(parent, json_path)

            # Should recommend TIMESTAMP because 24fps != 30fps
            self.assertEqual(
                dialog.position_mode_combo.currentData(), PositionMode.TIMESTAMP
            )
            self.assertEqual(dialog.preview_table.rowCount(), 2)
            # Frame 30 collides with Existing, Frame 60 imports
            self.assertEqual(dialog.plan.imported_count, 1)
            self.assertEqual(dialog.plan.skipped_count, 1)

            # Switch collision policy to OVERWRITE
            ow_idx = dialog.collision_combo.findData(CollisionPolicy.OVERWRITE)
            dialog.collision_combo.setCurrentIndex(ow_idx)
            self.assertEqual(dialog.plan.overwritten_count, 1)
            self.assertEqual(dialog.plan.imported_count, 1)

            dialog.close()
            parent.close()

    def test_mainwindow_cross_clip_export_and_import_roundtrip(self):
        win = self.win
        win.seek_to_frame(24)
        win.add_bookmark()
        win.seek_to_frame(48)
        win.add_bookmark()

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "clip_a_bookmarks.csv")
            with patch("ui_main.QMessageBox.information"):
                win.export_bookmarks_data(csv_path, format_name="csv")

            self.assertTrue(os.path.exists(csv_path))

            # Simulate switching to a different 30fps clip with 150 frames
            win.reset_loaded_media_state(clear_bookmarks=True)
            win.total_frames = 150
            win.fps = 30
            win.timeline.set_total_frames(150)
            win.overview_timeline.set_total_frames(150)

            plan = win.import_bookmarks_from_file(csv_path)
            self.assertEqual(plan.imported_count, 2)
            self.assertEqual([b["frame"] for b in win.bookmarks], [30, 60])
            self.assertEqual(win.timeline.bookmarks, {30, 60})
            self.assertEqual(win.overview_timeline.bookmarks, {30, 60})
            self.assertEqual(win.bookmark_list.count(), 2)
            self.assertTrue(win.export_bookmark_data_btn.isEnabled())

    def test_mainwindow_effective_fps_and_dialog_guards(self):
        win = self.win
        win.project.is_video = True
        win.project.video_fps = 23.976
        win.fps = 23
        self.assertAlmostEqual(win.get_effective_fps(), 23.976)

        win.project.video_fps = 0
        self.assertEqual(win.get_effective_fps(), 23.0)

        with patch("ui_main.QMessageBox.warning") as warn_mock:
            win.show_export_bookmark_data_dialog()
            warn_mock.assert_called_once()

        win.total_frames = 0
        with patch("ui_main.QMessageBox.warning") as warn_mock:
            win.show_import_bookmarks_dialog()
            warn_mock.assert_called_once()

    def test_mainwindow_show_export_and_import_dialogs_flow(self):
        win = self.win
        win.seek_to_frame(12)
        win.add_bookmark()

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "exported.json")
            with patch(
                "ui_main.QFileDialog.getSaveFileName",
                return_value=(json_path, "JSON Files (*.json)"),
            ), patch("ui_main.QMessageBox.information"):
                win.show_export_bookmark_data_dialog()

            self.assertTrue(os.path.exists(json_path))

            # Clear and import onto a 48fps clip via dialog flow
            win.reset_loaded_media_state(clear_bookmarks=True)
            win.total_frames = 240
            win.fps = 48
            win.timeline.set_total_frames(240)
            win.overview_timeline.set_total_frames(240)

            with patch(
                "ui_main.QFileDialog.getOpenFileName",
                return_value=(json_path, "Bookmark Files (*.json *.csv *.kfp_basic)"),
            ), patch.object(
                ImportBookmarksDialog,
                "exec",
                return_value=ImportBookmarksDialog.DialogCode.Accepted,
            ), patch("ui_main.QMessageBox.information"):
                win.show_import_bookmarks_dialog()

            self.assertEqual([b["frame"] for b in win.bookmarks], [24])

    def test_import_dialog_start_frame_controls_and_mainwindow_shift(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "clip_a.json")
            export_bookmarks_json(
                json_path,
                [
                    {"frame": 20, "name": "Cue A", "color": "#ff6b35"},
                    {"frame": 40, "name": "Cue B", "color": "#00a8ff"},
                ],
                fps=24.0,
                source_name="clip_a",
                total_frames=100,
            )

            parent = _MockImportParent(
                total_frames=200,
                fps=24.0,
                current_frame=99,  # 1-based Frame 100
            )
            dialog = ImportBookmarksDialog(parent, json_path)

            self.assertEqual(
                dialog.start_anchor_combo.currentData(), StartAnchorMode.ORIGINAL
            )
            self.assertFalse(dialog.start_frame_spin.isEnabled())
            self.assertEqual(dialog.start_frame_spin.value(), 100)
            self.assertEqual(
                [b["frame"] for b in dialog.plan.final_bookmarks], [20, 40]
            )

            # Clicking "Current (100)" enables FIRST_BOOKMARK at 0-based frame 99
            dialog.use_current_frame_btn.click()
            self.assertEqual(
                dialog.start_anchor_combo.currentData(), StartAnchorMode.FIRST_BOOKMARK
            )
            self.assertTrue(dialog.start_frame_spin.isEnabled())
            self.assertEqual(
                [b["frame"] for b in dialog.plan.final_bookmarks], [99, 119]
            )
            self.assertTrue(
                dialog.preview_table.item(0, 3).text().startswith("Frame 100")
            )

            # Adjusting start_frame_spin replans live (1-based 51 -> 0-based 50)
            dialog.start_frame_spin.setValue(51)
            self.assertEqual(
                [b["frame"] for b in dialog.plan.final_bookmarks], [50, 70]
            )

            # Switching to CLIP_START shifts frame 0 to 50 -> [70, 90]
            clip_idx = dialog.start_anchor_combo.findData(StartAnchorMode.CLIP_START)
            dialog.start_anchor_combo.setCurrentIndex(clip_idx)
            self.assertEqual(
                [b["frame"] for b in dialog.plan.final_bookmarks], [70, 90]
            )

            dialog.close()
            parent.close()

            # End-to-end on MainWindow with start_frame
            win = self.win
            win.total_frames = 200
            win.fps = 24
            win.timeline.set_total_frames(200)
            win.overview_timeline.set_total_frames(200)
            plan = win.import_bookmarks_from_file(
                json_path,
                start_frame=100,
                start_anchor=StartAnchorMode.FIRST_BOOKMARK,
            )
            self.assertEqual(plan.imported_count, 2)
            self.assertEqual([b["frame"] for b in win.bookmarks], [100, 120])
            self.assertEqual(win.timeline.bookmarks, {100, 120})
            self.assertEqual(win.overview_timeline.bookmarks, {100, 120})


if __name__ == "__main__":
    unittest.main()
