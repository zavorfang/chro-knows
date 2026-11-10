import os
import tempfile
import unittest

import cv2
import numpy as np

from shot_grid import GridPart
from shot_grid_render import (
    GridRenderOptions,
    SequenceFrameReader,
    compose_grid,
    compute_cell_size,
    render_part,
    write_rgb_image,
)


class _FakeReader:
    def __init__(self, width, height):
        self.width = width
        self.height = height

    def read(self, frame_num):
        image = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        image[:, :] = (frame_num * 10 % 256, frame_num * 20 % 256, 0)
        return image


class CellSizeTests(unittest.TestCase):
    def test_landscape_grid_fits_inside_long_side(self):
        cell_w, cell_h = compute_cell_size(5, 5, 1920, 1080, 2048, 0)
        self.assertLessEqual(5 * cell_w, 2048)
        self.assertLessEqual(5 * cell_h, 2048)
        self.assertAlmostEqual(cell_w / cell_h, 1920 / 1080, delta=0.02)

    def test_portrait_grid_fits_inside_long_side(self):
        cell_w, cell_h = compute_cell_size(3, 4, 1080, 1920, 2048, 4)
        self.assertLessEqual(4 * cell_w + 3 * 4, 2048)
        self.assertLessEqual(3 * cell_h + 2 * 4, 2048)
        self.assertAlmostEqual(cell_w / cell_h, 1080 / 1920, delta=0.02)

    def test_native_uses_source_pixels(self):
        self.assertEqual(compute_cell_size(2, 2, 640, 480, None, 0), (640, 480))

    def test_bad_gap(self):
        with self.assertRaises(ValueError):
            compute_cell_size(5, 5, 100, 100, 20, 10)


class RenderTests(unittest.TestCase):
    def test_render_part_fills_cells_in_row_major_order(self):
        part = GridPart(1, 2, 2, (0, 1, 2, 3))
        reader = _FakeReader(16, 16)
        image = render_part(part, reader, GridRenderOptions(max_side=None))
        self.assertEqual(image.shape, (32, 32, 3))
        expected = [
            (0, 0, 0),
            (10, 20, 0),
            (20, 40, 0),
            (30, 60, 0),
        ]
        for index, color in enumerate(expected):
            row, col = divmod(index, 2)
            cell = image[row * 16:(row + 1) * 16, col * 16:(col + 1) * 16]
            self.assertTrue(np.all(cell == color))

    def test_render_part_supports_gap(self):
        part = GridPart(1, 2, 2, (0, 1, 2, 3))
        reader = _FakeReader(8, 8)
        image = render_part(
            part, reader, GridRenderOptions(max_side=None, gap=2)
        )
        self.assertEqual(image.shape, (18, 18, 3))
        self.assertTrue(np.all(image[8:10, :] == 0))
        self.assertTrue(np.all(image[:, 8:10] == 0))

    def test_compose_grid_pads_missing_cells(self):
        images = [
            np.full((10, 10, 3), 10, dtype=np.uint8),
            np.full((10, 10, 3), 20, dtype=np.uint8),
            np.full((10, 10, 3), 30, dtype=np.uint8),
        ]
        grid = compose_grid(images, 2, 2, gap=1, background=(5, 6, 7))
        self.assertEqual(grid.shape, (21, 21, 3))
        self.assertTrue(np.all(grid[0:10, 0:10] == 10))
        self.assertTrue(np.all(grid[0:10, 11:21] == 20))
        self.assertTrue(np.all(grid[11:21, 0:10] == 30))
        self.assertTrue(np.all(grid[11:21, 11:21] == (5, 6, 7)))

    def test_write_rgb_image_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nested", "grid.png")
            write_rgb_image(path, np.full((4, 5, 3), 42, dtype=np.uint8))
            loaded = cv2.imread(path, cv2.IMREAD_COLOR)
            self.assertEqual(loaded.shape, (4, 5, 3))
            self.assertTrue(np.all(loaded == 42))


if __name__ == "__main__":
    unittest.main()
