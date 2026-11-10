import unittest

from app_utils import (
    build_bookmark_export_filename,
    build_bookmark_video_export_filename,
    build_frame_export_filename,
    build_recent_file_label,
    build_shot_grid_filename,
    ensure_extension,
    normalize_image_format,
    normalize_recent_files,
    push_recent_file,
)


class AppUtilsTests(unittest.TestCase):
    def test_ensure_extension_replaces_existing_suffix(self):
        self.assertEqual(ensure_extension("shot_001.jpeg", ".jpg"), "shot_001.jpg")
        self.assertEqual(ensure_extension("shot_001", ".png"), "shot_001.png")

    def test_normalize_image_format_prefers_extension(self):
        self.assertEqual(normalize_image_format("frame.jpg", ""), "JPEG")
        self.assertEqual(normalize_image_format("frame.tif", ""), "TIFF")
        self.assertEqual(normalize_image_format("", "PNG Image (*.png)"), "PNG")

    def test_recent_files_are_deduplicated_and_trimmed(self):
        recent = [
            {"path": r"E:\clips\shot.mov", "kind": "video"},
            {"path": r"E:\clips\shot.mov", "kind": "video"},
            {"path": r"E:\seq\shot", "kind": "folder"},
            {"path": "", "kind": "video"},
        ]
        normalized = normalize_recent_files(recent, limit=2)
        self.assertEqual(
            normalized,
            [
                {"path": r"E:\clips\shot.mov", "kind": "video"},
                {"path": r"E:\seq\shot", "kind": "folder"},
            ],
        )

    def test_push_recent_file_moves_entry_to_front(self):
        recent = [
            {"path": r"E:\seq\shot", "kind": "folder"},
            {"path": r"E:\clips\shot.mov", "kind": "video"},
        ]
        updated = push_recent_file(recent, r"E:\clips\shot.mov", "video", limit=5)
        self.assertEqual(updated[0], {"path": r"E:\clips\shot.mov", "kind": "video"})
        self.assertEqual(len(updated), 2)

    def test_recent_file_label_shows_kind(self):
        label = build_recent_file_label(
            {"path": r"E:\projects\review.kfp_basic", "kind": "project"}
        )
        self.assertEqual(label, "review.kfp_basic (Project)")

    def test_frame_export_filename_is_readable(self):
        filename = build_frame_export_filename("shot 010", 11, "last frame", ".png")
        self.assertEqual(filename, "shot 010_last frame_f0012.png")

    def test_bookmark_export_filename_includes_index_and_frame(self):
        filename = build_bookmark_export_filename(
            "shot010", 3, 24, "Camera Note", ".jpg"
        )
        self.assertEqual(filename, "shot010_bookmark_003_f0025_Camera Note.jpg")

    def test_bookmark_video_export_filename_is_predictable(self):
        filename = build_bookmark_video_export_filename("shot 010", ".mp4")
        self.assertEqual(filename, "shot 010_bookmarks.mp4")

    def test_shot_grid_filename_includes_frames_and_layout(self):
        filename = build_shot_grid_filename(
            "shot 010", 3, 24, 88, 4, 4, ".png"
        )
        self.assertEqual(
            filename, "shot 010_shot_003_f0025-0089_grid4x4.png"
        )

    def test_shot_grid_filename_adds_part_only_when_split(self):
        filename = build_shot_grid_filename(
            "shot010", 2, 0, 127, 4, 4, ".jpg", part=1, total_parts=2
        )
        self.assertEqual(
            filename, "shot010_shot_002_f0001-0128_grid4x4_part1of2.jpg"
        )
        single = build_shot_grid_filename(
            "shot010", 2, 0, 127, 4, 4, ".jpg", part=1, total_parts=1
        )
        self.assertEqual(single, "shot010_shot_002_f0001-0128_grid4x4.jpg")

    def test_shot_grid_filename_sanitizes_parts(self):
        filename = build_shot_grid_filename(
            'my:clip', 1, 0, 9, 2, 2, ".png"
        )
        self.assertEqual(filename, "my_clip_shot_001_f0001-0010_grid2x2.png")


if __name__ == "__main__":
    unittest.main()
