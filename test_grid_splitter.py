import json
import os
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from grid_splitter import SmartGridSplitterDialog
from shot_grid_render import compose_grid


class RectangularSidecarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = self.temp.name
        self.video_path = os.path.join(self.folder, "clip.avi")
        self.frame_w, self.frame_h = 64, 48
        # OpenCV writes BGR, so these are red, green, blue in display order.
        colors = [(30, 30, 220), (30, 200, 30), (220, 30, 30)]
        writer = cv2.VideoWriter(
            self.video_path,
            cv2.VideoWriter_fourcc(*"MJPG"),
            24.0,
            (self.frame_w, self.frame_h),
        )
        for color in colors:
            frame = np.empty((self.frame_h, self.frame_w, 3), dtype=np.uint8)
            frame[:] = color
            writer.write(frame)
        writer.release()

        # Build the same 1x3 grid the exporter would write: smaller cells and
        # a gap, not a native square grid.
        cell_w, cell_h, gap = 32, 24, 4
        cells = []
        cap = cv2.VideoCapture(self.video_path)
        for _ in range(3):
            ok, bgr = cap.read()
            self.assertTrue(ok)
            cells.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        cap.release()
        grid = compose_grid(
            cells,
            rows=1,
            cols=3,
            gap=gap,
            cell_size=(cell_w, cell_h),
        )
        self.grid_path = os.path.join(self.folder, "clip_grid.png")
        cv2.imwrite(
            self.grid_path, cv2.cvtColor(grid, cv2.COLOR_RGB2BGR)
        )

        self.sidecar_path = os.path.join(self.folder, "clip_grid.json")
        payload = {
            "grid_dim": 3,
            "grid_rows": 1,
            "grid_cols": 3,
            "grid_gap": gap,
            "cell_width": cell_w,
            "cell_height": cell_h,
            "chunks": [
                {
                    "chunk_index": 0,
                    "video_start_frame_abs": 0,
                    "video_end_frame_abs": 2,
                    "selected_frames_abs": [0, 1, 2],
                }
            ],
        }
        with open(self.sidecar_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def tearDown(self):
        self.temp.cleanup()

    def _dialog(self):
        with open(self.sidecar_path, encoding="utf-8") as handle:
            sidecar = json.load(handle)
        return SmartGridSplitterDialog(
            None,
            {
                "video_path": self.video_path,
                "json_path": self.sidecar_path,
                "json_data": sidecar,
                "grid_path": self.grid_path,
                "chunk_index": 0,
                "output_folder": os.path.join(self.folder, "out"),
            },
        )

    def test_reads_rectangular_geometry_and_auto_scales(self):
        dialog = self._dialog()
        try:
            self.assertEqual(dialog._grid_rows, 1)
            self.assertEqual(dialog._grid_cols, 3)
            self.assertEqual(dialog._grid_gap, 4)
            self.assertEqual(dialog._cell_width, 32)
            self.assertEqual(dialog._cell_height, 24)
            self.assertEqual(dialog._scale_slider.value(), 200)

            dialog._navigate_to(1)
            base = dialog._viewport._grid_base_offset
            self.assertAlmostEqual(base.x(), -(32 + 4) * 2)
            self.assertAlmostEqual(base.y(), 0)
        finally:
            dialog.close()

    def test_export_uses_rows_cols_and_gaps(self):
        dialog = self._dialog()
        try:
            out_dir = os.path.join(self.folder, "exports")
            dialog._output_folder = out_dir
            with mock.patch(
                "grid_splitter.QMessageBox.information"
            ), mock.patch("grid_splitter.QMessageBox.critical"):
                dialog._do_export()

            files = sorted(os.listdir(out_dir))
            self.assertEqual(len(files), 3)
            for name in files:
                image = cv2.imread(os.path.join(out_dir, name))
                self.assertIsNotNone(image)
                self.assertEqual(image.shape[:2], (self.frame_h, self.frame_w))
            # Cell 0 should stay red, cell 1 green, cell 2 blue after the
            # grid is scaled to source resolution and cropped.
            means = [
                cv2.imread(os.path.join(out_dir, name)).reshape(-1, 3).mean(0)
                for name in files
            ]
            self.assertGreater(means[0][2], means[0][0])  # BGR: red
            self.assertGreater(means[1][1], means[1][0])  # green
            self.assertGreater(means[2][0], means[2][2])  # blue
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
