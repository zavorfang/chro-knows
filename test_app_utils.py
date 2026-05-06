import unittest

from app_utils import (
    build_bookmark_export_filename,
    build_bookmark_video_export_filename,
    build_frame_export_filename,
    build_recent_file_label,
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


if __name__ == "__main__":
    unittest.main()
