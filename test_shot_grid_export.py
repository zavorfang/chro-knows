import json
import os
import tempfile
import unittest

import cv2
import numpy as np

from shot_grid import Shot, plan_shot
from shot_grid_export import (
    ShotGridExportOptions,
    export_shot_grids,
)
from shot_grid_render import ShotGridMedia


def frame_color(frame_num):
    return (frame_num * 7 % 256, frame_num * 13 % 256, frame_num * 29 % 256)


def make_sequence(folder, count, width=32, height=24, skip=()):
    files = []
    for frame_num in range(count):
        if frame_num in skip:
            continue
        image = np.empty((height, width, 3), dtype=np.uint8)
        image[:] = frame_color(frame_num)
        cv2.putText(
            image,
            str(frame_num),
            (2, 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.3,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        path = os.path.join(folder, f"frame_{frame_num:04d}.png")
        cv2.imwrite(path, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        files.append(path)
    return files


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = self.temp.name
        self.files = make_sequence(self.folder, 205)
        self.media = ShotGridMedia(
            source_name="test clip",
            total_frames=205,
            fps=24.0,
            kind="sequence",
            files=tuple(self.files),
        )
        self.bookmarks = [
            {"frame": 0, "name": "Start"},
            {"frame": 10, "name": "Second"},
            {"frame": 75, "name": "Third"},
        ]

    def tearDown(self):
        self.temp.cleanup()

    def _options(self, **overrides):
        values = dict(
            output_folder=self.folder,
            prefix="test clip",
            range_start=0,
            range_end=204,
            interval=4,
            max_dim=5,
            format_name="PNG",
            grid_side=128,
            gap=0,
            include_shots=frozenset({1, 2, 3}),
            write_manifest=True,
            write_splitter_sidecars=True,
        )
        values.update(overrides)
        return ShotGridExportOptions(**values)

    def test_export_writes_expected_images_and_manifest(self):
        result = export_shot_grids(
            self.media, self.bookmarks, self._options()
        )
        self.assertEqual(result.errors, [])
        self.assertEqual(result.image_count, 4)
        self.assertEqual(result.shot_count, 3)
        self.assertTrue(os.path.isfile(result.manifest_path))

        with open(result.manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["source_name"], "test clip")
        self.assertEqual(len(manifest["shots"]), 3)
        self.assertFalse(manifest["cancelled"])

        expected_shots = {
            1: Shot(1, 0, 9),
            2: Shot(2, 10, 74),
            3: Shot(3, 75, 204),
        }
        for shot_entry in manifest["shots"]:
            shot = expected_shots[shot_entry["shot_index"]]
            plan = plan_shot(shot, interval=4)
            self.assertEqual(
                shot_entry["samples_at_interval"], plan.samples_at_interval
            )
            self.assertEqual(len(shot_entry["images"]), len(plan.parts))
            self.assertEqual(shot_entry["length"], shot.length)

            for image_entry, part in zip(shot_entry["images"], plan.parts):
                self.assertEqual(image_entry["frames"], list(part.frames))
                self.assertEqual(
                    image_entry["rows"] * image_entry["cols"],
                    len(image_entry["frames"]),
                )
                image_path = os.path.join(
                    result.output_root, image_entry["file"]
                )
                image = cv2.imread(image_path, cv2.IMREAD_COLOR)
                cell_w = image_entry["cell_width"]
                cell_h = image_entry["cell_height"]
                self.assertEqual(
                    image.shape[:2],
                    (part.rows * cell_h, part.cols * cell_w),
                )
                for cell_index, frame_num in enumerate(part.frames):
                    row, col = divmod(cell_index, part.cols)
                    # The frame number is drawn in the top-left, so sample the
                    # bottom-right corner for the solid frame colour.
                    bgr = image[
                        row * cell_h + cell_h - 2,
                        col * cell_w + cell_w - 2,
                    ]
                    self.assertEqual(
                        tuple(int(v) for v in bgr[::-1]),
                        frame_color(frame_num),
                        msg=f"shot {shot.index} cell {cell_index}",
                    )

                sidecar_path = os.path.splitext(image_path)[0] + ".json"
                with open(sidecar_path, "r", encoding="utf-8") as handle:
                    sidecar = json.load(handle)
                self.assertEqual(sidecar["grid_rows"], part.rows)
                self.assertEqual(sidecar["grid_cols"], part.cols)
                self.assertEqual(sidecar["grid_gap"], 0)
                self.assertEqual(sidecar["cell_width"], cell_w)
                self.assertEqual(sidecar["cell_height"], cell_h)
                self.assertEqual(
                    sidecar["chunks"][0]["selected_frames_abs"],
                    list(part.frames),
                )

    def test_saves_individual_frames_and_shot_subfolders(self):
        with tempfile.TemporaryDirectory() as small_folder:
            files = make_sequence(small_folder, 10)
            media = ShotGridMedia(
                source_name="small",
                total_frames=10,
                fps=24.0,
                kind="sequence",
                files=tuple(files),
            )
            result = export_shot_grids(
                media,
                [{"frame": 0, "name": "Only shot"}],
                ShotGridExportOptions(
                    output_folder=self.folder,
                    prefix="small",
                    range_start=0,
                    range_end=9,
                    interval=4,
                    subfolder_per_shot=True,
                    save_individual_frames=True,
                    write_manifest=True,
                    include_shots=frozenset({1}),
                ),
            )
            self.assertEqual(result.errors, [])
            self.assertEqual(result.image_count, 1)
            self.assertEqual(len(result.frame_paths), 4)
            for path in result.frame_paths:
                self.assertTrue(os.path.isfile(path))
                self.assertIn(f"shot_001", path)
            with open(result.manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(len(manifest["shots"][0]["frame_files"]), 4)
            self.assertEqual(manifest["shots"][0]["images"][0]["file"], "shot_001/"
                             + os.path.basename(result.image_paths[0]))

    def test_cancel_keeps_the_current_image_and_writes_a_manifest(self):
        checks = {"count": 0}

        def cancel_check():
            checks["count"] += 1
            return checks["count"] > 2

        result = export_shot_grids(
            self.media,
            self.bookmarks,
            self._options(),
            cancel_check=cancel_check,
        )
        self.assertTrue(result.cancelled)
        self.assertEqual(result.image_count, 1)
        self.assertEqual(len(result.image_paths), 1)
        self.assertTrue(os.path.isfile(result.image_paths[0]))
        self.assertIsNotNone(cv2.imread(result.image_paths[0]))
        with open(result.manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertTrue(manifest["cancelled"])
        self.assertEqual(len(manifest["shots"]), 1)

    def test_missing_frame_reports_the_shot_and_keeps_going(self):
        with tempfile.TemporaryDirectory() as broken_folder:
            files = make_sequence(broken_folder, 10, skip=(6,))
            # Keep the file list the same length as the original sequence by
            # pointing frame 6 at a path that does not exist.
            files[6:6] = [os.path.join(broken_folder, "frame_0006.png")]
            media = ShotGridMedia(
                source_name="broken",
                total_frames=10,
                fps=24.0,
                kind="sequence",
                files=tuple(files),
            )
            result = export_shot_grids(
                media,
                [{"frame": 0, "name": "Broken shot"}],
                ShotGridExportOptions(
                    output_folder=self.folder,
                    prefix="broken",
                    range_start=0,
                    range_end=9,
                    interval=4,
                    write_manifest=True,
                    include_shots=frozenset({1}),
                ),
            )
            self.assertTrue(result.errors)
            self.assertIn("6", result.errors[0])
            self.assertEqual(result.image_count, 0)
            self.assertTrue(os.path.isfile(result.manifest_path))


class RangeTests(unittest.TestCase):
    def test_range_clipping_uses_only_bookmarks_inside_range(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        files = make_sequence(temp.name, 20)
        media = ShotGridMedia(
            source_name="range",
            total_frames=20,
            fps=24.0,
            kind="sequence",
            files=tuple(files),
        )
        result = export_shot_grids(
            media,
            [
                {"frame": 0, "name": "Zero"},
                {"frame": 5, "name": "Five"},
                {"frame": 10, "name": "Ten"},
                {"frame": 15, "name": "Fifteen"},
            ],
            ShotGridExportOptions(
                output_folder=temp.name,
                prefix="range",
                range_start=5,
                range_end=14,
                interval=4,
                include_shots=frozenset({1, 2}),
            ),
        )
        self.assertEqual(result.errors, [])
        self.assertEqual(result.image_count, 2)
        with open(result.manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(
            [(s["start_frame"], s["end_frame"]) for s in manifest["shots"]],
            [(5, 9), (10, 14)],
        )


if __name__ == "__main__":
    unittest.main()
