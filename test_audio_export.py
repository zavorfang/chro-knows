import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from ui_main import MainWindow, ExportMp4Dialog, WanPreparationDialog, MinimaxPreparationDialog
from app_utils import probe_audio_stream, mux_audio_into_mp4


class AudioPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_probe_audio_stream_nonexistent_file(self):
        info = probe_audio_stream("non_existent_file_12345.mp4")
        self.assertIsNone(info)

    def test_mute_toggle_state(self):
        window = MainWindow()
        self.assertFalse(window.audio_muted)
        self.assertEqual(window.mute_btn.text(), "🔊")
        
        window.toggle_mute()
        self.assertTrue(window.audio_muted)
        self.assertEqual(window.mute_btn.text(), "🔇")

        window.toggle_mute()
        self.assertFalse(window.audio_muted)
        self.assertEqual(window.mute_btn.text(), "🔊")

    def test_speed_sets_audio_playback_rate(self):
        window = MainWindow()
        window._has_audio = True
        window._audio_player = MagicMock()
        window.is_playing = True
        window.set_speed("2x")
        self.assertEqual(window.playback_speed, 2.0)
        window._audio_player.setPlaybackRate.assert_called_with(2.0)

        window.set_speed("0.5x")
        self.assertEqual(window.playback_speed, 0.5)
        window._audio_player.setPlaybackRate.assert_called_with(0.5)

    def test_export_dialogs_have_uniform_audio_toggle(self):
        window = MainWindow()
        window.total_frames = 50
        window._has_audio = True

        # When source has audio
        mp4_dlg = ExportMp4Dialog(window)
        self.assertTrue(mp4_dlg.include_audio_checkbox.isChecked())
        self.assertTrue(mp4_dlg.include_audio_checkbox.isEnabled())
        self.assertIn("Source has audio", mp4_dlg.audio_hint.text())

        wan_dlg = WanPreparationDialog(window)
        self.assertTrue(wan_dlg.include_audio_checkbox.isChecked())
        self.assertTrue(wan_dlg.include_audio_checkbox.isEnabled())

        minimax_dlg = MinimaxPreparationDialog(window)
        self.assertTrue(minimax_dlg.include_audio_checkbox.isChecked())
        self.assertTrue(minimax_dlg.include_audio_checkbox.isEnabled())

        # When source has no audio
        window._has_audio = False
        mp4_dlg_no_audio = ExportMp4Dialog(window)
        self.assertFalse(mp4_dlg_no_audio.include_audio_checkbox.isChecked())
        self.assertFalse(mp4_dlg_no_audio.include_audio_checkbox.isEnabled())
        self.assertIn("no audio track", mp4_dlg_no_audio.audio_hint.text())


if __name__ == "__main__":
    unittest.main()
