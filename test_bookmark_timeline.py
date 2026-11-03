import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent

from timeline import TimelineWidget, OverviewTimelineWidget
from ui_main import MainWindow


class BookmarkTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_timeline_widget_bookmark_selection_and_clear(self):
        timeline = TimelineWidget()
        timeline.set_total_frames(100)
        timeline.add_bookmark(10)
        timeline.add_bookmark(20)

        selected_events = []
        timeline.bookmark_selected.connect(selected_events.append)

        timeline.select_bookmark(10)
        self.assertEqual(timeline.selected_bookmark, 10)
        self.assertEqual(selected_events, [10])

        timeline.clear_selection()
        self.assertEqual(timeline.selected_bookmark, -1)
        self.assertEqual(selected_events, [10, -1])

    def test_timeline_widget_click_bookmark_seeks_and_selects(self):
        timeline = TimelineWidget()
        timeline.set_total_frames(100)
        timeline.frame_width = 8
        timeline.add_bookmark(10)

        selected_frames = []
        selected_bookmarks = []
        timeline.frame_selected.connect(selected_frames.append)
        timeline.bookmark_selected.connect(selected_bookmarks.append)

        # bookmark 10 is at x = 50 + 10 * 8 = 130, y in [0, 24]
        click_pos = QPointF(130.0, 10.0)
        press_event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            click_pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        timeline.mousePressEvent(press_event)

        self.assertEqual(timeline.selected_bookmark, 10)
        self.assertEqual(timeline.playhead, 10)
        self.assertIn(10, selected_frames)
        self.assertIn(10, selected_bookmarks)

    def test_timeline_widget_drag_bookmark_moves_and_emits(self):
        timeline = TimelineWidget()
        timeline.set_total_frames(100)
        timeline.frame_width = 8
        timeline.add_bookmark(10)

        moved_events = []
        timeline.bookmark_moved.connect(lambda old_f, new_f: moved_events.append((old_f, new_f)))

        # Press on bookmark 10 (x=130, y=10)
        press_event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(130.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        timeline.mousePressEvent(press_event)

        # Move to frame 15 (x = 50 + 15 * 8 = 170)
        move_event = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(170.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        timeline.mouseMoveEvent(move_event)

        # Release to commit move
        release_event = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(170.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        timeline.mouseReleaseEvent(release_event)

        self.assertNotIn(10, timeline.bookmarks)
        self.assertIn(15, timeline.bookmarks)
        self.assertEqual(timeline.selected_bookmark, 15)
        self.assertEqual(moved_events, [(10, 15)])

    def test_timeline_widget_drag_collision_rejects_move(self):
        timeline = TimelineWidget()
        timeline.set_total_frames(100)
        timeline.frame_width = 8
        timeline.add_bookmark(10)
        timeline.add_bookmark(15)  # existing bookmark at 15

        moved_events = []
        timeline.bookmark_moved.connect(lambda old_f, new_f: moved_events.append((old_f, new_f)))

        # Press on bookmark 10
        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(130.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        timeline.mousePressEvent(press)

        # Drag to frame 15 (already occupied)
        move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(170.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        timeline.mouseMoveEvent(move)

        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(170.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        timeline.mouseReleaseEvent(release)

        # Move rejected: bookmark 10 should still be at 10
        self.assertIn(10, timeline.bookmarks)
        self.assertIn(15, timeline.bookmarks)
        self.assertEqual(timeline.selected_bookmark, 10)
        self.assertEqual(moved_events, [])

    def test_overview_timeline_selection_and_drag(self):
        overview = OverviewTimelineWidget()
        overview.setFixedWidth(208)  # 4 margin each side, 200 usable
        overview.set_total_frames(101)  # 0 to 100 frames, 2px per frame
        overview.add_bookmark(20)

        moved_events = []
        overview.bookmark_moved.connect(lambda old_f, new_f: moved_events.append((old_f, new_f)))

        # bookmark 20 is at x = 4 + (20/100)*200 = 44
        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(44.0, 14.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        overview.mousePressEvent(press)
        self.assertEqual(overview.selected_bookmark, 20)
        self.assertEqual(overview.playhead, 20)

        # Drag to frame 40 (x = 4 + 0.40*200 = 84)
        move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(84.0, 14.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        overview.mouseMoveEvent(move)

        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(84.0, 14.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        overview.mouseReleaseEvent(release)

        self.assertNotIn(20, overview.bookmarks)
        self.assertIn(40, overview.bookmarks)
        self.assertEqual(overview.selected_bookmark, 40)
        self.assertEqual(moved_events, [(20, 40)])


class MainWindowBookmarkUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = MainWindow()
        self.win.total_frames = 50
        self.win.current_frame = 0

    def tearDown(self):
        self.win.close()

    def test_bookmark_buttons_are_fixed_size_and_icon_only(self):
        self.assertEqual(self.win.add_bookmark_btn.text(), "+")
        self.assertEqual(self.win.remove_bookmark_btn.text(), "−")
        self.assertEqual(self.win.clear_bookmarks_btn.text(), "🗑")

        self.assertEqual(self.win.add_bookmark_btn.width(), 28)
        self.assertEqual(self.win.add_bookmark_btn.height(), 28)
        self.assertEqual(self.win.remove_bookmark_btn.width(), 28)
        self.assertEqual(self.win.remove_bookmark_btn.height(), 28)
        self.assertEqual(self.win.clear_bookmarks_btn.width(), 28)
        self.assertEqual(self.win.clear_bookmarks_btn.height(), 28)

    def test_add_remove_clear_bookmark_states(self):
        win = self.win
        # Initially frame 0 has no bookmark
        win.seek_to_frame(0)
        self.assertTrue(win.add_bookmark_btn.isEnabled())
        self.assertFalse(win.remove_bookmark_btn.isEnabled())
        self.assertFalse(win.clear_bookmarks_btn.isEnabled())

        # Add bookmark at frame 0
        win.add_bookmark()
        self.assertEqual(len(win.bookmarks), 1)
        self.assertIn(0, win.timeline.bookmarks)
        self.assertIn(0, win.overview_timeline.bookmarks)
        self.assertEqual(win.timeline.selected_bookmark, 0)
        self.assertEqual(win.overview_timeline.selected_bookmark, 0)

        # Button state: add disabled, remove enabled, clear enabled
        self.assertFalse(win.add_bookmark_btn.isEnabled())
        self.assertTrue(win.remove_bookmark_btn.isEnabled())
        self.assertTrue(win.clear_bookmarks_btn.isEnabled())

        # Move to frame 5 (no bookmark)
        win.seek_to_frame(5)
        self.assertTrue(win.add_bookmark_btn.isEnabled())
        self.assertFalse(win.remove_bookmark_btn.isEnabled())
        self.assertTrue(win.clear_bookmarks_btn.isEnabled())

        # Move back to frame 0
        win.seek_to_frame(0)
        self.assertFalse(win.add_bookmark_btn.isEnabled())
        self.assertTrue(win.remove_bookmark_btn.isEnabled())

        # Remove bookmark at current frame
        win.remove_current_bookmark()
        self.assertEqual(len(win.bookmarks), 0)
        self.assertNotIn(0, win.timeline.bookmarks)
        self.assertNotIn(0, win.overview_timeline.bookmarks)
        self.assertTrue(win.add_bookmark_btn.isEnabled())
        self.assertFalse(win.remove_bookmark_btn.isEnabled())
        self.assertFalse(win.clear_bookmarks_btn.isEnabled())

    def test_on_bookmark_moved_syncs_model_and_timelines(self):
        win = self.win
        win.seek_to_frame(10)
        win.add_bookmark()
        self.assertEqual(win.bookmarks[0]["frame"], 10)

        # Simulate move from 10 to 25
        win.on_bookmark_moved(10, 25)
        self.assertEqual(win.bookmarks[0]["frame"], 25)
        self.assertNotIn(10, win.timeline.bookmarks)
        self.assertIn(25, win.timeline.bookmarks)
        self.assertNotIn(10, win.overview_timeline.bookmarks)
        self.assertIn(25, win.overview_timeline.bookmarks)


if __name__ == "__main__":
    unittest.main()
