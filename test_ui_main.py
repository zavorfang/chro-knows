import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from unittest.mock import MagicMock, patch
from PyQt6.QtGui import QPixmap, QColor
from ui_main import ExportBookmarksDialog, GemmaShotDetectionDialog, MainWindow
from timeline import TimelineWidget


class _BookmarkDialogParent(QWidget):
    def __init__(self):
        super().__init__()
        self.bookmarks = [{"frame": 0, "name": "Start"}]
        self.total_frames = 100

    def get_default_export_folder(self):
        return os.getcwd()

    def get_loaded_source_name(self):
        return "shot_001"

    def get_export_fps(self):
        return 24

    def get_configured_google_api_key(self):
        return ""

    def is_dummy_google_api_key(self, key):
        return key in MainWindow.DUMMY_API_KEYS


class ExportBookmarksDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_initializes_and_toggles_modes(self):
        parent = _BookmarkDialogParent()
        dialog = ExportBookmarksDialog(parent)

        self.assertTrue(hasattr(dialog, "browse_output_folder_btn"))
        self.assertEqual(dialog.mode_combo.currentData(), "images")
        self.assertTrue(dialog.output_folder.isEnabled())
        self.assertFalse(dialog.output_path.isEnabled())

        dialog.mode_combo.setCurrentIndex(1)

        self.assertEqual(dialog.mode_combo.currentData(), "video")
        self.assertFalse(dialog.output_folder.isEnabled())
        self.assertTrue(dialog.output_path.isEnabled())

        dialog.close()
        parent.close()

    def test_gemma_shot_detection_dialog_model_fallback(self):
        models, is_live = GemmaShotDetectionDialog.fetch_gemini_models("")
        self.assertFalse(is_live)
        self.assertEqual(len(models), 10)
        self.assertEqual(models[0][1], "gemini-2.5-flash")

    def test_gemma_shot_detection_dialog_mock_live_fetch(self):
        class MockModel:
            def __init__(self, name, display_name="", supported_actions=None):
                self.name = name
                self.display_name = display_name
                self.supported_actions = supported_actions or ["generateContent"]

        mock_models = [
            MockModel("models/gemini-3.0-flash-preview", "Gemini 3.0 Flash Preview"),
            MockModel("models/gemini-2.5-flash", "Gemini 2.5 Flash"),
            MockModel("models/gemini-2.5-flash-001", "Gemini 2.5 Flash 001"),
            MockModel("models/gemini-1.5-pro", "Gemini 1.5 Pro"),
            MockModel("models/text-embedding-004", "Embedding", supported_actions=["embedContent"]),
            MockModel("models/imagen-3.0", "Imagen", supported_actions=["generateImages"]),
            MockModel("models/gemma-2-27b-it", "Gemma 2 27B"),
        ]

        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.models.list.return_value = mock_models
            mock_client_cls.return_value = mock_client

            models, is_live = GemmaShotDetectionDialog.fetch_gemini_models("valid-test-key")
            self.assertTrue(is_live)
            model_ids = [m[1] for m in models]
            self.assertIn("gemini-3.0-flash-preview", model_ids)
            self.assertIn("gemini-2.5-flash", model_ids)
            # 001 snapshot should be deduplicated
            self.assertNotIn("gemini-2.5-flash-001", model_ids)
            # embedding and imagen should be excluded
            self.assertNotIn("text-embedding-004", model_ids)
            self.assertNotIn("imagen-3.0", model_ids)
            # Gemini 3.0 should rank higher than 2.5
            self.assertLess(model_ids.index("gemini-3.0-flash-preview"), model_ids.index("gemini-2.5-flash"))

    def test_gemma_shot_detection_dialog_initialization(self):
        parent = _BookmarkDialogParent()
        dialog = GemmaShotDetectionDialog(parent)

        self.assertTrue(hasattr(dialog, "refresh_models_btn"))
        self.assertEqual(dialog.model_combo.count(), 10)
        self.assertTrue(len(dialog.model_combo.currentText()) > 0)

        dialog.close()
        parent.close()

    def test_sync_timeline_scroll_on_navigation(self):
        window = MainWindow()
        window.total_frames = 200
        window.timeline.set_total_frames(200)
        window.overview_timeline.set_total_frames(200)

        window.seek_to_frame(50)
        self.assertEqual(window.current_frame, 50)
        self.assertEqual(window.timeline.playhead, 50)
        self.assertEqual(window.overview_timeline.playhead, 50)

        window.next_frame()
        self.assertEqual(window.current_frame, 51)
        self.assertEqual(window.timeline.playhead, 51)
        self.assertEqual(window.overview_timeline.playhead, 51)

        window.prev_frame()
        self.assertEqual(window.current_frame, 50)
        self.assertEqual(window.timeline.playhead, 50)
        self.assertEqual(window.overview_timeline.playhead, 50)

        window.jump_to_end()
        self.assertEqual(window.current_frame, 199)
        self.assertEqual(window.timeline.playhead, 199)

        window.jump_to_start()
        self.assertEqual(window.current_frame, 0)
        self.assertEqual(window.timeline.playhead, 0)

        window.close()

    def test_thumbnail_miniature_no_crop(self):
        timeline = TimelineWidget()
        timeline.set_total_frames(10)
        self.assertEqual(timeline.height(), 96)

        pix = QPixmap(100, 50)
        pix.fill(QColor(255, 0, 0))
        timeline.set_thumbnail(0, pix)

        self.assertIn(0, timeline.thumbnails)
        self.assertEqual(timeline.thumbnails[0].width(), 100)
        self.assertEqual(timeline.thumbnails[0].height(), 50)
        timeline.close()


if __name__ == "__main__":
    unittest.main()
