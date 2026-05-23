import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from ui_main import ExportBookmarksDialog


class _BookmarkDialogParent(QWidget):
    def __init__(self):
        super().__init__()
        self.bookmarks = [{"frame": 0, "name": "Start"}]

    def get_default_export_folder(self):
        return os.getcwd()

    def get_loaded_source_name(self):
        return "shot_001"

    def get_export_fps(self):
        return 24


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


if __name__ == "__main__":
    unittest.main()
