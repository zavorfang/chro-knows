import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Set offscreen for Qt tests
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtGui import QPixmap, QImage
import numpy as np

from ui_main import MainWindow


class PrepareWanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @patch("ui_main.WanFrameReviewDialog")
    @patch("ui_main.QMessageBox.information")
    def test_prepare_wan_exports_correct_files_and_directories(self, mock_info, mock_review_class):
        # Setup mock review dialog
        mock_review = MagicMock()
        mock_review.exec.return_value = QDialog.DialogCode.Accepted
        # 2 chunks of frames with frame indices within each chunk range
        mock_review.get_all_selected_frames.return_value = [
            {"selected_frames": [0, 28, 56]},
            {"selected_frames": [49, 74, 99]}
        ]
        mock_review_class.return_value = mock_review

        # Create window
        window = MainWindow()
        window.total_frames = 100
        
        # Mock project
        window.project = MagicMock()
        window.project.is_video = False
        window.project.name = "test_project"

        # Mock load_frame_data to return a dummy QPixmap
        dummy_image = QImage(256, 256, QImage.Format.Format_RGB888)
        dummy_image.fill(0)
        dummy_pixmap = QPixmap.fromImage(dummy_image)
        window.load_frame_data = MagicMock(return_value=dummy_pixmap)

        # Mock write_mp4_file to just touch the file
        def mock_write_mp4(filepath, frame_numbers, quality, preset="fast", progress_callback=None, fps=None, *args, **kwargs):
            with open(filepath, "wb") as f:
                f.write(b"dummy mp4 data")
        window.write_mp4_file = MagicMock(side_effect=mock_write_mp4)

        # Call prepare_wan
        window.prepare_wan(
            output_folder=self.temp_dir,
            prefix="test_prefix",
            chunk_size=93,
            overlap=8,
            quality=5,
            preset="fast",
            start_frame=0,
            end_frame=99,
            grid_size="2x2",
            per_chunk_grid=True
        )

        # Let's check if the chunk subdirectories were created
        chunk1_dir = os.path.join(self.temp_dir, "test_prefix_chunk_001")
        chunk2_dir = os.path.join(self.temp_dir, "test_prefix_chunk_002")
        
        self.assertTrue(os.path.isdir(chunk1_dir))
        self.assertTrue(os.path.isdir(chunk2_dir))

        # Check chunk 1 files
        # 1. Chunk video mp4 (balanced length is 57 frames, from 0 to 56)
        video1_path = os.path.join(chunk1_dir, "test_prefix_wan22_001_057f_0000-0056.mp4")
        self.assertTrue(os.path.isfile(video1_path))

        # 2. Individual keyframe images (JPEG)
        self.assertTrue(os.path.isfile(os.path.join(chunk1_dir, "test_prefix_chunk_001_frame_01_f0000.jpg")))
        self.assertTrue(os.path.isfile(os.path.join(chunk1_dir, "test_prefix_chunk_001_frame_02_f0028.jpg")))
        self.assertTrue(os.path.isfile(os.path.join(chunk1_dir, "test_prefix_chunk_001_frame_03_f0056.jpg")))

        # 3. 1fps keyframe video
        keyframe_video1_path = os.path.join(chunk1_dir, "test_prefix_chunk_001_1fps.mp4")
        self.assertTrue(os.path.isfile(keyframe_video1_path))

        # 4. Chunk grid image (per_chunk_grid is True)
        grid1_path = os.path.join(chunk1_dir, "test_prefix_chunk_001_grid_2x2.jpg")
        self.assertTrue(os.path.isfile(grid1_path))

        # Check metadata JSON file
        json_path = os.path.join(self.temp_dir, "test_prefix_wan_preparation.json")
        self.assertTrue(os.path.isfile(json_path))

        import json
        with open(json_path, "r") as f:
            metadata = json.load(f)

        self.assertEqual(metadata["num_chunks"], 2)
        # Check relative paths inside output_grids
        self.assertIn("test_prefix_chunk_001/test_prefix_chunk_001_grid_2x2.jpg", metadata["output_grids"])
        self.assertIn("test_prefix_chunk_002/test_prefix_chunk_002_grid_2x2.jpg", metadata["output_grids"])


if __name__ == "__main__":
    unittest.main()
