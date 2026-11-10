import json
import os
import shutil
import tempfile
import threading
import time

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QToolBar,
    QStatusBar,
    QFileDialog,
    QMessageBox,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QFrame,
    QSlider,
    QPushButton,
    QComboBox,
    QCheckBox,
    QSpinBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QScrollArea,
    QApplication,
    QMenuBar,
    QMenu,
    QToolButton,
    QDoubleSpinBox,
    QGroupBox,
    QProgressBar,
    QSizePolicy,
    QRadioButton,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QPointF, QRectF, QEvent, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtGui import (
    QAction,
    QIcon,
    QPixmap,
    QImage,
    QPainter,
    QColor,
    QPen,
    QBrush,
    QKeySequence,
    QCursor,
    QFont,
)

from viewer import ViewerWidget
from timeline import TimelineWidget, OverviewTimelineWidget
from project import Project
from minimax_chunks import (
    MINIMAX_DEFAULT_CHUNK,
    MINIMAX_MIN_FRAMES,
    MINIMAX_OVERLAP_MAX,
    MINIMAX_OVERLAP_MIN,
    MINIMAX_STRIDE,
    MinimaxChunk,
    normalize_minimax_chunk_size,
    normalize_minimax_overlap,
    plan_minimax_chunks,
    snap_to_minimax_ceil,
    snap_to_minimax_floor,
)
from wan_chunks import (
    WAN_CHUNK_SIZE,
    WAN_OVERLAP_MAX,
    WAN_OVERLAP_MIN,
    normalize_chunk_overlap,
    normalize_wan_chunk_size,
    plan_wan_chunks,
)
from grid_splitter import GridSplitterSetupDialog, SmartGridSplitterDialog
from shot_grid_dialog import ShotGridDialog, show_shot_grid_export
from shot_grid_render import ShotGridMedia, compose_grid
from app_utils import (
    mux_audio_into_mp4,
    probe_audio_stream,

    IMAGE_EXPORT_FILTER,
    IMAGE_EXPORT_FORMATS,
    build_bookmark_export_filename,
    build_bookmark_video_export_filename,
    build_frame_export_filename,
    build_recent_file_label,
    ensure_extension,
    normalize_image_format,
    normalize_recent_files,
    push_recent_file,
    sanitize_filename_part,
)
from gemma_shot_detection import (
    AnalysisChunk,
    ChunkShotAnalysis,
    DetectedShot,
    GemmaShot,
    SHOT_ANALYSIS_CHUNK_SECONDS,
    TraditionalCutCandidate,
    description_similarity,
    detect_cut_candidates_from_scores,
    extract_json_payload,
    finalize_shot_ranges,
    find_nearest_candidate,
    frame_to_timestamp,
    match_chunk_shots_to_candidates,
    merge_shot_descriptions,
    parse_chunk_shot_response,
    plan_shot_analysis_chunks,
    should_merge_boundary_duplicate,
)


class MainWindow(QMainWindow):
    frame_changed = pyqtSignal(int)
    DUMMY_API_KEYS = {
        "",
        "AIzaSyDUMMY_REPLACE_ME",
        "your-google-ai-studio-key-here",
        "replace-with-your-google-ai-studio-key",
        "dummy-gemini-key",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Keyframe Pro Lite")
        self.setGeometry(100, 100, 1280, 720)
        self.setMinimumSize(640, 480)

        self.project = Project()
        self.current_frame = 0
        self.total_frames = 0
        self.is_playing = False
        self.playback_speed = 1.0
        self.fps = 24
        self.loop_enabled = False
        self.scrubbing = False

        self.view_pan = QPointF(0, 0)
        self.view_zoom = 1.0

        self.cache_size_mb = 500
        self.audio_scrub = False
        self.scrub_sensitivity = 5
        self.auto_save_enabled = True
        self.export_folder = ""
        self.recent_files = []
        self.recent_files_menu = None
        self.shot_grid_settings = {}
        self.audio_muted = False
        self.audio_volume = 80
        self.audio_enabled = True
        self._has_audio = False
        self._audio_player = None
        self._audio_output = None
        self._video_cap = None
        self._video_cap_pos = -1
        self._play_clock_start = 0.0
        self._play_frame_start = 0
        self._effective_fps = 24
        self._init_audio()

        self.load_settings()

        self.init_ui()
        self.init_menu()
        self.init_timeline()
        self.init_bookmark_panel()

        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self.play_step)

        self.auto_save_timer = QTimer()
        if self.auto_save_enabled:
            self.auto_save_timer.timeout.connect(self.auto_save)
            self.auto_save_timer.start(120000)

        self.frame_cache = {}
        self.max_cache_frames = (self.cache_size_mb * 1024 * 1024) // (1920 * 1080 * 4)

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(2000)

        self.update_status()

    def _init_audio(self):
        try:
            self._audio_output = QAudioOutput(self)
            self._audio_output.setVolume(self.audio_volume / 100.0)
            self._audio_player = QMediaPlayer(self)
            self._audio_player.setAudioOutput(self._audio_output)
        except Exception:
            self._audio_output = None
            self._audio_player = None

    def toggle_mute(self):
        self.audio_muted = not self.audio_muted
        if self._audio_output:
            self._audio_output.setMuted(self.audio_muted)
        if hasattr(self, "mute_btn"):
            self.mute_btn.setText("🔇" if self.audio_muted else "🔊")
            self.mute_btn.setToolTip("Unmute (M)" if self.audio_muted else "Mute (M)")

    def init_ui(self):
        self.central_widget = QWidget()
        self.central_widget.setAcceptDrops(True)
        self.central_widget.dragEnterEvent = self.drag_enter_event
        self.central_widget.dropEvent = self.drop_event
        self.setCentralWidget(self.central_widget)

        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.init_toolbar()

        main_splitter = QSplitter(Qt.Orientation.Vertical)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.viewer = ViewerWidget(self)
        self.viewer.frame_clicked.connect(self.on_viewer_click)
        self.viewer.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.viewer.customContextMenuRequested.connect(self.show_viewer_context_menu)

        top_splitter.addWidget(self.viewer)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)

        self.bookmark_list = QListWidget()
        self.bookmark_list.itemClicked.connect(self.on_bookmark_clicked)
        self.bookmark_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bookmark_list.customContextMenuRequested.connect(
            self.show_bookmark_context_menu
        )
        self.bookmark_list.installEventFilter(self)
        right_layout.addWidget(QLabel("Bookmarks"))
        right_layout.addWidget(self.bookmark_list)

        bookmark_button_row = QHBoxLayout()
        bookmark_button_row.setSpacing(4)

        self.add_bookmark_btn = QPushButton("+")
        self.add_bookmark_btn.setFixedSize(28, 28)
        self.add_bookmark_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding: 0;")
        self.add_bookmark_btn.setToolTip("Add bookmark at current frame")
        self.add_bookmark_btn.clicked.connect(self.add_bookmark)
        bookmark_button_row.addWidget(self.add_bookmark_btn)

        self.remove_bookmark_btn = QPushButton("−")
        self.remove_bookmark_btn.setFixedSize(28, 28)
        self.remove_bookmark_btn.setStyleSheet("font-size: 14px; font-weight: bold; padding: 0;")
        self.remove_bookmark_btn.setToolTip("Remove bookmark at current frame")
        self.remove_bookmark_btn.clicked.connect(self.remove_current_bookmark)
        self.remove_bookmark_btn.setEnabled(False)
        bookmark_button_row.addWidget(self.remove_bookmark_btn)

        self.clear_bookmarks_btn = QPushButton("🗑")
        self.clear_bookmarks_btn.setFixedSize(28, 28)
        self.clear_bookmarks_btn.setStyleSheet("font-size: 12px; padding: 0;")
        self.clear_bookmarks_btn.setToolTip("Delete all bookmarks")
        self.clear_bookmarks_btn.clicked.connect(self.delete_all_bookmarks)
        bookmark_button_row.addWidget(self.clear_bookmarks_btn)

        bookmark_button_row.addStretch()
        right_layout.addLayout(bookmark_button_row)

        top_splitter.addWidget(right_panel)
        top_splitter.setStretchFactor(0, 4)
        top_splitter.setStretchFactor(1, 1)

        main_splitter.addWidget(top_splitter)

        self.timeline_container = QWidget()
        self.timeline_layout = QVBoxLayout(self.timeline_container)
        self.timeline_layout.setContentsMargins(4, 0, 4, 4)
        self.timeline_layout.setSpacing(2)
        main_splitter.addWidget(self.timeline_container)

        main_splitter.setStretchFactor(0, 9)
        main_splitter.setStretchFactor(1, 1)

        self.main_layout.addWidget(main_splitter)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def init_toolbar(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)

        self.open_folder_btn = QPushButton("📂 Open")
        self.open_folder_btn.setToolTip("Open a folder of image sequences")
        self.open_folder_btn.clicked.connect(self.open_folder)
        toolbar.addWidget(self.open_folder_btn)

        toolbar.addSeparator()

        self.jump_start_btn = QPushButton("|◀")
        self.jump_start_btn.setFixedWidth(40)
        self.jump_start_btn.setToolTip("Jump to Start (Home)")
        self.jump_start_btn.clicked.connect(self.jump_to_start)
        toolbar.addWidget(self.jump_start_btn)

        self.prev_frame_btn = QPushButton("◀")
        self.prev_frame_btn.setFixedWidth(40)
        self.prev_frame_btn.setToolTip("Previous Frame (Left Arrow)")
        self.prev_frame_btn.clicked.connect(self.prev_frame)
        toolbar.addWidget(self.prev_frame_btn)

        self.play_pause_btn = QPushButton("▶")
        self.play_pause_btn.setFixedWidth(50)
        self.play_pause_btn.setToolTip("Play / Pause (Space)")
        self.play_pause_btn.clicked.connect(self.toggle_play)
        toolbar.addWidget(self.play_pause_btn)

        self.next_frame_btn = QPushButton("▶")
        self.next_frame_btn.setFixedWidth(40)
        self.next_frame_btn.setToolTip("Next Frame (Right Arrow)")
        self.next_frame_btn.clicked.connect(self.next_frame)
        toolbar.addWidget(self.next_frame_btn)

        self.jump_end_btn = QPushButton("▶|")
        self.jump_end_btn.setFixedWidth(40)
        self.jump_end_btn.setToolTip("Jump to End (End)")
        self.jump_end_btn.clicked.connect(self.jump_to_end)
        toolbar.addWidget(self.jump_end_btn)

        toolbar.addSeparator()

        self.loop_btn = QPushButton("🔁")
        self.loop_btn.setCheckable(True)
        self.loop_btn.setFixedWidth(40)
        self.loop_btn.setToolTip("Toggle Loop Playback")
        self.loop_btn.clicked.connect(self.toggle_loop)
        toolbar.addWidget(self.loop_btn)

        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.25x", "0.5x", "1x", "2x"])
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.setFixedWidth(70)
        self.speed_combo.setToolTip("Playback Speed")
        self.speed_combo.currentTextChanged.connect(self.set_speed)
        toolbar.addWidget(self.speed_combo)
        self.mute_btn = QPushButton("🔊")
        self.mute_btn.setFixedWidth(40)
        self.mute_btn.setToolTip("Mute / Unmute (M)")
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.mute_btn.setEnabled(False)
        toolbar.addWidget(self.mute_btn)

        toolbar.addSeparator()

        self.frame_label = QLabel("Frame: 0 / 0")
        self.frame_label.setMinimumWidth(120)
        toolbar.addWidget(self.frame_label)

        self.timecode_label = QLabel("00:00:00:00")
        self.timecode_label.setMinimumWidth(100)
        toolbar.addWidget(self.timecode_label)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self.loaded_file_label = QLabel("")
        self.loaded_file_label.setStyleSheet("color: #888; font-style: italic;")
        toolbar.addWidget(self.loaded_file_label)

        self.fps_label = QLabel(f"{self.fps} FPS")
        toolbar.addWidget(self.fps_label)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedWidth(40)
        self.settings_btn.setToolTip("Preferences")
        self.settings_btn.clicked.connect(self.show_preferences)
        toolbar.addWidget(self.settings_btn)

    def init_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")

        open_action = QAction("Open Folder...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_folder)
        file_menu.addAction(open_action)

        open_video_action = QAction("Open Video File...", self)
        open_video_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
        open_video_action.triggered.connect(self.open_video_file)
        file_menu.addAction(open_video_action)

        self.recent_files_menu = file_menu.addMenu("Recent Files")
        self.refresh_recent_files_menu()

        file_menu.addSeparator()

        save_action = QAction("Save Project", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_project)
        file_menu.addAction(save_action)

        load_action = QAction("Load Project...", self)
        load_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        load_action.triggered.connect(self.load_project)
        file_menu.addAction(load_action)

        file_menu.addSeparator()

        export_menu = file_menu.addMenu("Export")

        export_action = QAction("Frame / Sequence...", self)
        export_action.setShortcut(QKeySequence.StandardKey.Print)
        export_action.triggered.connect(self.show_export_dialog)
        export_menu.addAction(export_action)

        export_current_frame_action = QAction("Current Frame Image...", self)
        export_current_frame_action.triggered.connect(self.export_current_frame_image)
        export_menu.addAction(export_current_frame_action)

        export_first_frame_action = QAction("First Frame Image...", self)
        export_first_frame_action.triggered.connect(self.export_first_frame_image)
        export_menu.addAction(export_first_frame_action)

        export_last_frame_action = QAction("Last Frame Image...", self)
        export_last_frame_action.triggered.connect(self.export_last_frame_image)
        export_menu.addAction(export_last_frame_action)

        export_bookmarks_action = QAction("Bookmarks...", self)
        export_bookmarks_action.triggered.connect(self.show_export_bookmarks_dialog)
        export_menu.addAction(export_bookmarks_action)

        self.export_shot_grids_action = QAction("Shot Grids...", self)
        self.export_shot_grids_action.triggered.connect(self.show_shot_grid_dialog)
        self.export_shot_grids_action.setEnabled(self.total_frames > 0)
        export_menu.addAction(self.export_shot_grids_action)

        export_mp4_action = QAction("MP4...", self)
        export_mp4_action.triggered.connect(self.show_export_mp4_dialog)
        export_menu.addAction(export_mp4_action)

        wan_prep_action = QAction("Wan Preparation...", self)
        wan_prep_action.triggered.connect(self.show_wan_preparation_dialog)
        export_menu.addAction(wan_prep_action)
        minimax_prep_action = QAction("MiniMax H3 Preparation...", self)
        minimax_prep_action.triggered.connect(self.show_minimax_preparation_dialog)
        export_menu.addAction(minimax_prep_action)

        grid_splitter_action = QAction("Smart Grid Splitter...", self)
        grid_splitter_action.triggered.connect(self.show_grid_splitter_dialog)
        export_menu.addAction(grid_splitter_action)

        gemma_shot_action = QAction("Detect Shots...", self)
        gemma_shot_action.setShortcut(QKeySequence("Ctrl+Shift+G"))
        gemma_shot_action.triggered.connect(self.show_gemma_shot_detection_dialog)
        file_menu.addAction(gemma_shot_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = menubar.addMenu("View")

        fit_action = QAction("Fit to Window", self)
        fit_action.setShortcut(QKeySequence("F"))
        fit_action.triggered.connect(self.viewer.fit_to_window)
        view_menu.addAction(fit_action)

        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
        zoom_in_action.triggered.connect(self.viewer.zoom_in)
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        zoom_out_action.triggered.connect(self.viewer.zoom_out)
        view_menu.addAction(zoom_out_action)

        playback_menu = menubar.addMenu("Playback")

        play_action = QAction("Play/Pause", self)
        play_action.setShortcut(Qt.Key.Key_Space)
        play_action.triggered.connect(self.toggle_play)
        playback_menu.addAction(play_action)

        prev_action = QAction("Previous Frame", self)
        prev_action.setShortcut(Qt.Key.Key_Left)
        prev_action.triggered.connect(self.prev_frame)
        playback_menu.addAction(prev_action)

        next_action = QAction("Next Frame", self)
        next_action.setShortcut(Qt.Key.Key_Right)
        next_action.triggered.connect(self.next_frame)
        playback_menu.addAction(next_action)

        playback_menu.addSeparator()
        nudge_earlier_action = QAction("Nudge Selected Bookmark Earlier", self)
        nudge_earlier_action.setShortcut(QKeySequence("Alt+Left"))
        nudge_earlier_action.triggered.connect(lambda: self.nudge_selected_bookmark(-1))
        playback_menu.addAction(nudge_earlier_action)

        nudge_later_action = QAction("Nudge Selected Bookmark Later", self)
        nudge_later_action.setShortcut(QKeySequence("Alt+Right"))
        nudge_later_action.triggered.connect(lambda: self.nudge_selected_bookmark(1))
        playback_menu.addAction(nudge_later_action)

        help_menu = menubar.addMenu("Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def init_timeline(self):
        # Overview bar (thin, full-width, no thumbnails)
        self.overview_timeline = OverviewTimelineWidget(self)
        self.overview_timeline.frame_selected.connect(self.seek_to_frame)
        self.overview_timeline.bookmark_selected.connect(self.on_bookmark_selected)
        self.overview_timeline.bookmark_moved.connect(self.on_bookmark_moved)
        self.timeline_layout.addWidget(self.overview_timeline)

        # Thumbnail timeline (scrollable, for fine scrubbing)
        self.timeline = TimelineWidget(self)
        self.timeline.frame_selected.connect(self.seek_to_frame)
        self.timeline.bookmark_selected.connect(self.on_bookmark_selected)
        self.timeline.bookmark_moved.connect(self.on_bookmark_moved)

        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.timeline_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.timeline_scroll.setWidget(self.timeline)
        self.timeline_scroll.setStyleSheet(
            "QScrollArea { border: none; background-color: #2a2a2a; }"
        )
        self.timeline_layout.addWidget(self.timeline_scroll)

    def sync_timeline_scroll(self):
        if not hasattr(self, "timeline_scroll"):
            return

        frame_offset = 50
        playhead_x = frame_offset + self.current_frame * self.timeline.frame_width

        scrollbar = self.timeline_scroll.horizontalScrollBar()
        viewport_width = self.timeline_scroll.viewport().width()
        current_scroll = scrollbar.value()
        margin = 100

        if playhead_x < current_scroll + margin:
            scrollbar.setValue(int(max(0, playhead_x - margin)))
        elif playhead_x > current_scroll + viewport_width - margin:
            scrollbar.setValue(
                int(min(scrollbar.maximum(), playhead_x - viewport_width + margin))
            )

    def init_bookmark_panel(self):
        self.bookmarks = []
        self.update_bookmark_button_state()

    def get_settings_path(self):
        return os.path.join(os.path.expanduser("~"), ".kfpro_lite_settings.json")

    def update_shot_grid_action_state(self):
        if hasattr(self, "export_shot_grids_action"):
            self.export_shot_grids_action.setEnabled(self.total_frames > 0)

    def save_shot_grid_settings(self, settings):
        self.shot_grid_settings = dict(settings or {})
        self.save_settings()

    def get_default_export_folder(self):
        if self.export_folder and os.path.isdir(self.export_folder):
            return self.export_folder

        default_base = os.path.join(os.path.expanduser("~"), "Videos", "KFPlayer")
        try:
            os.makedirs(default_base, exist_ok=True)
            return default_base
        except:
            pass

        if getattr(self.project, "is_video", False) and hasattr(self.project, "video_path"):
            return os.path.dirname(self.project.video_path)
        if self.project.folder and os.path.isdir(self.project.folder):
            return self.project.folder
        return os.path.expanduser("~")

    def remember_export_folder(self, path):
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if folder:
            self.export_folder = folder
            self.save_settings()

    def get_loaded_source_name(self):
        if getattr(self.project, "is_video", False) and hasattr(self.project, "video_path"):
            return os.path.splitext(os.path.basename(self.project.video_path))[0]
        if self.project.folder:
            return os.path.basename(os.path.normpath(self.project.folder))
        if self.project.sources:
            return self.project.sources[0].get("name", self.project.name)
        return "kfplayer"

    def reset_loaded_media_state(self, clear_bookmarks=True):
        if getattr(self, "_video_cap", None) is not None:
            try:
                self._video_cap.release()
            except Exception:
                pass
            self._video_cap = None
        self._video_cap_pos = -1
        if getattr(self, "_audio_player", None) is not None:
            self._audio_player.stop()
            self._audio_player.setSource(QUrl())
        self._has_audio = False
        if hasattr(self, "mute_btn"):
            self.mute_btn.setEnabled(False)
        self.frame_cache = {}
        self.timeline.thumbnails.clear()
        self.timeline.bookmarks.clear()
        self.timeline.selected_bookmark = -1
        self.timeline.set_playhead(0)
        self.overview_timeline.bookmarks.clear()
        self.overview_timeline.selected_bookmark = -1
        self.overview_timeline.set_playhead(0)
        if clear_bookmarks:
            self.bookmarks = []
            self.update_bookmark_list()
        self.update_shot_grid_action_state()

    def add_recent_file(self, path, kind):
        self.recent_files = push_recent_file(self.recent_files, path, kind)
        self.save_settings()
        self.refresh_recent_files_menu()

    def remove_recent_file(self, path, kind=None):
        path = os.path.normpath(path)
        self.recent_files = [
            entry
            for entry in self.recent_files
            if not (
                entry.get("path", "").lower() == path.lower()
                and (kind is None or entry.get("kind") == kind)
            )
        ]
        self.save_settings()
        self.refresh_recent_files_menu()

    def refresh_recent_files_menu(self):
        if self.recent_files_menu is None:
            return

        self.recent_files_menu.clear()

        if not self.recent_files:
            empty_action = QAction("No recent files", self)
            empty_action.setEnabled(False)
            self.recent_files_menu.addAction(empty_action)
            return

        for entry in self.recent_files:
            action = QAction(build_recent_file_label(entry), self)
            action.setToolTip(entry["path"])
            action.triggered.connect(
                lambda checked=False, recent_entry=entry: self.open_recent_file(
                    recent_entry
                )
            )
            self.recent_files_menu.addAction(action)

        self.recent_files_menu.addSeparator()
        clear_action = QAction("Clear History", self)
        clear_action.triggered.connect(self.clear_recent_files_history)
        self.recent_files_menu.addAction(clear_action)

    def clear_recent_files_history(self):
        self.recent_files = []
        self.save_settings()
        self.refresh_recent_files_menu()

    def open_recent_file(self, entry):
        path = entry.get("path", "")
        kind = entry.get("kind", "video")

        if not path or not os.path.exists(path):
            QMessageBox.warning(
                self,
                "Recent File Missing",
                f"This recent item is no longer available:\n{path}",
            )
            self.remove_recent_file(path, kind)
            return

        if kind == "project":
            self.load_project_from_file(path)
        elif kind == "folder" or os.path.isdir(path):
            self.project.folder = path
            self.scan_folder(path)
        else:
            self.load_video(path)

    def load_settings(self):
        settings_path = self.get_settings_path()
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                    self.cache_size_mb = settings.get("cache_size", 500)
                    self.fps = settings.get("default_fps", 24)
                    self.export_folder = settings.get("export_folder", "")
                    self.audio_scrub = settings.get("audio_scrub", False)
                    self.audio_muted = settings.get("audio_muted", False)
                    self.audio_volume = settings.get("audio_volume", 80)
                    self.audio_enabled = settings.get("audio_enabled", True)
                    self.scrub_sensitivity = settings.get("scrub_sensitivity", 5)
                    self.auto_save_enabled = settings.get("auto_save", True)
                    self.recent_files = normalize_recent_files(
                        settings.get("recent_files", [])
                    )
                    shot_grid = settings.get("shot_grid", {})
                    self.shot_grid_settings = shot_grid if isinstance(shot_grid, dict) else {}
            except:
                pass

    def save_settings(self):
        settings_path = self.get_settings_path()
        settings = {
            "cache_size": self.cache_size_mb,
            "default_fps": self.fps,
            "export_folder": self.export_folder,
            "audio_scrub": self.audio_scrub,
            "audio_muted": self.audio_muted,
            "audio_volume": self.audio_volume,
            "audio_enabled": self.audio_enabled,
            "scrub_sensitivity": self.scrub_sensitivity,
            "auto_save": self.auto_save_enabled,
            "recent_files": self.recent_files,
            "shot_grid": self.shot_grid_settings,
        }
        with open(settings_path, "w") as f:
            json.dump(settings, f)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.project.folder = folder
            self.scan_folder(folder)

    def scan_folder(self, folder, add_to_recent=True):
        from viewer import detect_sequence

        sequences = detect_sequence(folder)

        if sequences:
            self.reset_loaded_media_state(clear_bookmarks=True)
            self.project.sources = []
            self.project.folder = folder
            self.project.name = os.path.basename(os.path.normpath(folder)) or "Untitled"

            # Reset video state when loading folder
            if hasattr(self.project, "is_video"):
                self.project.is_video = False
            if hasattr(self.project, "video_path"):
                delattr(self.project, "video_path")

            self.total_frames = len(sequences[0]["files"])
            self.current_frame = 0

            # Get resolution from first frame
            try:
                from PIL import Image
                with Image.open(sequences[0]["files"][0]) as img:
                    self.video_width, self.video_height = img.size
            except:
                self.video_width, self.video_height = 0, 0

            self.update_frame_display()
            self.timeline.set_total_frames(self.total_frames)
            self.overview_timeline.set_total_frames(self.total_frames)
            self.load_frame(0)
            self.generate_thumbnails()

            folder_name = os.path.basename(folder)
            self.setWindowTitle(f"KFPlayer — {folder_name}")
            self.loaded_file_label.setText(folder_name)
            if add_to_recent:
                self.add_recent_file(folder, "folder")
            return True
        else:
            QMessageBox.warning(
                self, "No Sequences", "No image sequences found in the selected folder."
            )
            return False

    def open_video_file(self):
        """Open a video file using file dialog"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Video File",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.webm *.wmv *.gif);;All Files (*)",
        )

        if file_path:
            self.load_video(file_path)

    def drag_enter_event(self, event):
        """Handle drag enter event for file drop"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def drop_event(self, event):
        """Handle file drop event"""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()

                if os.path.isdir(file_path):
                    self.project.folder = file_path
                    self.scan_folder(file_path)
                    break
                elif os.path.isfile(file_path):
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext in [".mp4", ".avi", ".mov", ".mkv", ".webm", ".wmv", ".gif"]:
                        self.load_video(file_path)
                        break
                    elif ext in [
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".tga",
                        ".bmp",
                        ".tiff",
                        ".tif",
                        ".exr",
                        ".dpx",
                    ]:
                        # If a single image is dropped, load its parent folder as a sequence
                        parent_folder = os.path.dirname(file_path)
                        self.project.folder = parent_folder
                        self.scan_folder(parent_folder)
                        break
        event.acceptProposedAction()

    def load_video(self, file_path, add_to_recent=True):
        """Load a video file and prepare for playback"""
        import cv2

        ext = os.path.splitext(file_path)[1].lower()

        # Get video properties
        if ext == ".gif":
            # Handle GIF with Pillow for correct frame count
            from PIL import Image

            try:
                gif = Image.open(file_path)
                frame_count = 0
                while True:
                    try:
                        gif.seek(frame_count)
                        frame_count += 1
                    except EOFError:
                        break

                # Get duration for FPS
                gif.seek(0)
                duration = gif.info.get("duration", 100)
                fps = 1000 / duration if duration > 0 else 24.0
                width, height = gif.size
            except Exception as e:
                QMessageBox.warning(
                    self, "Error", f"Could not open GIF file: {file_path}"
                )
                return False
        else:
            # Regular video handling with OpenCV
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                QMessageBox.warning(
                    self, "Error", f"Could not open video file: {file_path}"
                )
                return False

            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

        self.reset_loaded_media_state(clear_bookmarks=True)

        # Clear existing sources when loading a video
        self.project.sources = []
        self.project.folder = os.path.dirname(file_path)
        self.project.name = os.path.splitext(os.path.basename(file_path))[0]

        # Store video info in project
        self.project.video_path = file_path
        self.project.video_frame_count = frame_count
        self.project.video_fps = fps
        self.project.is_video = True

        # Reset state
        self.total_frames = frame_count
        self.current_frame = 0
        self.fps = int(fps) if fps > 0 else 24

        # Clear frame cache
        self.frame_cache = {}

        self.video_width = width
        self.video_height = height
        # Probe audio
        audio_info = probe_audio_stream(file_path) if ext != ".gif" else None
        self._has_audio = bool(audio_info)
        if getattr(self, "_audio_player", None) and self._has_audio:
            self._audio_player.setSource(QUrl.fromLocalFile(file_path))
            if hasattr(self, "mute_btn"):
                self.mute_btn.setEnabled(True)
                self.mute_btn.setText("🔇" if self.audio_muted else "🔊")
                self.mute_btn.setToolTip("Mute / Unmute (M)")
        else:
            if getattr(self, "_audio_player", None):
                self._audio_player.stop()
                self._audio_player.setSource(QUrl())
            if hasattr(self, "mute_btn"):
                self.mute_btn.setEnabled(False)
                self.mute_btn.setToolTip("No audio track in source")

        if getattr(self, "_video_cap", None) is not None:
            try:
                self._video_cap.release()
            except Exception:
                pass
            self._video_cap = None
        self._video_cap_pos = -1
        if ext != ".gif":
            self._video_cap = cv2.VideoCapture(file_path)
            self._video_cap_pos = 0

        # Update UI
        self.update_frame_display()
        self.timeline.set_total_frames(self.total_frames)
        self.overview_timeline.set_total_frames(self.total_frames)
        self.load_frame(0)

        # Generate thumbnails in background
        self.generate_video_thumbnails(file_path)

        self.statusBar().showMessage(
            f"Loaded video: {os.path.basename(file_path)} - {frame_count} frames at {fps:.2f} fps"
        )

        video_name = os.path.basename(file_path)
        self.setWindowTitle(f"KFPlayer — {video_name}")
        self.loaded_file_label.setText(video_name)
        if add_to_recent:
            self.add_recent_file(file_path, "video")
        return True

    def generate_video_thumbnails(self, file_path):
        """Generate thumbnails from video file"""
        import cv2

        def worker():
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return

            frame_step = max(1, self.total_frames // 50)

            for i in range(0, self.total_frames, frame_step):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()

                if ret:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w = frame_rgb.shape[:2]

                    # Scale to thumbnail
                    scale = 64 / max(w, h)
                    new_w = int(w * scale)
                    new_h = int(h * scale)

                    from PIL import Image
                    import numpy as np

                    img = Image.fromarray(frame_rgb)
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                    thumb = QPixmap.fromImage(
                        QImage(
                            img.tobytes(),
                            new_w,
                            new_h,
                            new_w * 3,
                            QImage.Format.Format_RGB888,
                        )
                    )

                    self.timeline.set_thumbnail(i, thumb)

            cap.release()

        thread = threading.Thread(target=worker)
        thread.daemon = True
        thread.start()

    def generate_thumbnails(self):
        def worker():
            for i in range(
                0, min(self.total_frames, 100), max(1, self.total_frames // 50)
            ):
                if hasattr(self, "project") and self.project.sources:
                    frame = self.load_frame_data(i)
                    if frame is not None:
                        thumb = frame.scaled(
                            64,
                            64,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        self.timeline.set_thumbnail(i, thumb)

        thread = threading.Thread(target=worker)
        thread.daemon = True
        thread.start()

    def load_frame(self, frame_num):
        if frame_num < 0 or frame_num >= self.total_frames:
            return

        if frame_num in self.frame_cache:
            self.viewer.set_image(self.frame_cache[frame_num])
            return

        frame_data = self.load_frame_data(frame_num)
        if frame_data is not None:
            self.frame_cache[frame_num] = frame_data

            if len(self.frame_cache) > self.max_cache_frames:
                oldest = next(iter(self.frame_cache))
                del self.frame_cache[oldest]

            self.viewer.set_image(frame_data)

    def load_frame_data(self, frame_num):
        # Handle video files
        if getattr(self.project, "is_video", False) and hasattr(
            self.project, "video_path"
        ):
            import cv2
            import numpy as np
            from PIL import Image

            video_path = self.project.video_path
            ext = os.path.splitext(video_path)[1].lower()

            if ext == ".gif":
                # Handle animated GIFs with Pillow
                try:
                    gif = Image.open(video_path)
                    if frame_num < 0:
                        return None

                    try:
                        gif.seek(frame_num)
                        frame = gif.convert("RGB")
                        frame_np = np.array(frame)
                        # Convert to QImage/QPixmap directly
                        height, width, channels = frame_np.shape
                        bytes_per_line = channels * width
                        qimage = QImage(
                            frame_np.data,
                            width,
                            height,
                            bytes_per_line,
                            QImage.Format.Format_RGB888,
                        )
                        return QPixmap.fromImage(qimage)
                    except EOFError:
                        return None
                except Exception:
                    return None
            else:
                # Regular video handling with persistent OpenCV VideoCapture
                if getattr(self, "_video_cap", None) is None or not self._video_cap.isOpened():
                    self._video_cap = cv2.VideoCapture(video_path)
                    self._video_cap_pos = -1

                if not self._video_cap.isOpened():
                    return None

                if self._video_cap_pos == frame_num:
                    ret, frame = self._video_cap.read()
                    self._video_cap_pos += 1
                else:
                    self._video_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                    ret, frame = self._video_cap.read()
                    self._video_cap_pos = frame_num + 1 if ret else -1

                if not ret:
                    return None

                # Convert BGR to RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                height, width, channels = frame_rgb.shape
                bytes_per_line = channels * width

                qimage = QImage(
                    frame_rgb.data,
                    width,
                    height,
                    bytes_per_line,
                    QImage.Format.Format_RGB888,
                )
                return QPixmap.fromImage(qimage)

        # Handle image sequences
        if not self.project.sources:
            return None

        source = self.project.sources[0]
        files = source.get("files", [])

        if frame_num >= len(files):
            return None

        filepath = files[frame_num]

        try:
            from PIL import Image
            import numpy as np

            img = Image.open(filepath)
            if img.mode != "RGBA" and img.mode != "RGB":
                img = img.convert("RGB")

            img_array = np.array(img)

            height, width, channels = img_array.shape
            bytes_per_line = channels * width
            qimage = QImage(
                img_array.data,
                width,
                height,
                bytes_per_line,
                QImage.Format.Format_RGB888,
            )

            return QPixmap.fromImage(qimage)

        except Exception as e:
            print(f"Error loading frame {filepath}: {e}")
            return None

    def seek_to_frame(self, frame_num):
        self.current_frame = frame_num
        self.load_frame(frame_num)
        self.update_frame_display()
        self.sync_timeline_scroll()
        self.update_bookmark_button_state()
        if self.is_playing:
            self._play_clock_start = time.perf_counter()
            self._play_frame_start = frame_num
        if getattr(self, "_audio_player", None) is not None and self._has_audio:
            effective_fps = getattr(self, "_effective_fps", self.fps)
            pos_ms = int(frame_num / max(1, effective_fps) * 1000)
            self._audio_player.setPosition(pos_ms)

    def play_step(self):
        if not self.is_playing:
            return

        elapsed = time.perf_counter() - self._play_clock_start
        effective_fps = getattr(self, "_effective_fps", self.fps)
        target = self._play_frame_start + int(elapsed * effective_fps * self.playback_speed)

        if target >= self.total_frames:
            if self.loop_enabled and self.total_frames > 0:
                self._play_clock_start = time.perf_counter()
                self._play_frame_start = 0
                target = 0
                if getattr(self, "_audio_player", None) is not None and self._has_audio and not self.audio_muted:
                    self._audio_player.setPosition(0)
                    self._audio_player.play()
            else:
                self.is_playing = False
                self.play_pause_btn.setText("▶")
                self.play_timer.stop()
                if getattr(self, "_audio_player", None) is not None:
                    self._audio_player.pause()
                return

        if target == self.current_frame:
            return

        self.current_frame = target
        self.load_frame(self.current_frame)
        self.update_frame_display()
        self.timeline.set_playhead(self.current_frame)
        self.overview_timeline.set_playhead(self.current_frame)
        self.sync_timeline_scroll()
        self.update_bookmark_button_state()

    def toggle_play(self):
        self.is_playing = not self.is_playing

        if self.is_playing:
            self.play_pause_btn.setText("❚❚")
            fps = self.fps
            if getattr(self.project, "is_video", False) and hasattr(
                self.project, "video_fps"
            ):
                fps = int(self.project.video_fps) if self.project.video_fps > 0 else 24

            self._effective_fps = fps
            self._play_clock_start = time.perf_counter()
            self._play_frame_start = self.current_frame

            if getattr(self, "_audio_player", None) is not None and self._has_audio and not self.audio_muted:
                pos_ms = int(self.current_frame / max(1, fps) * 1000)
                self._audio_player.setPosition(pos_ms)
                self._audio_player.setPlaybackRate(self.playback_speed)
                self._audio_player.play()

            interval = max(5, int(1000 / (fps * self.playback_speed * 2)))
            self.play_timer.start(min(15, interval))
        else:
            self.play_pause_btn.setText("▶")
            self.play_timer.stop()
            if getattr(self, "_audio_player", None) is not None:
                self._audio_player.pause()

    def prev_frame(self):
        if self.current_frame > 0:
            self.current_frame -= 1
            self.load_frame(self.current_frame)
            self.update_frame_display()
            self.timeline.set_playhead(self.current_frame)
            self.overview_timeline.set_playhead(self.current_frame)
            self.update_bookmark_button_state()
            if self.is_playing:
                self._play_clock_start = time.perf_counter()
                self._play_frame_start = self.current_frame
            if getattr(self, "_audio_player", None) is not None and self._has_audio:
                effective_fps = getattr(self, "_effective_fps", self.fps)
                pos_ms = int(self.current_frame / max(1, effective_fps) * 1000)
                self._audio_player.setPosition(pos_ms)

    def next_frame(self):
        if self.current_frame < self.total_frames - 1:
            self.current_frame += 1
            self.load_frame(self.current_frame)
            self.update_frame_display()
            self.timeline.set_playhead(self.current_frame)
            self.overview_timeline.set_playhead(self.current_frame)
            self.update_bookmark_button_state()
            if self.is_playing:
                self._play_clock_start = time.perf_counter()
                self._play_frame_start = self.current_frame
            if getattr(self, "_audio_player", None) is not None and self._has_audio:
                effective_fps = getattr(self, "_effective_fps", self.fps)
                pos_ms = int(self.current_frame / max(1, effective_fps) * 1000)
                self._audio_player.setPosition(pos_ms)

    def jump_to_start(self):
        self.current_frame = 0
        self.load_frame(0)
        self.update_frame_display()
        self.timeline.set_playhead(0)
        self.overview_timeline.set_playhead(0)
        self.update_bookmark_button_state()
        if self.is_playing:
            self._play_clock_start = time.perf_counter()
            self._play_frame_start = 0
        if getattr(self, "_audio_player", None) is not None and self._has_audio:
            self._audio_player.setPosition(0)

    def jump_to_end(self):
        self.current_frame = max(0, self.total_frames - 1)
        self.load_frame(self.current_frame)
        self.update_frame_display()
        self.timeline.set_playhead(self.current_frame)
        self.overview_timeline.set_playhead(self.current_frame)
        self.update_bookmark_button_state()
        if self.is_playing:
            self._play_clock_start = time.perf_counter()
            self._play_frame_start = self.current_frame
        if getattr(self, "_audio_player", None) is not None and self._has_audio:
            effective_fps = getattr(self, "_effective_fps", self.fps)
            pos_ms = int(self.current_frame / max(1, effective_fps) * 1000)
            self._audio_player.setPosition(pos_ms)

    def toggle_loop(self):
        self.loop_enabled = not self.loop_enabled

    def set_speed(self, speed_text):
        speed_map = {"0.25x": 0.25, "0.5x": 0.5, "1x": 1.0, "2x": 2.0}
        self.playback_speed = speed_map.get(speed_text, 1.0)

        if self.is_playing:
            self._play_clock_start = time.perf_counter()
            self._play_frame_start = self.current_frame
            effective_fps = getattr(self, "_effective_fps", self.fps)
            interval = max(5, int(1000 / (effective_fps * self.playback_speed * 2)))
            self.play_timer.setInterval(min(15, interval))
            if getattr(self, "_audio_player", None) is not None and self._has_audio:
                self._audio_player.setPlaybackRate(self.playback_speed)

    def update_frame_display(self):
        res_str = ""
        if hasattr(self, "video_width") and hasattr(self, "video_height") and self.video_width > 0:
            res_str = f" [{self.video_width}x{self.video_height}]"

        self.frame_label.setText(
            f"Frame: {self.current_frame + 1} / {self.total_frames}{res_str}"
        )
        self.update_shot_grid_action_state()

        total_seconds = self.current_frame / self.fps
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        frames = self.current_frame % self.fps
        self.timecode_label.setText(
            f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"
        )

    def show_viewer_context_menu(self, position):
        menu = QMenu(self)

        copy_action = QAction("Copy Frame to Clipboard", self)
        copy_action.triggered.connect(self.copy_frame_to_clipboard)
        copy_action.setEnabled(self.viewer.current_pixmap is not None)
        menu.addAction(copy_action)

        menu.addSeparator()

        export_current_action = QAction("Export Current Frame...", self)
        export_current_action.triggered.connect(self.export_current_frame_image)
        export_current_action.setEnabled(self.total_frames > 0)
        menu.addAction(export_current_action)

        export_first_action = QAction("Export First Frame...", self)
        export_first_action.triggered.connect(self.export_first_frame_image)
        export_first_action.setEnabled(self.total_frames > 0)
        menu.addAction(export_first_action)

        export_last_action = QAction("Export Last Frame...", self)
        export_last_action.triggered.connect(self.export_last_frame_image)
        export_last_action.setEnabled(self.total_frames > 0)
        menu.addAction(export_last_action)

        export_bookmarks_action = QAction("Export Bookmarks...", self)
        export_bookmarks_action.triggered.connect(self.show_export_bookmarks_dialog)
        export_bookmarks_action.setEnabled(bool(self.bookmarks))
        menu.addAction(export_bookmarks_action)

        menu.exec(self.viewer.mapToGlobal(position))

    def copy_frame_to_clipboard(self):
        if not self.viewer.current_pixmap:
            return
        clipboard = QApplication.clipboard()
        clipboard.setPixmap(self.viewer.current_pixmap)
        self.statusBar().showMessage("Frame copied to clipboard.", 4000)

    def export_current_frame_image(self):
        self.show_export_frame_dialog(self.current_frame, "current")

    def export_first_frame_image(self):
        if self.total_frames == 0:
            QMessageBox.warning(self, "Export", "No project loaded.")
            return
        self.show_export_frame_dialog(0, "first")

    def export_last_frame_image(self):
        if self.total_frames == 0:
            QMessageBox.warning(self, "Export", "No project loaded.")
            return
        self.show_export_frame_dialog(self.total_frames - 1, "last")

    def export_selected_bookmark_image(self, item):
        bookmark_data = item.data(Qt.ItemDataRole.UserRole)
        if not bookmark_data:
            return

        label = bookmark_data.get("name") or "bookmark"
        self.show_export_frame_dialog(bookmark_data["frame"], label)

    def show_export_frame_dialog(self, frame_num, label):
        if self.total_frames == 0:
            QMessageBox.warning(self, "Export", "No project loaded.")
            return

        default_name = build_frame_export_filename(
            self.get_loaded_source_name(),
            frame_num,
            label,
            IMAGE_EXPORT_FORMATS["PNG"]["extension"],
        )
        default_path = os.path.join(self.get_default_export_folder(), default_name)
        filepath, selected_filter = QFileDialog.getSaveFileName(
            self,
            f"Export Frame {frame_num + 1}",
            default_path,
            IMAGE_EXPORT_FILTER,
        )

        if not filepath:
            return

        format_name = normalize_image_format(filepath, selected_filter)
        filepath = ensure_extension(
            filepath, IMAGE_EXPORT_FORMATS[format_name]["extension"]
        )

        try:
            saved_paths = self.save_image_export_requests(
                [{"frame": frame_num, "path": filepath}],
                format_name,
                jpeg_quality=95,
                progress_title=f"Exporting Frame {frame_num + 1}",
            )
            self.remember_export_folder(filepath)
            self.statusBar().showMessage(
                f"Exported frame {frame_num + 1} to {os.path.basename(saved_paths[0])}.",
                4000,
            )
        except Exception as e:
            QMessageBox.warning(self, "Export Error", str(e))

    def show_export_bookmarks_dialog(self):
        if not self.bookmarks:
            QMessageBox.warning(self, "Export", "No bookmarks available to export.")
            return

        dialog = ExportBookmarksDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if dialog.is_video_mode():
            output_path = dialog.output_path.text().strip()
            if not output_path:
                QMessageBox.warning(self, "Export", "Please choose an output file.")
                return

            self.export_bookmarks_as_video(
                ensure_extension(output_path, ".mp4"),
                dialog.hold_spinbox.value(),
                dialog.fps_spinbox.value(),
                dialog.quality_slider.value(),
                dialog.speed_combo.currentText(),
            )
            return

        output_folder = dialog.output_folder.text().strip()
        if not output_folder:
            QMessageBox.warning(self, "Export", "Please choose an output folder.")
            return

        self.export_bookmarks_as_images(
            output_folder,
            dialog.filename_prefix.text().strip(),
            dialog.get_format_name(),
            jpeg_quality=dialog.jpeg_quality.value(),
        )

    def show_export_bookmarks_video_dialog(self):
        self.show_export_bookmarks_dialog()

    def build_bookmark_export_requests(self, output_folder, prefix, format_name):
        extension = IMAGE_EXPORT_FORMATS[format_name]["extension"]
        requests = []
        for bookmark_index, bookmark in enumerate(
            sorted(self.bookmarks, key=lambda bm: (bm["frame"], bm.get("name", ""))),
            start=1,
        ):
            filename = build_bookmark_export_filename(
                prefix,
                bookmark_index,
                bookmark["frame"],
                bookmark.get("name", ""),
                extension,
            )
            requests.append(
                {
                    "frame": bookmark["frame"],
                    "path": os.path.join(output_folder, filename),
                }
            )
        return requests

    def export_bookmarks_as_images(
        self, output_folder, prefix, format_name="PNG", jpeg_quality=95
    ):
        requests = self.build_bookmark_export_requests(
            output_folder, prefix or self.get_loaded_source_name(), format_name
        )
        if not requests:
            QMessageBox.warning(self, "Export", "No bookmarks available to export.")
            return

        try:
            saved_paths = self.save_image_export_requests(
                requests,
                format_name,
                jpeg_quality=jpeg_quality,
                progress_title="Exporting Bookmark Images",
            )
            self.remember_export_folder(output_folder)
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {len(saved_paths)} bookmark image(s) to {output_folder}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def build_bookmark_video_frame_numbers(self, hold_frames):
        hold_frames = max(1, int(hold_frames))
        sorted_bookmarks = sorted(
            self.bookmarks, key=lambda bm: (bm["frame"], bm.get("name", ""))
        )
        frame_numbers = []
        for bookmark in sorted_bookmarks:
            frame_numbers.extend([bookmark["frame"]] * hold_frames)
        return sorted_bookmarks, frame_numbers

    def export_bookmarks_as_video(
        self, filepath, hold_frames, export_fps, quality, preset="fast"
    ):
        hold_frames = max(1, int(hold_frames))
        export_fps = max(1, int(export_fps))
        sorted_bookmarks, frame_numbers = self.build_bookmark_video_frame_numbers(
            hold_frames
        )
        if not frame_numbers:
            QMessageBox.warning(self, "Export", "No bookmarks available to export.")
            return

        progress = QDialog(self)
        progress.setWindowTitle("Exporting Bookmark Video...")
        progress.setFixedSize(420, 140)
        prog_layout = QVBoxLayout(progress)
        status_label = QLabel()
        status_label.setWordWrap(True)
        prog_layout.addWidget(status_label)
        bar = QProgressBar()
        bar.setRange(0, len(frame_numbers))
        prog_layout.addWidget(bar)
        progress.show()

        try:
            def update_progress(output_index, total, source_frame):
                bookmark_index = min(
                    len(sorted_bookmarks), ((output_index - 1) // hold_frames) + 1
                )
                bookmark = sorted_bookmarks[bookmark_index - 1]
                bookmark_name = bookmark.get("name") or f"Bookmark {bookmark_index}"
                status_label.setText(
                    f"Encoding bookmark {bookmark_index}/{len(sorted_bookmarks)}: "
                    f"frame {source_frame + 1} ({bookmark_name})"
                )
                bar.setValue(output_index)
                QApplication.processEvents()

            self.write_mp4_file(
                filepath,
                frame_numbers,
                quality,
                preset,
                progress_callback=update_progress,
                fps=export_fps,
            )

            bar.setValue(len(frame_numbers))
            QApplication.processEvents()

            self.remember_export_folder(filepath)
            total_duration = len(frame_numbers) / export_fps
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {len(sorted_bookmarks)} bookmark(s) to {filepath}\n"
                f"Duration: {total_duration:.2f} seconds at {export_fps} fps.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))
        finally:
            progress.close()

    def save_image_export_requests(
        self, requests, format_name, jpeg_quality=95, progress_title="Exporting Images"
    ):
        import cv2
        import numpy as np
        from PIL import Image

        if not requests:
            return []

        if format_name not in IMAGE_EXPORT_FORMATS:
            raise ValueError(f"Unsupported image format: {format_name}")

        sorted_requests = sorted(requests, key=lambda request: request["frame"])

        progress = QDialog(self)
        progress.setWindowTitle(progress_title)
        progress.setFixedSize(420, 130)
        prog_layout = QVBoxLayout(progress)
        status_label = QLabel()
        status_label.setWordWrap(True)
        prog_layout.addWidget(status_label)
        bar = QProgressBar()
        bar.setRange(0, len(sorted_requests))
        prog_layout.addWidget(bar)
        progress.show()

        saved_paths = []

        try:
            for request in sorted_requests:
                os.makedirs(os.path.dirname(request["path"]), exist_ok=True)

            if getattr(self.project, "is_video", False) and hasattr(
                self.project, "video_path"
            ):
                video_path = self.project.video_path
                ext = os.path.splitext(video_path)[1].lower()

                if ext == ".gif":
                    gif = Image.open(video_path)
                    try:
                        for output_index, request in enumerate(sorted_requests, start=1):
                            status_label.setText(
                                f"Exporting frame {request['frame'] + 1} ({output_index}/{len(sorted_requests)})"
                            )
                            QApplication.processEvents()

                            gif.seek(request["frame"])
                            frame_rgb = np.array(gif.convert("RGB"))
                            self.write_rgb_image_file(
                                frame_rgb,
                                request["path"],
                                format_name,
                                jpeg_quality,
                            )

                            saved_paths.append(request["path"])
                            bar.setValue(output_index)
                            QApplication.processEvents()
                    finally:
                        gif.close()
                else:
                    cap = cv2.VideoCapture(video_path)
                    if not cap.isOpened():
                        raise ValueError(f"Could not open video for export: {video_path}")

                    try:
                        for output_index, request in enumerate(sorted_requests, start=1):
                            status_label.setText(
                                f"Exporting frame {request['frame'] + 1} ({output_index}/{len(sorted_requests)})"
                            )
                            QApplication.processEvents()

                            cap.set(cv2.CAP_PROP_POS_FRAMES, request["frame"])
                            ret, frame = cap.read()
                            if not ret:
                                raise ValueError(
                                    f"Could not read frame {request['frame']} for export."
                                )

                            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            self.write_rgb_image_file(
                                frame_rgb,
                                request["path"],
                                format_name,
                                jpeg_quality,
                            )

                            saved_paths.append(request["path"])
                            bar.setValue(output_index)
                            QApplication.processEvents()
                    finally:
                        cap.release()
            else:
                for output_index, request in enumerate(sorted_requests, start=1):
                    status_label.setText(
                        f"Exporting frame {request['frame'] + 1} ({output_index}/{len(sorted_requests)})"
                    )
                    QApplication.processEvents()

                    source_frame_path = self.get_sequence_frame_path(request["frame"])
                    if source_frame_path and self.can_copy_source_frame(
                        source_frame_path, format_name
                    ):
                        shutil.copy2(source_frame_path, request["path"])
                    else:
                        pixmap = self.load_frame_data(request["frame"])
                        if pixmap is None:
                            raise ValueError(
                                f"Could not load frame {request['frame']} for export."
                            )
                        self.write_pixmap_image_file(
                            pixmap,
                            request["path"],
                            format_name,
                            jpeg_quality,
                        )

                    saved_paths.append(request["path"])
                    bar.setValue(output_index)
                    QApplication.processEvents()
        finally:
            progress.close()

        return saved_paths

    def get_sequence_frame_path(self, frame_num):
        if not self.project.sources:
            return None

        source = self.project.sources[0]
        files = source.get("files", [])
        if 0 <= frame_num < len(files):
            return files[frame_num]
        return None

    def can_copy_source_frame(self, source_path, format_name):
        source_extension = os.path.splitext(source_path)[1].lower()
        return source_extension in IMAGE_EXPORT_FORMATS[format_name]["extensions"]

    def write_rgb_image_file(self, frame_rgb, filepath, format_name, jpeg_quality=95):
        import cv2

        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        params = []
        if format_name == "JPEG":
            params = [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)]
        elif format_name == "PNG":
            params = [cv2.IMWRITE_PNG_COMPRESSION, 1]

        if not cv2.imwrite(filepath, frame_bgr, params):
            raise ValueError(f"Failed to save image: {filepath}")

    def write_pixmap_image_file(self, pixmap, filepath, format_name, jpeg_quality=95):
        quality = int(jpeg_quality) if format_name == "JPEG" else -1
        qt_format = IMAGE_EXPORT_FORMATS[format_name]["qt_format"]
        if not pixmap.save(filepath, qt_format, quality):
            raise ValueError(f"Failed to save image: {filepath}")

    def on_viewer_click(self, frame_num):
        self.seek_to_frame(frame_num)

    def on_bookmark_clicked(self, item):
        bookmark_data = item.data(Qt.ItemDataRole.UserRole)
        if bookmark_data:
            frame = bookmark_data["frame"]
            self.seek_to_frame(frame)
            self.timeline.select_bookmark(frame)
            self.overview_timeline.select_bookmark(frame)

    def get_bookmark_for_frame(self, frame):
        for bookmark in self.bookmarks:
            if bookmark.get("frame") == frame:
                return bookmark
        return None

    def update_bookmark_button_state(self):
        if not hasattr(self, "add_bookmark_btn"):
            return

        has_bookmark = self.get_bookmark_for_frame(self.current_frame) is not None
        self.add_bookmark_btn.setEnabled(not has_bookmark)
        if hasattr(self, "remove_bookmark_btn"):
            self.remove_bookmark_btn.setEnabled(has_bookmark)
        if hasattr(self, "clear_bookmarks_btn"):
            self.clear_bookmarks_btn.setEnabled(bool(self.bookmarks))

    def remove_current_bookmark(self):
        """Remove the bookmark at the current frame."""
        if self.get_bookmark_for_frame(self.current_frame):
            self.delete_bookmark_by_frame(self.current_frame)

    def on_bookmark_selected(self, frame):
        """Sync bookmark selection across both timelines and highlight in list."""
        sender = self.sender()
        # Sync selection to the other timeline
        if sender is self.timeline:
            self.overview_timeline.selected_bookmark = frame
            self.overview_timeline.update()
        elif sender is self.overview_timeline:
            self.timeline.selected_bookmark = frame
            self.timeline.update()

        # Highlight the corresponding item in the bookmark list
        if frame >= 0:
            for i in range(self.bookmark_list.count()):
                item = self.bookmark_list.item(i)
                bm_data = item.data(Qt.ItemDataRole.UserRole)
                if bm_data and bm_data.get("frame") == frame:
                    self.bookmark_list.setCurrentItem(item)
                    return
        self.bookmark_list.clearSelection()



    def nudge_selected_bookmark(self, delta: int) -> bool:
        """Nudge whichever bookmark is currently selected by delta frames (-1 or +1)."""
        target = None
        if hasattr(self, "timeline") and self.timeline.selected_bookmark >= 0:
            target = self.timeline
        elif hasattr(self, "overview_timeline") and self.overview_timeline.selected_bookmark >= 0:
            target = self.overview_timeline

        if target is None:
            return False

        if target.total_frames <= 0 and self.total_frames > 0:
            target.set_total_frames(self.total_frames)

        old_frame = target.selected_bookmark
        new_frame = old_frame + delta
        if new_frame < 0 or new_frame >= self.total_frames:
            self.statusBar().showMessage(
                f"Cannot nudge bookmark: boundary reached (frame {new_frame + 1}).", 2000
            )
            return False
        if new_frame in target.bookmarks:
            self.statusBar().showMessage(
                f"Cannot nudge bookmark: frame {new_frame + 1} already has a bookmark.", 2000
            )
            return False

        success = target.nudge_selected_bookmark(delta)
        if success:
            self.statusBar().showMessage(f"Bookmark moved to frame {new_frame + 1}", 1500)
        return success

    def eventFilter(self, watched, event):
        if watched is getattr(self, "bookmark_list", None) and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Left:
                if self.nudge_selected_bookmark(-1):
                    return True
            elif event.key() == Qt.Key.Key_Right:
                if self.nudge_selected_bookmark(1):
                    return True
            elif event.key() == Qt.Key.Key_Escape:
                if hasattr(self, "timeline"):
                    self.timeline.clear_selection()
                if hasattr(self, "overview_timeline"):
                    self.overview_timeline.clear_selection()
                self.bookmark_list.clearSelection()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        focused = QApplication.focusWidget()
        from PyQt6.QtWidgets import QLineEdit, QAbstractSpinBox
        if isinstance(focused, (QLineEdit, QAbstractSpinBox)):
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_M:
            self.toggle_mute()
            event.accept()
            return

        has_selected = (
            (hasattr(self, "timeline") and self.timeline.selected_bookmark >= 0)
            or (hasattr(self, "overview_timeline") and self.overview_timeline.selected_bookmark >= 0)
        )

        if has_selected:
            if event.key() == Qt.Key.Key_Up:
                if self.nudge_selected_bookmark(1):
                    event.accept()
                    return
            elif event.key() == Qt.Key.Key_Down:
                if self.nudge_selected_bookmark(-1):
                    event.accept()
                    return
            elif event.key() == Qt.Key.Key_Escape:
                if hasattr(self, "timeline"):
                    self.timeline.clear_selection()
                if hasattr(self, "overview_timeline"):
                    self.overview_timeline.clear_selection()
                if hasattr(self, "bookmark_list"):
                    self.bookmark_list.clearSelection()
                event.accept()
                return

        super().keyPressEvent(event)

    def on_bookmark_moved(self, old_frame, new_frame):
        """Handle a bookmark being dragged to a new position on a timeline."""
        # Update the bookmark data
        for bm in self.bookmarks:
            if bm["frame"] == old_frame:
                bm["frame"] = new_frame
                break

        # Sync the move across both timelines
        for tl in (getattr(self, "timeline", None), getattr(self, "overview_timeline", None)):
            if tl is not None:
                if old_frame in tl.bookmarks:
                    tl.remove_bookmark(old_frame)
                tl.add_bookmark(new_frame)
                tl.selected_bookmark = new_frame
                tl.update()

        self.update_bookmark_list()
        self.update_bookmark_button_state()

    def add_bookmark(self):
        if self.total_frames == 0:
            return

        if self.get_bookmark_for_frame(self.current_frame):
            self.update_bookmark_button_state()
            return

        bookmark = {
            "frame": self.current_frame,
            "name": f"Bookmark {len(self.bookmarks) + 1}",
            "color": "#ff6b35",
        }

        self.bookmarks.append(bookmark)
        self.timeline.add_bookmark(self.current_frame)
        self.overview_timeline.add_bookmark(self.current_frame)
        self.timeline.select_bookmark(self.current_frame)
        self.overview_timeline.select_bookmark(self.current_frame)
        self.update_bookmark_list()
        self.update_bookmark_button_state()

    def update_bookmark_list(self):
        self.bookmark_list.clear()

        for bm in sorted(self.bookmarks, key=lambda x: x["frame"]):
            item = QListWidgetItem(f"Frame {bm['frame'] + 1}: {bm['name']}")
            item.setData(Qt.ItemDataRole.UserRole, bm)

            color = QColor(bm.get("color", "#ff6b35"))
            item.setForeground(color)

            self.bookmark_list.addItem(item)

        if hasattr(self, "timeline") and self.timeline.selected_bookmark >= 0:
            for i in range(self.bookmark_list.count()):
                item = self.bookmark_list.item(i)
                bm_data = item.data(Qt.ItemDataRole.UserRole)
                if bm_data and bm_data.get("frame") == self.timeline.selected_bookmark:
                    self.bookmark_list.setCurrentItem(item)
                    break

        if hasattr(self, "clear_bookmarks_btn"):
            self.clear_bookmarks_btn.setEnabled(bool(self.bookmarks))
        self.update_bookmark_button_state()

    def show_bookmark_context_menu(self, position):
        item = self.bookmark_list.itemAt(position)
        if item:
            menu = QMenu()
            export_action = QAction("Export Bookmark Image...", self)
            export_action.triggered.connect(
                lambda: self.export_selected_bookmark_image(item)
            )
            menu.addAction(export_action)

            export_all_action = QAction("Export Bookmarks...", self)
            export_all_action.triggered.connect(self.show_export_bookmarks_dialog)
            export_all_action.setEnabled(bool(self.bookmarks))
            menu.addAction(export_all_action)

            menu.addSeparator()
            clear_action = QAction("Delete All Bookmarks", self)
            clear_action.triggered.connect(self.delete_all_bookmarks)
            clear_action.setEnabled(bool(self.bookmarks))
            menu.addAction(clear_action)

            menu.addSeparator()
            delete_action = QAction("Delete Bookmark", self)
            delete_action.triggered.connect(lambda: self.delete_bookmark(item))
            menu.addAction(delete_action)
            menu.exec(self.bookmark_list.mapToGlobal(position))

    def delete_bookmark_by_frame(self, frame):
        if self.get_bookmark_for_frame(frame) is None:
            self.update_bookmark_button_state()
            return
        self.bookmarks = [b for b in self.bookmarks if b["frame"] != frame]
        self.timeline.remove_bookmark(frame)
        self.overview_timeline.remove_bookmark(frame)
        # Clear selection on both timelines if needed
        if self.timeline.selected_bookmark == frame:
            self.timeline.selected_bookmark = -1
        if self.overview_timeline.selected_bookmark == frame:
            self.overview_timeline.selected_bookmark = -1
        self.update_bookmark_list()

    def delete_bookmark(self, item):
        bookmark_data = item.data(Qt.ItemDataRole.UserRole)
        if bookmark_data:
            self.delete_bookmark_by_frame(bookmark_data["frame"])

    def delete_all_bookmarks(self):
        if not self.bookmarks:
            self.update_bookmark_button_state()
            return

        reply = QMessageBox.question(
            self,
            "Delete All Bookmarks",
            "Delete all bookmarks from this clip?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.bookmarks = []
        self.timeline.bookmarks.clear()
        self.timeline.selected_bookmark = -1
        self.timeline.update()
        self.overview_timeline.bookmarks.clear()
        self.overview_timeline.selected_bookmark = -1
        self.overview_timeline.update()
        self.update_bookmark_list()

    def save_project(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "", "Keyframe Pro Project (*.kfp_basic)"
        )

        if filepath:
            if not filepath.endswith(".kfp_basic"):
                filepath += ".kfp_basic"

            self.save_project_to_file(filepath)

    def save_project_to_file(self, filepath):
        project_data = {
            "version": "1.0",
            "sources": [],
            "timeline": {
                "current": self.current_frame,
                "inPoint": 0,
                "outPoint": self.total_frames - 1,
            },
            "bookmarks": self.bookmarks,
            "view": {
                "panX": self.view_pan.x(),
                "panY": self.view_pan.y(),
                "zoom": self.view_zoom,
            },
            "settings": {"fps": self.fps, "loop": self.loop_enabled},
        }

        # Save video source info if loaded from a video file
        if getattr(self.project, "is_video", False) and hasattr(self.project, "video_path"):
            project_data["video_path"] = self.project.video_path
            project_data["is_video"] = True
        elif self.project.sources:
            source = self.project.sources[0]
            project_data["sources"].append(
                {
                    "path": source.get("relative_path", source.get("folder", "")),
                    "absolute": source.get("folder", ""),
                    "start": 0,
                    "end": self.total_frames - 1,
                }
            )

        with open(filepath, "w") as f:
            json.dump(project_data, f, indent=2)

        self.status_bar.showMessage(f"Project saved to {filepath}", 3000)

    def load_project(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Load Project", "", "Keyframe Pro Project (*.kfp_basic)"
        )

        if filepath:
            self.load_project_from_file(filepath)

    def load_project_from_file(self, filepath):
        try:
            with open(filepath, "r") as f:
                project_data = json.load(f)

            media_loaded = False

            # Try loading as a video project first
            if project_data.get("is_video") and project_data.get("video_path"):
                video_path = project_data["video_path"]
                if os.path.exists(video_path):
                    media_loaded = self.load_video(video_path, add_to_recent=False)
                else:
                    QMessageBox.warning(
                        self,
                        "Missing Video",
                        f"Video file not found:\n{video_path}",
                    )
            # Fall back to folder-based source
            elif project_data.get("sources"):
                source_data = project_data["sources"][0]
                folder = source_data.get("absolute", source_data.get("path", ""))
                if os.path.exists(folder):
                    self.project.folder = folder
                    media_loaded = self.scan_folder(folder, add_to_recent=False)
                else:
                    QMessageBox.warning(
                        self,
                        "Missing Folder",
                        f"Source folder not found:\n{folder}",
                    )

            if media_loaded:
                if "timeline" in project_data:
                    self.current_frame = project_data["timeline"].get("current", 0)
                    self.seek_to_frame(self.current_frame)

                if "bookmarks" in project_data:
                    self.bookmarks = project_data["bookmarks"]
                    self.update_bookmark_list()
                    for bm in self.bookmarks:
                        self.timeline.add_bookmark(bm["frame"])
                        self.overview_timeline.add_bookmark(bm["frame"])

                if "view" in project_data:
                    view = project_data["view"]
                    self.view_pan = QPointF(
                        view.get("panX", 0), view.get("panY", 0)
                    )
                    self.view_zoom = view.get("zoom", 1.0)

                if "settings" in project_data:
                    settings = project_data["settings"]
                    self.fps = settings.get("fps", 24)
                    self.loop_enabled = settings.get("loop", False)
                    self.fps_label.setText(f"{self.fps} FPS")
                    self.loop_btn.setChecked(self.loop_enabled)

            self.add_recent_file(filepath, "project")
            self.status_bar.showMessage(f"Project loaded from {filepath}", 3000)

        except Exception as e:
            QMessageBox.warning(self, "Error Loading Project", str(e))

    def auto_save(self):
        if self.project.folder and self.bookmarks:
            autosave_path = os.path.join(
                self.project.folder, ".kfpro_autosave.kfp_basic"
            )
            self.save_project_to_file(autosave_path)

    def show_export_dialog(self):
        dialog = ExportDialog(self)
        dialog.exec()

    def show_export_mp4_dialog(self):
        if self.total_frames == 0:
            QMessageBox.warning(self, "Export", "No project loaded.")
            return

        dialog = ExportMp4Dialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            start_frame = dialog.start_spinbox.value()
            end_frame = dialog.end_spinbox.value()
            quality = dialog.quality_slider.value()
            preset = dialog.speed_combo.currentText()

            if start_frame > end_frame:
                QMessageBox.warning(
                    self, "Invalid Range", "Start frame must be before end frame."
                )
                return

            filepath, _ = QFileDialog.getSaveFileName(
                self, "Export MP4", "", "MP4 Video (*.mp4)"
            )
            include_audio = getattr(dialog, "include_audio_checkbox", None) and dialog.include_audio_checkbox.isChecked()
            if filepath:
                self.export_mp4(filepath, start_frame, end_frame, quality, preset, include_audio=include_audio)

    def show_wan_preparation_dialog(self):
        if self.total_frames == 0:
            QMessageBox.warning(self, "Export", "No project loaded.")
            return

        dialog = WanPreparationDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            output_folder = dialog.output_folder.text().strip()
            prefix = dialog.filename_prefix.text().strip()
            chunk_size = dialog.get_chunk_size()
            overlap = dialog.get_overlap()
            quality = dialog.quality_slider.value()
            preset = dialog.speed_combo.currentText()
            start_frame = dialog.start_spinbox.value()
            end_frame = dialog.end_spinbox.value()
            grid_size = dialog.grid_combo.currentData()
            per_chunk_grid = dialog.per_chunk_grid_checkbox.isChecked()

            if start_frame > end_frame:
                QMessageBox.warning(self, "Invalid Range", "Start frame must be before end frame.")
                return

            if not output_folder:
                QMessageBox.warning(self, "Export", "Please choose an output folder.")
                return

            include_audio = getattr(dialog, "include_audio_checkbox", None) and dialog.include_audio_checkbox.isChecked()
            self.prepare_wan(
                output_folder, prefix, chunk_size, overlap, quality, preset,
                start_frame, end_frame, grid_size, per_chunk_grid, include_audio=include_audio
            )

    def show_minimax_preparation_dialog(self):
        if self.total_frames == 0:
            QMessageBox.warning(self, "Export", "No project loaded.")
            return

        dialog = MinimaxPreparationDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            output_folder = dialog.output_folder.text().strip()
            prefix = dialog.filename_prefix.text().strip()
            chunk_size = dialog.get_chunk_size()
            overlap = dialog.get_overlap()
            quality = dialog.quality_slider.value()
            preset = dialog.speed_combo.currentText()
            start_frame = dialog.start_spinbox.value()
            end_frame = dialog.end_spinbox.value()
            grid_size = dialog.grid_combo.currentData()
            per_chunk_grid = dialog.per_chunk_grid_checkbox.isChecked()
            include_audio = getattr(dialog, "include_audio_checkbox", None) and dialog.include_audio_checkbox.isChecked()

            if start_frame > end_frame:
                QMessageBox.warning(self, "Invalid Range", "Start frame must be before end frame.")
                return

            if not output_folder:
                QMessageBox.warning(self, "Export", "Please choose an output folder.")
                return

            self.prepare_minimax(
                output_folder, prefix, chunk_size, overlap, quality, preset,
                start_frame, end_frame, grid_size, per_chunk_grid, include_audio=include_audio
            )

    def prepare_minimax(
        self, output_folder, prefix, chunk_size, overlap, quality, preset,
        start_frame, end_frame, grid_size, per_chunk_grid=False, include_audio=False
    ):
        chunk_size = normalize_minimax_chunk_size(chunk_size)
        overlap = normalize_minimax_overlap(overlap, chunk_size)
        
        total_frames_to_chunk = end_frame - start_frame + 1
        chunk_plan = plan_minimax_chunks(total_frames_to_chunk, chunk_size, overlap)
        if not chunk_plan:
            QMessageBox.warning(self, "Export", "No frames available for export.")
            return

        prefix = sanitize_filename_part(prefix)
        
        num_chunks = len(chunk_plan)
        preferred_dim = None
        if grid_size == "2x2": preferred_dim = 2
        elif grid_size == "3x3": preferred_dim = 3
        
        dims = [preferred_dim] if preferred_dim else [3, 2]
        if num_chunks == 1 and not preferred_dim:
            best_k, best_dim = 4, 2
        elif num_chunks == 3 and not preferred_dim:
            best_k, best_dim = 3, 3
        else:
            best_k, best_dim = None, None
            for k in range(3, 6):
                for dim in dims:
                    cap = dim * dim
                    if (num_chunks * k) % cap == 0:
                        best_k, best_dim = k, dim
                        break
                if best_k is not None:
                    break
            
            if best_k is None:
                best_k = 3
                if preferred_dim:
                    best_dim = preferred_dim
                else:
                    best_dim = dims[0]
                    best_waste = float("inf")
                    for dim in dims:
                        cap = dim * dim
                        waste = (cap - ((num_chunks * best_k) % cap)) % cap
                        if waste < best_waste:
                            best_waste = waste
                            best_dim = dim

        cap = best_dim * best_dim
        if per_chunk_grid:
            k_list = [cap] * num_chunks
            best_k = cap
        else:
            base_total = num_chunks * best_k
            missing = (cap - (base_total % cap)) % cap
            k_list = [best_k] * num_chunks
            for i in range(missing):
                k_list[i % num_chunks] += 1

        review_data = []
        for chunk_index, chunk in enumerate(chunk_plan):
            abs_start = start_frame + chunk.start_frame
            abs_end_raw = start_frame + chunk.end_frame
            abs_end = min(abs_end_raw, end_frame)

            k_i = k_list[chunk_index]
            span = abs_end - abs_start
            if span == 0:
                indices = [abs_start] * k_i
            else:
                indices = [abs_start + i * span // (k_i - 1) for i in range(k_i)]

            review_data.append({
                "chunk_index": chunk_index,
                "abs_start": abs_start,
                "abs_end": abs_end,
                "selected_frames": list(indices),
            })

        review = WanFrameReviewDialog(self, review_data, self.load_frame_data)
        if review.exec() != QDialog.DialogCode.Accepted:
            return

        reviewed_data = review.get_all_selected_frames()
        total_mp4_frames = sum(chunk.target_length for chunk in chunk_plan)

        progress = QDialog(self)
        progress.setWindowTitle("MiniMax H3 Preparation...")
        progress.setFixedSize(420, 130)
        prog_layout = QVBoxLayout(progress)
        status_label = QLabel()
        status_label.setWordWrap(True)
        prog_layout.addWidget(status_label)
        bar = QProgressBar()
        bar.setRange(0, total_mp4_frames)
        prog_layout.addWidget(bar)
        progress.show()

        completed_frames = 0
        all_images = []
        selection_details = []

        import cv2
        import numpy as np
        from dataclasses import asdict

        try:
            os.makedirs(output_folder, exist_ok=True)

            for chunk_index, chunk in enumerate(chunk_plan, start=1):
                abs_start = start_frame + chunk.start_frame
                abs_end_raw = start_frame + chunk.end_frame
                abs_end = min(abs_end_raw, end_frame)
                
                chunk_dir_name = f"{prefix}_chunk_{chunk_index:03d}"
                chunk_dir = os.path.join(output_folder, chunk_dir_name)
                os.makedirs(chunk_dir, exist_ok=True)

                filename = (
                    f"{prefix}_minimax_h3_{chunk_index:03d}_"
                    f"{chunk.target_length:03d}f_"
                    f"{abs_start:04d}-{abs_end:04d}.mp4"
                )
                filepath = os.path.join(chunk_dir, filename)

                frame_numbers = list(range(abs_start, abs_end + 1))
                pad_needed = chunk.target_length - len(frame_numbers)
                if pad_needed > 0:
                    frame_numbers.extend([abs_end] * pad_needed)

                status_label.setText(
                    f"Processing chunk {chunk_index}/{len(chunk_plan)}: "
                    f"frames {abs_start}-{abs_end}"
                )
                QApplication.processEvents()

                def update_progress(output_index, total, source_frame, base=completed_frames):
                    bar.setValue(base + output_index)
                    QApplication.processEvents()

                write_kwargs = {}
                if include_audio:
                    write_kwargs["include_audio"] = True
                    write_kwargs["audio_start_frame"] = abs_start
                    write_kwargs["audio_end_frame"] = abs_end
                self.write_mp4_file(
                    filepath,
                    frame_numbers,
                    quality,
                    preset,
                    progress_callback=update_progress,
                    **write_kwargs
                )

                completed_frames += len(frame_numbers)
                reviewed_indices = reviewed_data[chunk_index - 1]["selected_frames"]

                chunk_images = []
                for i, idx in enumerate(reviewed_indices):
                    pixmap = self.load_frame_data(idx)
                    if pixmap:
                        img_rgb = self.pixmap_to_rgb_array(pixmap)
                        chunk_images.append(img_rgb)
                        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                        frame_filename = f"{prefix}_chunk_{chunk_index:03d}_frame_{i+1:02d}_f{idx:04d}.jpg"
                        frame_path = os.path.join(chunk_dir, frame_filename)
                        cv2.imwrite(frame_path, img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    else:
                        chunk_images.append(np.zeros((256, 256, 3), dtype=np.uint8))
                        
                status_label.setText(
                    f"Processing chunk {chunk_index}/{len(chunk_plan)}: "
                    f"Writing 1fps keyframe video..."
                )
                QApplication.processEvents()
                
                video_1fps_filename = f"{prefix}_chunk_{chunk_index:03d}_1fps.mp4"
                video_1fps_path = os.path.join(chunk_dir, video_1fps_filename)
                self.write_mp4_file(
                    video_1fps_path,
                    reviewed_indices,
                    quality,
                    preset,
                    progress_callback=None,
                    fps=1,
                )

                all_images.extend(chunk_images)
                selection_details.append({
                    "chunk_index": chunk_index - 1,
                    "chunk_data": asdict(chunk),
                    "video_start_frame_abs": abs_start,
                    "video_end_frame_abs": abs_end,
                    "selected_frames_abs": reviewed_indices
                })

            bar.setValue(total_mp4_frames)
            QApplication.processEvents()
            
            status_label.setText("Generating grids and metadata...")
            QApplication.processEvents()
            
            cap = best_dim * best_dim
            grids = []
            if all_images:
                h, w = all_images[0].shape[:2]
                for i in range(0, len(all_images), cap):
                    batch = all_images[i:i+cap]
                    while len(batch) < cap:
                        batch.append(None)
                    grids.append(
                        compose_grid(
                            batch,
                            rows=best_dim,
                            cols=best_dim,
                            cell_size=(w, h),
                        )
                    )
            
            saved_grids = []
            for i, grid in enumerate(grids):
                if per_chunk_grid:
                    chunk_dir_name = f"{prefix}_chunk_{i+1:03d}"
                    grid_filename = f"{prefix}_chunk_{i+1:03d}_grid_{best_dim}x{best_dim}.jpg"
                    grid_path = os.path.join(output_folder, chunk_dir_name, grid_filename)
                    saved_grids.append(f"{chunk_dir_name}/{grid_filename}")
                else:
                    grid_filename = f"{prefix}_grid_{best_dim}x{best_dim}_{i:03d}.jpg"
                    grid_path = os.path.join(output_folder, grid_filename)
                    saved_grids.append(grid_filename)
                
                frame_bgr = cv2.cvtColor(grid, cv2.COLOR_RGB2BGR)
                params = [cv2.IMWRITE_JPEG_QUALITY, 95]
                cv2.imwrite(grid_path, frame_bgr, params)
                
            metadata = {}
            for detail in selection_details:
                chunk_num = detail["chunk_index"] + 1
                start_f = detail["video_start_frame_abs"]
                metadata[f"chunk {chunk_num}"] = [f - start_f for f in detail["selected_frames_abs"]]
            
            metadata.update({
                "model": "MiniMax H3",
                "formula": "17k + 5",
                "start_frame": start_frame,
                "end_frame": end_frame,
                "total_frames_processed": total_frames_to_chunk,
                "chunk_size": chunk_size,
                "overlap": overlap,
                "num_chunks": num_chunks,
                "k_frames_per_chunk": best_k,
                "grid_dim": best_dim,
                "output_grids": saved_grids,
                "chunks": selection_details
            })
            
            with open(os.path.join(output_folder, f"{prefix}_minimax_h3_preparation.json"), "w") as f:
                json.dump(metadata, f, indent=4)

            QMessageBox.information(
                self,
                "Preparation Complete",
                f"Successfully prepared {num_chunks} MiniMax H3 clip(s) and metadata in {output_folder}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Preparation Error", str(e))
        finally:
            progress.close()

    def show_grid_splitter_dialog(self):
        default_folder = self.get_default_export_folder()

        setup = GridSplitterSetupDialog(self, default_folder=default_folder)
        if setup.exec() != QDialog.DialogCode.Accepted:
            return
        data = setup.result_data()
        splitter = SmartGridSplitterDialog(self, data)
        splitter.exec()

    def build_shot_grid_media(self):
        """Describe the currently loaded clip in a Qt-free form for export."""
        if self.total_frames <= 0:
            return None

        source_name = self.get_loaded_source_name()
        fps = float(self.fps or 24)

        if getattr(self.project, "is_video", False) and getattr(
            self.project, "video_path", ""
        ):
            path = self.project.video_path
            kind = (
                "gif"
                if os.path.splitext(path)[1].lower() == ".gif"
                else "video"
            )
            return ShotGridMedia(
                source_name=source_name,
                total_frames=int(self.total_frames),
                fps=fps,
                kind=kind,
                path=path,
                width=int(getattr(self, "video_width", 0) or 0),
                height=int(getattr(self, "video_height", 0) or 0),
            )

        files = []
        if self.project.sources:
            files = list(self.project.sources[0].get("files", []) or [])
        if not files and self.project.folder:
            from viewer import detect_sequence

            sequences = detect_sequence(self.project.folder)
            if sequences:
                files = list(sequences[0]["files"])
        if not files:
            return None

        return ShotGridMedia(
            source_name=source_name,
            total_frames=int(self.total_frames),
            fps=fps,
            kind="sequence",
            files=tuple(files),
            width=int(getattr(self, "video_width", 0) or 0),
            height=int(getattr(self, "video_height", 0) or 0),
        )

    def show_shot_grid_dialog(self):
        if self.total_frames == 0:
            QMessageBox.warning(self, "Shot Grids", "No project loaded.")
            return

        media = self.build_shot_grid_media()
        if media is None:
            QMessageBox.warning(
                self,
                "Shot Grids",
                "Could not find readable frames for the loaded clip.",
            )
            return

        dialog = ShotGridDialog(
            self,
            media=media,
            bookmarks=self.bookmarks,
            settings=self.shot_grid_settings,
            default_folder=self.get_default_export_folder(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        result = show_shot_grid_export(self, dialog)
        if result is not None and result.image_count:
            if dialog.export_options is not None:
                self.remember_export_folder(dialog.export_options.output_folder)

    def show_gemma_shot_detection_dialog(self):
        if self.total_frames == 0:
            QMessageBox.warning(self, "Shot Detection", "No project loaded.")
            return

        dialog = GemmaShotDetectionDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        output_folder = dialog.output_folder.text().strip()
        prefix = dialog.filename_prefix.text().strip()
        model_name = dialog.model_combo.currentData()
        api_key = dialog.api_key.text().strip() or self.get_configured_google_api_key()
        start_frame = dialog.start_spinbox.value()
        end_frame = dialog.end_spinbox.value()
        add_bookmarks = dialog.add_bookmarks_checkbox.isChecked()
        clear_existing = dialog.clear_bookmarks_checkbox.isChecked()

        if start_frame > end_frame:
            QMessageBox.warning(
                self, "Invalid Range", "Start frame must be before end frame."
            )
            return

        if not output_folder:
            QMessageBox.warning(
                self, "Shot Detection", "Please choose an output folder."
            )
            return

        if not api_key:
            QMessageBox.warning(
                self,
                "Shot Detection",
                "Enter a Google API key or set GOOGLE_API_KEY / GEMINI_API_KEY in .env.",
            )
            return

        if self.is_dummy_google_api_key(api_key):
            QMessageBox.warning(
                self,
                "Shot Detection",
                "The fallback API key is still the dummy placeholder from .env. Replace it with your real Google AI Studio key, or paste a key into the dialog.",
            )
            return

        self.detect_shots_with_gemma(
            output_folder,
            prefix,
            model_name,
            api_key,
            start_frame,
            end_frame,
            add_bookmarks=add_bookmarks,
            clear_existing=clear_existing,
        )

    def _resize_rgb_frame(self, frame_rgb, max_dimension=None):
        if not max_dimension:
            return frame_rgb

        import cv2

        height, width = frame_rgb.shape[:2]
        longest_side = max(height, width)
        if longest_side <= max_dimension:
            return frame_rgb

        scale = max_dimension / float(longest_side)
        new_width = max(1, int(round(width * scale)))
        new_height = max(1, int(round(height * scale)))
        return cv2.resize(
            frame_rgb,
            (new_width, new_height),
            interpolation=cv2.INTER_AREA,
        )

    def get_rgb_frame_array(self, frame_num, max_dimension=None):
        pixmap = self.load_frame_data(frame_num)
        if pixmap is None:
            raise ValueError(f"Could not load frame {frame_num}.")
        frame_rgb = self.pixmap_to_rgb_array(pixmap)
        return self._resize_rgb_frame(frame_rgb, max_dimension=max_dimension)

    def iter_source_rgb_frames(self, start_frame, end_frame, max_dimension=None):
        import cv2
        import numpy as np
        from PIL import Image

        if start_frame > end_frame:
            return

        if getattr(self.project, "is_video", False) and hasattr(self.project, "video_path"):
            video_path = self.project.video_path
            ext = os.path.splitext(video_path)[1].lower()

            if ext == ".gif":
                gif = Image.open(video_path)
                try:
                    for frame_index in range(start_frame, end_frame + 1):
                        gif.seek(frame_index)
                        frame_rgb = np.array(gif.convert("RGB"))
                        yield frame_index, self._resize_rgb_frame(
                            frame_rgb, max_dimension=max_dimension
                        )
                finally:
                    gif.close()
                return

            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise ValueError(f"Could not open video for analysis: {video_path}")

            try:
                cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                frame_index = start_frame
                while frame_index <= end_frame:
                    ret, frame_bgr = cap.read()
                    if not ret:
                        raise ValueError(f"Could not read frame {frame_index}.")
                    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                    yield frame_index, self._resize_rgb_frame(
                        frame_rgb, max_dimension=max_dimension
                    )
                    frame_index += 1
            finally:
                cap.release()
            return

        if not self.project.sources:
            raise ValueError("No source media is available for analysis.")

        source = self.project.sources[0]
        files = source.get("files", [])
        for frame_index in range(start_frame, end_frame + 1):
            if frame_index >= len(files):
                raise ValueError(f"Frame {frame_index} is outside the loaded sequence.")
            with Image.open(files[frame_index]) as image:
                frame_rgb = np.array(image.convert("RGB"))
            yield frame_index, self._resize_rgb_frame(
                frame_rgb, max_dimension=max_dimension
            )

    def scan_traditional_cut_candidates(
        self,
        start_frame,
        end_frame,
        fps,
        progress_callback=None,
    ):
        import cv2
        import numpy as np

        scores = []
        previous_hist = None
        previous_gray = None
        previous_gray_mean = 0.0
        previous_edges = None
        total_frames = max(1, end_frame - start_frame + 1)

        for processed_index, (_frame_index, frame_rgb) in enumerate(
            self.iter_source_rgb_frames(start_frame, end_frame, max_dimension=256),
            start=1,
        ):
            gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
            hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
            cv2.normalize(hist, hist)
            edges = cv2.Canny(gray, 40, 120)
            gray_mean = float(gray.mean())

            if previous_hist is not None:
                hist_diff = float(
                    cv2.compareHist(previous_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
                )
                gray_diff = float(
                    np.mean(
                        np.abs(
                            gray.astype(np.int16) - previous_gray.astype(np.int16)
                        )
                    )
                ) / 255.0
                edge_diff = float(np.mean(edges != previous_edges))
                luminance_jump = abs(gray_mean - previous_gray_mean) / 255.0
                score = (
                    (hist_diff * 0.52)
                    + (gray_diff * 0.25)
                    + (edge_diff * 0.13)
                    + (luminance_jump * 0.10)
                )
                scores.append(score)

            previous_hist = hist
            previous_gray = gray
            previous_gray_mean = gray_mean
            previous_edges = edges

            if progress_callback and (
                processed_index == 1
                or processed_index == total_frames
                or processed_index % 48 == 0
            ):
                progress_callback(processed_index / total_frames)

        candidates = detect_cut_candidates_from_scores(scores, start_frame, fps)
        return candidates, scores

    def write_analysis_clip(
        self,
        filepath,
        start_frame,
        end_frame,
        fps,
        progress_callback=None,
    ):
        import imageio

        output_dir = os.path.dirname(filepath)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        total_frames = max(1, end_frame - start_frame + 1)
        writer = imageio.get_writer(
            filepath,
            format="FFMPEG",
            mode="I",
            fps=fps,
            codec="libx264",
            macro_block_size=None,
            quality=None,
            output_params=["-crf", "26", "-preset", "ultrafast"],
        )

        try:
            for output_index, (_frame_index, frame_rgb) in enumerate(
                self.iter_source_rgb_frames(start_frame, end_frame, max_dimension=960),
                start=1,
            ):
                writer.append_data(frame_rgb)
                if progress_callback and (
                    output_index == 1
                    or output_index == total_frames
                    or output_index % 48 == 0
                ):
                    progress_callback(output_index / total_frames)
        finally:
            writer.close()

    def wait_for_gemma_file_ready(self, client, uploaded_file, status_callback=None):
        import time

        current = uploaded_file
        for _ in range(180):
            state = getattr(getattr(current, "state", None), "name", "")
            if state != "PROCESSING":
                if state == "FAILED":
                    raise ValueError(
                        f"Google rejected the uploaded video file: {getattr(current, 'name', '')}"
                    )
                return current

            if status_callback:
                status_callback("Waiting for Google to finish processing the clip...")
            QApplication.processEvents()
            time.sleep(2)
            current = self.run_gemma_with_retry(
                lambda: client.files.get(name=current.name),
                "Checking uploaded chunk status",
                status_callback=status_callback,
                max_attempts=3,
                base_delay_seconds=1.5,
            )

        raise TimeoutError("Timed out while waiting for Google to process the clip.")

    def import_gemma_sdk(self):
        try:
            from google import genai
            from google.genai import types
            from google.genai import errors
            return genai, types, errors
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.startswith("google"):
                raise RuntimeError(
                    "The Gemma shot detector needs the `google-genai` package in the same Python environment that launches KFPlayer. "
                    "Install it with `.venv\\Scripts\\python.exe -m pip install -r requirements.txt`, then restart the app."
                ) from exc
            raise

    def get_configured_google_api_key(self):
        return (
            os.environ.get("GOOGLE_API_KEY", "").strip()
            or os.environ.get("GEMINI_API_KEY", "").strip()
        )

    def is_dummy_google_api_key(self, api_key):
        return (api_key or "").strip() in self.DUMMY_API_KEYS

    def is_retryable_gemma_error(self, exc):
        _genai, _types, errors = self.import_gemma_sdk()
        if isinstance(exc, (errors.ServerError, TimeoutError)):
            return True
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and status_code >= 500:
            return True
        message = str(exc).upper()
        return " 500 " in message or "'CODE': 500" in message or '"CODE": 500' in message

    def run_gemma_with_retry(
        self,
        operation,
        action_label,
        status_callback=None,
        max_attempts=4,
        base_delay_seconds=2.0,
    ):
        import time

        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                return operation()
            except Exception as exc:
                last_exc = exc
                if not self.is_retryable_gemma_error(exc) or attempt >= max_attempts:
                    break

                wait_seconds = base_delay_seconds * (2 ** (attempt - 1))
                if status_callback:
                    status_callback(
                        f"{action_label} failed with a temporary Google error. "
                        f"Retrying in {wait_seconds:.0f}s ({attempt}/{max_attempts})..."
                    )
                QApplication.processEvents()
                time.sleep(wait_seconds)

        raise RuntimeError(
            f"{action_label} failed after {max_attempts} attempts. "
            f"Google kept returning a temporary server error.\n\nLast error: {last_exc}"
        ) from last_exc

    def analyze_chunk_with_gemma(
        self,
        client,
        model_name,
        clip_path,
        chunk,
        status_callback=None,
    ):
        _genai, types, _errors = self.import_gemma_sdk()

        system_prompt = (
            "You are an expert film editor and hard-cut boundary analyst. "
            "Return strict JSON only."
        )
        prompt = f"""
Analyze this video chunk and identify only shots separated by real edits.

Chunk details:
- Duration: {chunk.duration_seconds:.3f} seconds
- Return times relative to the start of this chunk

Return only JSON in this shape:
{{
  "first_shot_signature": "short phrase",
  "last_shot_signature": "short phrase",
  "shots": [
    {{
      "start_seconds": 0.0,
      "description": "Concrete visual description of the shot after the cut: subject, framing, angle, background.",
      "continues_from_previous": false,
      "continues_to_next": false,
      "confidence": 0.0
    }}
  ]
}}

Rules:
- Include the first visible shot at the top of the chunk, even if it started before this chunk.
- Add a new entry only when there is an actual edit boundary or cut to a different shot.
- Do not create a new shot for zooms, pans, tilts, dollies, handheld drift, reframing, rack focus, character movement, or a close-up widening within one continuous take.
- If the camera keeps rolling and the viewpoint evolves continuously, that is still one shot.
- Keep descriptions concise and specific.
- Set continues_from_previous on the first shot if the chunk begins mid-shot.
- Set continues_to_next on the last shot if the chunk ends before that shot ends.
- Confidence must be between 0 and 1.
- If there are no edits inside the chunk, return exactly one shot entry.
        - No markdown, no prose, no explanations outside JSON.
""".strip()

        if status_callback:
            status_callback(f"Uploading chunk {chunk.index + 1} to Gemma...")
        uploaded_file = self.run_gemma_with_retry(
            lambda: client.files.upload(file=clip_path),
            f"Uploading chunk {chunk.index + 1}",
            status_callback=status_callback,
        )
        uploaded_file = self.wait_for_gemma_file_ready(client, uploaded_file, status_callback)

        if status_callback:
            status_callback(f"Gemma is analyzing chunk {chunk.index + 1}...")
        response = self.run_gemma_with_retry(
            lambda: client.models.generate_content(
                model=model_name,
                contents=[prompt, uploaded_file],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    thinking_config=types.ThinkingConfig(thinking_level="high"),
                ),
            ),
            f"Analyzing chunk {chunk.index + 1}",
            status_callback=status_callback,
        )

        try:
            shots, first_signature, last_signature = parse_chunk_shot_response(
                response.text, chunk.duration_seconds
            )
            if not shots:
                shots = [
                    GemmaShot(
                        start_seconds=0.0,
                        description="Unspecified continuing shot.",
                        continues_from_previous=chunk.index > 0,
                        continues_to_next=True,
                        confidence=0.0,
                    )
                ]
            return ChunkShotAnalysis(
                chunk=chunk,
                shots=shots,
                first_shot_signature=first_signature,
                last_shot_signature=last_signature,
                raw_response=response.text,
            )
        finally:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass

    def build_candidate_contact_sheet(self, rows, title):
        from PIL import Image, ImageDraw, ImageOps

        tile_width = 320
        tile_height = 180
        header_height = 38
        row_gap = 12
        margin = 20
        canvas_width = margin * 2 + (tile_width * 2) + 24
        canvas_height = margin * 2 + header_height + (
            len(rows) * (tile_height + row_gap + header_height)
        )
        canvas = Image.new("RGB", (canvas_width, canvas_height), color=(245, 245, 245))
        draw = ImageDraw.Draw(canvas)
        draw.text((margin, margin), title, fill=(0, 0, 0))

        y = margin + header_height
        for row in rows:
            before_image = Image.fromarray(row["before_rgb"])
            after_image = Image.fromarray(row["after_rgb"])

            before_tile = ImageOps.pad(
                before_image,
                (tile_width, tile_height),
                color=(24, 24, 24),
                centering=(0.5, 0.5),
            )
            after_tile = ImageOps.pad(
                after_image,
                (tile_width, tile_height),
                color=(24, 24, 24),
                centering=(0.5, 0.5),
            )

            row_label = (
                f"{row['id']}  {row['before_timestamp']} -> {row['after_timestamp']}"
            )
            draw.text((margin, y), row_label, fill=(0, 0, 0))
            image_y = y + 24
            canvas.paste(before_tile, (margin, image_y))
            canvas.paste(after_tile, (margin + tile_width + 24, image_y))
            draw.text((margin, image_y + tile_height + 4), "Before", fill=(0, 0, 0))
            draw.text(
                (margin + tile_width + 24, image_y + tile_height + 4),
                "After",
                fill=(0, 0, 0),
            )
            y = image_y + tile_height + row_gap + 20

        return canvas

    def validate_candidate_rows_with_gemma(
        self,
        client,
        model_name,
        rows,
        status_callback=None,
        prompt_context="",
    ):
        _genai, types, _errors = self.import_gemma_sdk()

        if not rows:
            return {}

        if status_callback:
            status_callback("Gemma is validating precise cut candidates...")

        title = "Shot-boundary validation contact sheet"
        contact_sheet = self.build_candidate_contact_sheet(rows, title)
        prompt = f"""
You are validating hard-cut boundary candidates.

The contact sheet contains one candidate per row.
- Left tile: frame before the proposed cut
- Right tile: first frame after the proposed cut
{prompt_context}

Return only JSON in this shape:
{{
  "candidates": [
    {{
      "id": "C01",
      "is_shot_boundary": true,
      "new_shot_description": "Description of the shot that begins on the right image.",
      "confidence": 0.0
    }}
  ]
}}

Rules:
- Mark is_shot_boundary true only if there is evidence of an actual edit or hard cut between the two frames.
- Do not mark true for the same continuous take with camera movement, zoom, pan, tilt, dolly, focus change, subject motion, or reframing.
- If the left and right frames plausibly belong to one uninterrupted recording, mark false.
- If false, set new_shot_description to an empty string.
- Confidence must be between 0 and 1.
- No markdown, no explanations outside JSON.
""".strip()

        response = self.run_gemma_with_retry(
            lambda: client.models.generate_content(
                model=model_name,
                contents=[prompt, contact_sheet],
                config=types.GenerateContentConfig(
                    system_instruction="You are a strict JSON vision validator.",
                    thinking_config=types.ThinkingConfig(thinking_level="high"),
                ),
            ),
            "Validating hard-cut candidates",
            status_callback=status_callback,
        )

        payload = extract_json_payload(response.text)
        raw_candidates = payload if isinstance(payload, list) else payload.get("candidates", [])
        validated = {}
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                continue
            candidate_id = str(raw.get("id", "")).strip()
            if not candidate_id:
                continue
            raw_flag = raw.get("is_shot_boundary")
            if isinstance(raw_flag, bool):
                is_shot_boundary = raw_flag
            else:
                is_shot_boundary = str(raw_flag or "").strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "y",
                }
            try:
                confidence = float(raw.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            validated[candidate_id] = {
                "is_shot_boundary": is_shot_boundary,
                "new_shot_description": str(
                    raw.get("new_shot_description", "") or ""
                ).strip(),
                "confidence": max(0.0, min(1.0, confidence)),
            }
        return validated

    def add_detected_shot_bookmarks(self, finalized_shots, clear_existing=False):
        if clear_existing:
            self.bookmarks = []
            self.timeline.bookmarks.clear()
            self.overview_timeline.bookmarks.clear()

        existing_frames = {bookmark["frame"] for bookmark in self.bookmarks}
        for shot in finalized_shots:
            frame = int(shot["start_frame"])
            if frame in existing_frames:
                continue
            timestamp = shot["start_timestamp"]
            description = shot["description"].strip()
            short_description = description[:48].rstrip()
            if len(description) > 48:
                short_description += "..."
            name = f"Shot {shot['index']:03d} {timestamp} {short_description}".strip()
            bookmark = {
                "frame": frame,
                "name": name,
                "color": "#00a8ff",
                "annotations": [],
            }
            self.bookmarks.append(bookmark)
            self.timeline.add_bookmark(frame)
            self.overview_timeline.add_bookmark(frame)
            existing_frames.add(frame)

        self.update_bookmark_list()

    def write_shot_detection_outputs(
        self,
        output_folder,
        prefix,
        model_name,
        fps,
        start_frame,
        end_frame,
        finalized_shots,
        chunk_analyses,
        traditional_candidates,
    ):
        os.makedirs(output_folder, exist_ok=True)
        prefix = sanitize_filename_part(prefix)
        txt_path = os.path.join(output_folder, f"{prefix}_gemma_shots.txt")
        json_path = os.path.join(output_folder, f"{prefix}_gemma_shots.json")

        with open(txt_path, "w", encoding="utf-8") as handle:
            for shot in finalized_shots:
                handle.write(
                    f"{shot['index']:03d}  {shot['start_timestamp']}  {shot['description']}\n"
                )

        payload = {
            "source_name": self.get_loaded_source_name(),
            "model": model_name,
            "fps": fps,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "shots": finalized_shots,
            "chunks": [
                {
                    "chunk_index": analysis.chunk.index,
                    "start_frame": analysis.chunk.start_frame,
                    "end_frame": analysis.chunk.end_frame,
                    "start_timestamp": frame_to_timestamp(analysis.chunk.start_frame, fps),
                    "end_timestamp": frame_to_timestamp(analysis.chunk.end_frame, fps),
                    "duration_seconds": analysis.chunk.duration_seconds,
                    "first_shot_signature": analysis.first_shot_signature,
                    "last_shot_signature": analysis.last_shot_signature,
                    "shots": [
                        {
                            "start_seconds": shot.start_seconds,
                            "description": shot.description,
                            "continues_from_previous": shot.continues_from_previous,
                            "continues_to_next": shot.continues_to_next,
                            "confidence": shot.confidence,
                        }
                        for shot in analysis.shots
                    ],
                }
                for analysis in chunk_analyses
            ],
            "traditional_candidates": [
                {
                    "frame": candidate.frame,
                    "timestamp": frame_to_timestamp(candidate.frame, fps),
                    "score": candidate.score,
                    "confidence": candidate.confidence,
                    "kind": candidate.kind,
                }
                for candidate in traditional_candidates
            ],
        }

        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=4)

        return txt_path, json_path

    def detect_shots_with_gemma(
        self,
        output_folder,
        prefix,
        model_name,
        api_key,
        start_frame,
        end_frame,
        add_bookmarks=True,
        clear_existing=False,
    ):
        progress = QDialog(self)
        progress.setWindowTitle("Gemma Shot Detection...")
        progress.setFixedSize(460, 150)
        layout = QVBoxLayout(progress)
        status_label = QLabel("Preparing shot detection...")
        status_label.setWordWrap(True)
        layout.addWidget(status_label)
        bar = QProgressBar()
        bar.setRange(0, 100)
        layout.addWidget(bar)
        progress.show()

        def update_progress(percent, message):
            bar.setValue(max(0, min(100, int(percent))))
            status_label.setText(message)
            QApplication.processEvents()

        fps = float(self.get_export_fps())
        relative_chunks = plan_shot_analysis_chunks(end_frame - start_frame + 1, fps)
        chunks = [
            AnalysisChunk(
                index=chunk.index,
                start_frame=start_frame + chunk.start_frame,
                end_frame=start_frame + chunk.end_frame,
                fps=chunk.fps,
            )
            for chunk in relative_chunks
        ]

        try:
            genai, _types, _errors = self.import_gemma_sdk()

            update_progress(5, "Scanning the clip for traditional cut candidates...")

            def traditional_progress(ratio):
                update_progress(5 + (ratio * 15), "Scanning the clip for traditional cut candidates...")

            traditional_candidates, _scores = self.scan_traditional_cut_candidates(
                start_frame,
                end_frame,
                fps,
                progress_callback=traditional_progress,
            )

            client = genai.Client(api_key=api_key) if api_key else genai.Client()
            chunk_analyses = []
            chunk_shot_groups = []

            with tempfile.TemporaryDirectory(prefix="kf_gemma_shots_") as temp_dir:
                for chunk_index, chunk in enumerate(chunks, start=1):
                    progress_base = 20 + ((chunk_index - 1) / max(len(chunks), 1)) * 50

                    update_progress(
                        progress_base,
                        f"Encoding chunk {chunk_index}/{len(chunks)} for Gemma...",
                    )
                    clip_path = os.path.join(
                        temp_dir, f"gemma_chunk_{chunk_index:03d}.mp4"
                    )
                    self.write_analysis_clip(
                        clip_path,
                        chunk.start_frame,
                        chunk.end_frame,
                        fps,
                        progress_callback=lambda ratio, base=progress_base: update_progress(
                            base + (ratio * (10 / max(len(chunks), 1))),
                            f"Encoding chunk {chunk_index}/{len(chunks)} for Gemma...",
                        ),
                    )

                    analysis = self.analyze_chunk_with_gemma(
                        client,
                        model_name,
                        clip_path,
                        chunk,
                        status_callback=lambda message, idx=chunk_index, total=len(chunks): update_progress(
                            progress_base + 10,
                            f"Chunk {idx}/{total}: {message}",
                        ),
                    )
                    chunk_analyses.append(analysis)
                    chunk_shot_groups.append(
                        match_chunk_shots_to_candidates(analysis, traditional_candidates)
                    )

                update_progress(72, "Reconciling chunk seams so split shots are not double-counted...")

                seam_rows = []
                seam_context_lines = []
                seam_window = max(2, int(round(fps * 0.5)))
                for seam_index in range(1, len(chunk_shot_groups)):
                    previous_group = chunk_shot_groups[seam_index - 1]
                    next_group = chunk_shot_groups[seam_index]
                    if not previous_group or not next_group:
                        continue

                    seam_frame = next_group[0].start_frame
                    seam_rows.append(
                        {
                            "id": f"S{seam_index:02d}",
                            "before_rgb": self.get_rgb_frame_array(
                                max(start_frame, seam_frame - 1), max_dimension=640
                            ),
                            "after_rgb": self.get_rgb_frame_array(
                                min(end_frame, seam_frame), max_dimension=640
                            ),
                            "before_timestamp": frame_to_timestamp(max(start_frame, seam_frame - 1), fps),
                            "after_timestamp": frame_to_timestamp(min(end_frame, seam_frame), fps),
                            "candidate_frame": seam_frame,
                        }
                    )
                    seam_context_lines.append(
                        f"S{seam_index:02d}: previous='{previous_group[-1].description}' next='{next_group[0].description}'"
                    )

                seam_validations = self.validate_candidate_rows_with_gemma(
                    client,
                    model_name,
                    seam_rows,
                    status_callback=lambda message: update_progress(76, message),
                    prompt_context="Context:\n" + "\n".join(seam_context_lines) if seam_context_lines else "",
                )

                merged_shots = []
                for group_index, group in enumerate(chunk_shot_groups):
                    if not group:
                        continue
                    if not merged_shots:
                        merged_shots.extend(group)
                        continue

                    current_first = group[0]
                    previous_last = merged_shots[-1]
                    seam_id = f"S{group_index:02d}"
                    seam_validation = seam_validations.get(seam_id, {})
                    seam_candidate = find_nearest_candidate(
                        current_first.start_frame,
                        traditional_candidates,
                        seam_window,
                    )
                    should_merge = should_merge_boundary_duplicate(
                        previous_last,
                        current_first,
                        boundary_same_shot=not seam_validation.get("is_shot_boundary", False),
                        seam_candidate=seam_candidate,
                    )
                    if should_merge:
                        previous_last.description = merge_shot_descriptions(
                            previous_last.description,
                            current_first.description,
                        )
                        previous_last.continues_to_next = (
                            previous_last.continues_to_next or current_first.continues_to_next
                        )
                        if current_first.confidence is not None:
                            previous_last.confidence = max(
                                previous_last.confidence or 0.0,
                                current_first.confidence,
                            )
                        merged_shots.extend(group[1:])
                    else:
                        merged_shots.extend(group)

                update_progress(84, "Checking for strong cut candidates Gemma may have missed in the video chunks...")

                matched_frames = {shot.start_frame for shot in merged_shots}
                extra_candidate_rows = []
                candidate_window = max(2, int(round(fps * 0.75)))
                for candidate_index, candidate in enumerate(traditional_candidates, start=1):
                    if candidate.confidence < 0.82:
                        continue
                    if any(abs(candidate.frame - frame) <= candidate_window for frame in matched_frames):
                        continue
                    extra_candidate_rows.append(
                        {
                            "id": f"C{candidate_index:03d}",
                            "before_rgb": self.get_rgb_frame_array(
                                max(start_frame, candidate.frame - 1), max_dimension=640
                            ),
                            "after_rgb": self.get_rgb_frame_array(
                                min(end_frame, candidate.frame), max_dimension=640
                            ),
                            "before_timestamp": frame_to_timestamp(
                                max(start_frame, candidate.frame - 1), fps
                            ),
                            "after_timestamp": frame_to_timestamp(
                                min(end_frame, candidate.frame), fps
                            ),
                            "candidate_frame": candidate.frame,
                            "candidate": candidate,
                        }
                    )

                extra_confirmed_shots = []
                if extra_candidate_rows:
                    batch_size = 8
                    for batch_index in range(0, len(extra_candidate_rows), batch_size):
                        batch = extra_candidate_rows[batch_index : batch_index + batch_size]
                        validated = self.validate_candidate_rows_with_gemma(
                            client,
                            model_name,
                            batch,
                            status_callback=lambda message, offset=batch_index: update_progress(
                                84 + ((offset + len(batch)) / max(len(extra_candidate_rows), 1)) * 10,
                                message,
                            ),
                        )
                        for row in batch:
                            result = validated.get(row["id"], {})
                            if not result.get("is_shot_boundary"):
                                continue
                            description = result.get("new_shot_description", "").strip()
                            if not description:
                                description = "Additional short shot detected from a strong cut candidate."
                            extra_confirmed_shots.append(
                                DetectedShot(
                                    start_frame=row["candidate_frame"],
                                    description=description,
                                    source="candidate_validation",
                                    confidence=result.get("confidence"),
                                )
                            )

                final_shots = merged_shots + extra_confirmed_shots
                finalized = finalize_shot_ranges(final_shots, fps, end_frame)

                update_progress(96, "Writing shot timestamp files...")
                txt_path, json_path = self.write_shot_detection_outputs(
                    output_folder,
                    prefix,
                    model_name,
                    fps,
                    start_frame,
                    end_frame,
                    finalized,
                    chunk_analyses,
                    traditional_candidates,
                )

                if add_bookmarks:
                    update_progress(99, "Adding detected shot starts as bookmarks...")
                    self.add_detected_shot_bookmarks(finalized, clear_existing=clear_existing)

            update_progress(100, "Shot detection complete.")
            self.remember_export_folder(output_folder)
            QMessageBox.information(
                self,
                "Gemma Shot Detection Complete",
                f"Detected {len(finalized)} shot(s).\n\n"
                f"Timestamps: {txt_path}\n"
                f"JSON: {json_path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Shot Detection Error", str(e))
        finally:
            progress.close()

    def get_export_fps(self):
        fps = (
            self.project.video_fps
            if getattr(self.project, "is_video", False)
            and hasattr(self.project, "video_fps")
            else self.fps
        )
        return int(fps) if fps > 0 else 24

    def quality_to_crf(self, quality):
        return int(35 - ((quality - 1) * (20 / 9)))

    def pixmap_to_rgb_array(self, pixmap):
        import numpy as np

        img = pixmap.toImage()
        img = img.convertToFormat(QImage.Format.Format_RGB888)

        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())

        height = img.height()
        width = img.width()
        arr = np.array(ptr).reshape((height, img.bytesPerLine()))
        return arr[:, : width * 3].reshape((height, width, 3))

    def write_mp4_file(
        self,
        filepath,
        frame_numbers,
        quality,
        preset="fast",
        progress_callback=None,
        fps=None,
        include_audio=False,
        audio_start_frame=None,
        audio_end_frame=None,
    ):
        import imageio

        if not filepath.endswith(".mp4"):
            filepath += ".mp4"

        output_dir = os.path.dirname(filepath)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        effective_fps = fps if fps is not None else self.get_export_fps()

        source_video = (
            self.project.video_path
            if getattr(self.project, "is_video", False) and getattr(self.project, "video_path", "")
            else None
        )
        should_mux_audio = bool(
            include_audio
            and source_video
            and os.path.isfile(source_video)
            and getattr(self, "_has_audio", False)
        )

        render_path = filepath
        temp_render_path = None
        if should_mux_audio:
            temp_render_path = filepath + ".noaudio.mp4"
            render_path = temp_render_path

        writer = imageio.get_writer(
            render_path,
            format="FFMPEG",
            mode="I",
            fps=effective_fps,
            codec="libx264",
            macro_block_size=None,
            quality=None,
            output_params=["-crf", str(self.quality_to_crf(quality)), "-preset", preset],
        )

        try:
            total = len(frame_numbers)
            last_source_frame = None
            last_rgb_frame = None
            for output_index, source_frame in enumerate(frame_numbers, start=1):
                if source_frame != last_source_frame or last_rgb_frame is None:
                    pixmap = self.load_frame_data(source_frame)
                    if pixmap is None:
                        raise ValueError(
                            f"Could not load frame {source_frame} for export."
                        )
                    last_rgb_frame = self.pixmap_to_rgb_array(pixmap)
                    last_source_frame = source_frame

                writer.append_data(last_rgb_frame)

                if progress_callback:
                    progress_callback(output_index, total, source_frame)
        finally:
            writer.close()

        if should_mux_audio and temp_render_path:
            try:
                a_start = audio_start_frame if audio_start_frame is not None else frame_numbers[0]
                a_end = audio_end_frame if audio_end_frame is not None else frame_numbers[-1]
                source_span = max(0, a_end - a_start + 1)
                pad_frames = max(0, len(frame_numbers) - source_span)
                mux_audio_into_mp4(
                    temp_render_path,
                    source_video,
                    filepath,
                    a_start,
                    a_end,
                    effective_fps,
                    pad_frames=pad_frames,
                )
            finally:
                if os.path.exists(temp_render_path):
                    try:
                        os.remove(temp_render_path)
                    except OSError:
                        pass

    def export_mp4(self, filepath, start_frame, end_frame, quality, preset="fast", include_audio=False):
        if not filepath.endswith(".mp4"):
            filepath += ".mp4"

        progress = QDialog(self)
        progress.setWindowTitle("Exporting...")
        progress.setFixedSize(300, 100)
        prog_layout = QVBoxLayout(progress)
        bar = QProgressBar()
        bar.setRange(start_frame, end_frame)
        prog_layout.addWidget(bar)
        progress.show()

        try:
            frame_numbers = list(range(start_frame, end_frame + 1))

            def update_progress(output_index, total, source_frame):
                bar.setValue(start_frame + output_index - 1)
                QApplication.processEvents()

            write_kwargs = {}
            if include_audio:
                write_kwargs["include_audio"] = True
                write_kwargs["audio_start_frame"] = start_frame
                write_kwargs["audio_end_frame"] = end_frame
            self.write_mp4_file(
                filepath,
                frame_numbers,
                quality,
                preset,
                progress_callback=update_progress,
                **write_kwargs
            )

            bar.setValue(end_frame)
            QApplication.processEvents()

            QMessageBox.information(
                self,
                "Export Complete",
                f"Successfully exported frames {start_frame}-{end_frame}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))
        finally:
            progress.close()

    def prepare_wan(
        self, output_folder, prefix, chunk_size, overlap, quality, preset,
        start_frame, end_frame, grid_size, per_chunk_grid=False, include_audio=False
    ):
        chunk_size = normalize_wan_chunk_size(chunk_size)
        overlap = normalize_chunk_overlap(overlap, chunk_size)
        
        total_frames_to_chunk = end_frame - start_frame + 1
        chunk_plan = plan_wan_chunks(total_frames_to_chunk, chunk_size, overlap)
        if not chunk_plan:
            QMessageBox.warning(self, "Export", "No frames available for export.")
            return

        prefix = sanitize_filename_part(prefix)
        
        # Grid optimization logic
        num_chunks = len(chunk_plan)
        preferred_dim = None
        if grid_size == '2x2': preferred_dim = 2
        elif grid_size == '3x3': preferred_dim = 3
        
        dims = [preferred_dim] if preferred_dim else [3, 2]
        if num_chunks == 1 and not preferred_dim:
            best_k, best_dim = 4, 2
        elif num_chunks == 3 and not preferred_dim:
            best_k, best_dim = 3, 3
        else:
            best_k, best_dim = None, None
            for k in range(3, 6):
                for dim in dims:
                    cap = dim * dim
                    if (num_chunks * k) % cap == 0:
                        best_k, best_dim = k, dim
                        break
                if best_k is not None:
                    break
            
            if best_k is None:
                best_k = 3
                if preferred_dim:
                    best_dim = preferred_dim
                else:
                    best_dim = dims[0]
                    best_waste = float('inf')
                    for dim in dims:
                        cap = dim * dim
                        waste = (cap - ((num_chunks * best_k) % cap)) % cap
                        if waste < best_waste:
                            best_waste = waste
                            best_dim = dim

        # Dynamically distribute missing frames to eliminate black squares
        cap = best_dim * best_dim
        
        if per_chunk_grid:
            k_list = [cap] * num_chunks
            best_k = cap
        else:
            base_total = num_chunks * best_k
            missing = (cap - (base_total % cap)) % cap
            
            k_list = [best_k] * num_chunks
            for i in range(missing):
                k_list[i % num_chunks] += 1

        # --- Phase 1: compute initial frame selections for review ---
        review_data = []
        for chunk_index, chunk in enumerate(chunk_plan):
            abs_start = start_frame + chunk.start_frame
            abs_end_raw = start_frame + chunk.end_frame
            abs_end = min(abs_end_raw, end_frame)

            k_i = k_list[chunk_index]
            span = abs_end - abs_start
            if span == 0:
                indices = [abs_start] * k_i
            else:
                indices = [abs_start + i * span // (k_i - 1) for i in range(k_i)]

            review_data.append({
                "chunk_index": chunk_index,
                "abs_start": abs_start,
                "abs_end": abs_end,
                "selected_frames": list(indices),
            })

        # --- Phase 2: show review dialog ---
        review = WanFrameReviewDialog(self, review_data, self.load_frame_data)
        if review.exec() != QDialog.DialogCode.Accepted:
            return

        # Collect the (possibly modified) frame selections
        reviewed_data = review.get_all_selected_frames()

        # --- Phase 3: export MP4s and grids using reviewed selections ---
        total_mp4_frames = sum(chunk.target_length for chunk in chunk_plan)

        progress = QDialog(self)
        progress.setWindowTitle("Wan Preparation...")
        progress.setFixedSize(420, 130)
        prog_layout = QVBoxLayout(progress)
        status_label = QLabel()
        status_label.setWordWrap(True)
        prog_layout.addWidget(status_label)
        bar = QProgressBar()
        bar.setRange(0, total_mp4_frames)
        prog_layout.addWidget(bar)
        progress.show()

        completed_frames = 0
        all_images = []
        selection_details = []

        import cv2
        import numpy as np
        from dataclasses import asdict

        try:
            os.makedirs(output_folder, exist_ok=True)

            for chunk_index, chunk in enumerate(chunk_plan, start=1):
                abs_start = start_frame + chunk.start_frame
                abs_end_raw = start_frame + chunk.end_frame
                # Clamp to user's selected range so we never read past the shot
                abs_end = min(abs_end_raw, end_frame)
                
                # Create dedicated chunk subdirectory
                chunk_dir_name = f"{prefix}_chunk_{chunk_index:03d}"
                chunk_dir = os.path.join(output_folder, chunk_dir_name)
                os.makedirs(chunk_dir, exist_ok=True)

                filename = (
                    f"{prefix}_wan22_{chunk_index:03d}_"
                    f"{chunk.target_length:03d}f_"
                    f"{abs_start:04d}-{abs_end:04d}.mp4"
                )
                filepath = os.path.join(chunk_dir, filename)

                frame_numbers = list(range(abs_start, abs_end + 1))
                # Pad with the last valid frame to reach WAN-safe target length
                pad_needed = chunk.target_length - len(frame_numbers)
                if pad_needed > 0:
                    frame_numbers.extend([abs_end] * pad_needed)

                status_label.setText(
                    f"Processing chunk {chunk_index}/{len(chunk_plan)}: "
                    f"frames {abs_start}-{abs_end}"
                )
                QApplication.processEvents()

                def update_progress(output_index, total, source_frame, base=completed_frames):
                    bar.setValue(base + output_index)
                    QApplication.processEvents()

                write_kwargs = {}
                if include_audio:
                    write_kwargs["include_audio"] = True
                    write_kwargs["audio_start_frame"] = abs_start
                    write_kwargs["audio_end_frame"] = abs_end
                self.write_mp4_file(
                    filepath,
                    frame_numbers,
                    quality,
                    preset,
                    progress_callback=update_progress,
                    **write_kwargs
                )

                completed_frames += len(frame_numbers)

                # Use the reviewed frame selections instead of recomputing
                reviewed_indices = reviewed_data[chunk_index - 1]["selected_frames"]

                chunk_images = []
                for i, idx in enumerate(reviewed_indices):
                    pixmap = self.load_frame_data(idx)
                    if pixmap:
                        img_rgb = self.pixmap_to_rgb_array(pixmap)
                        chunk_images.append(img_rgb)
                        
                        # Export each individual frame as separate image
                        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                        frame_filename = f"{prefix}_chunk_{chunk_index:03d}_frame_{i+1:02d}_f{idx:04d}.jpg"
                        frame_path = os.path.join(chunk_dir, frame_filename)
                        cv2.imwrite(frame_path, img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    else:
                        chunk_images.append(np.zeros((256, 256, 3), dtype=np.uint8))
                        
                # Export 1fps keyframe video containing the reviewed keyframes
                status_label.setText(
                    f"Processing chunk {chunk_index}/{len(chunk_plan)}: "
                    f"Writing 1fps keyframe video..."
                )
                QApplication.processEvents()
                
                video_1fps_filename = f"{prefix}_chunk_{chunk_index:03d}_1fps.mp4"
                video_1fps_path = os.path.join(chunk_dir, video_1fps_filename)
                self.write_mp4_file(
                    video_1fps_path,
                    reviewed_indices,
                    quality,
                    preset,
                    progress_callback=None,
                    fps=1,
                )

                all_images.extend(chunk_images)
                selection_details.append({
                    "chunk_index": chunk_index - 1,
                    "chunk_data": asdict(chunk),
                    "video_start_frame_abs": abs_start,
                    "video_end_frame_abs": abs_end,
                    "selected_frames_abs": reviewed_indices
                })

            bar.setValue(total_mp4_frames)
            QApplication.processEvents()
            
            status_label.setText("Generating grids and metadata...")
            QApplication.processEvents()
            
            cap = best_dim * best_dim
            grids = []
            if all_images:
                h, w = all_images[0].shape[:2]
                for i in range(0, len(all_images), cap):
                    batch = all_images[i:i+cap]
                    while len(batch) < cap:
                        batch.append(None)
                    grids.append(
                        compose_grid(
                            batch,
                            rows=best_dim,
                            cols=best_dim,
                            cell_size=(w, h),
                        )
                    )
            
            saved_grids = []
            for i, grid in enumerate(grids):
                if per_chunk_grid:
                    chunk_dir_name = f"{prefix}_chunk_{i+1:03d}"
                    grid_filename = f"{prefix}_chunk_{i+1:03d}_grid_{best_dim}x{best_dim}.jpg"
                    grid_path = os.path.join(output_folder, chunk_dir_name, grid_filename)
                    saved_grids.append(f"{chunk_dir_name}/{grid_filename}")
                else:
                    grid_filename = f"{prefix}_grid_{best_dim}x{best_dim}_{i:03d}.jpg"
                    grid_path = os.path.join(output_folder, grid_filename)
                    saved_grids.append(grid_filename)
                
                # Write to disk
                frame_bgr = cv2.cvtColor(grid, cv2.COLOR_RGB2BGR)
                params = [cv2.IMWRITE_JPEG_QUALITY, 95]
                cv2.imwrite(grid_path, frame_bgr, params)
                
            metadata = {}
            for detail in selection_details:
                chunk_num = detail['chunk_index'] + 1
                start_f = detail['video_start_frame_abs']
                metadata[f"chunk {chunk_num}"] = [f - start_f for f in detail['selected_frames_abs']]
            
            metadata.update({
                "start_frame": start_frame,
                "end_frame": end_frame,
                "total_frames_processed": total_frames_to_chunk,
                "chunk_size": chunk_size,
                "overlap": overlap,
                "num_chunks": num_chunks,
                "k_frames_per_chunk": best_k,
                "grid_dim": best_dim,
                "output_grids": saved_grids,
                "chunks": selection_details
            })
            
            import json
            with open(os.path.join(output_folder, f"{prefix}_wan_preparation.json"), "w") as f:
                json.dump(metadata, f, indent=4)

            QMessageBox.information(
                self,
                "Preparation Complete",
                f"Generated {num_chunks} chunk(s), {len(grids)} {best_dim}x{best_dim} grid(s), and JSON metadata.",
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Export Error", str(e))
        finally:
            progress.close()

    def show_preferences(self):
        dialog = PreferencesDialog(self)
        if dialog.exec():
            self.cache_size_mb = dialog.cache_size.value()
            self.fps = dialog.fps.value()
            self.export_folder = dialog.export_folder.text()
            self.audio_scrub = dialog.audio_scrub.isChecked()
            self.scrub_sensitivity = dialog.sensitivity.value()
            self.auto_save_enabled = dialog.auto_save.isChecked()
            self.audio_enabled = dialog.audio_enabled.isChecked()
            self.audio_volume = dialog.audio_volume.value()
            if getattr(self, "_audio_output", None):
                self._audio_output.setVolume(self.audio_volume / 100.0)

            self.save_settings()
            self.fps_label.setText(f"{self.fps} FPS")

            self.max_cache_frames = (self.cache_size_mb * 1024 * 1024) // (
                1920 * 1080 * 4
            )

            if self.auto_save_enabled:
                self.auto_save_timer.start(120000)
            else:
                self.auto_save_timer.stop()

    def show_about(self):
        QMessageBox.about(
            self,
            "About Keyframe Pro Lite",
            "Keyframe Pro Lite v1.0\n\nA lightweight animation review tool for animators.\n\nBuilt with PyQt6",
        )

    def update_status(self):
        import psutil

        process = psutil.Process()
        mem_mb = process.memory_info().rss / (1024 * 1024)

        if mem_mb > 2048:
            self.status_bar.showMessage(
                f"WARNING: High memory usage ({mem_mb:.0f} MB)", 5000
            )
        else:
            self.status_bar.showMessage(f"Memory: {mem_mb:.0f} MB", 2000)

    def closeEvent(self, event):
        self.play_timer.stop()
        self.auto_save_timer.stop()
        if getattr(self, "_video_cap", None) is not None:
            try:
                self._video_cap.release()
            except Exception:
                pass
            self._video_cap = None
        if getattr(self, "_audio_player", None) is not None:
            self._audio_player.stop()
        self.save_settings()
        event.accept()


class PreferencesDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.setFixedSize(300, 280)

        layout = QFormLayout(self)

        self.cache_size = QSpinBox()
        self.cache_size.setRange(100, 2000)
        self.cache_size.setValue(parent.cache_size_mb)
        self.cache_size.setSuffix(" MB")
        layout.addRow("Cache Size:", self.cache_size)

        self.fps = QSpinBox()
        self.fps.setRange(12, 60)
        self.fps.setValue(parent.fps)
        layout.addRow("Default FPS:", self.fps)

        self.export_folder = QLineEdit(parent.export_folder or parent.get_default_export_folder())
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.export_folder)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self.browse_export_folder)
        folder_layout.addWidget(browse_btn)
        layout.addRow("Export Folder:", folder_layout)

        self.audio_scrub = QCheckBox()
        self.audio_scrub.setChecked(parent.audio_scrub)
        layout.addRow("Audio Scrub:", self.audio_scrub)

        self.audio_enabled = QCheckBox()
        self.audio_enabled.setChecked(getattr(parent, "audio_enabled", True))
        layout.addRow("Enable Audio:", self.audio_enabled)

        self.audio_volume = QSlider(Qt.Orientation.Horizontal)
        self.audio_volume.setRange(0, 100)
        self.audio_volume.setValue(getattr(parent, "audio_volume", 80))
        layout.addRow("Audio Volume:", self.audio_volume)

        self.sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity.setRange(1, 10)
        self.sensitivity.setValue(parent.scrub_sensitivity)
        layout.addRow("Scrub Sensitivity:", self.sensitivity)

        self.auto_save = QCheckBox()
        self.auto_save.setChecked(parent.auto_save_enabled)
        layout.addRow("Auto-save (2 min):", self.auto_save)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def browse_export_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if folder:
            self.export_folder.setText(folder)


class ExportDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.setModal(True)
        self.setFixedSize(400, 350)

        layout = QFormLayout(self)

        export_type_group = QGroupBox("Export Type")
        export_type_layout = QVBoxLayout(export_type_group)

        self.single_frame_radio = QPushButton("Single Frame")
        self.sequence_radio = QPushButton("Image Sequence")

        export_type_layout.addWidget(self.single_frame_radio)
        export_type_layout.addWidget(self.sequence_radio)

        layout.addRow(export_type_group)

        self.format_combo = QComboBox()
        self.format_combo.addItems(list(IMAGE_EXPORT_FORMATS.keys()))
        layout.addRow("Format:", self.format_combo)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(90)
        layout.addRow("JPEG Quality:", self.quality_slider)

        self.output_folder = QLineEdit(parent.get_default_export_folder())
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.output_folder)
        self.browse_output_folder_btn = QPushButton("...")
        self.browse_output_folder_btn.setFixedWidth(30)
        self.browse_output_folder_btn.clicked.connect(self.browse_output_folder)
        folder_layout.addWidget(self.browse_output_folder_btn)
        layout.addRow("Output Folder:", folder_layout)

        self.filename_pattern = QLineEdit("frame_####.png")
        layout.addRow("Filename Pattern:", self.filename_pattern)

        resize_group = QGroupBox("Resize")
        resize_layout = QHBoxLayout(resize_group)

        self.full_res = QRadioButton("Full")
        self.half_res = QRadioButton("Half")
        self.quarter_res = QRadioButton("Quarter")
        self.full_res.setChecked(True)

        resize_layout.addWidget(self.full_res)
        resize_layout.addWidget(self.half_res)
        resize_layout.addWidget(self.quarter_res)

        layout.addRow(resize_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.do_export)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.single_frame_radio.clicked.connect(lambda: self.set_export_mode("single"))
        self.sequence_radio.clicked.connect(lambda: self.set_export_mode("sequence"))
        self.set_export_mode("single")

    def set_export_mode(self, mode):
        self.export_mode = mode

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder.setText(folder)

    def do_export(self):
        if not self.output_folder.text():
            QMessageBox.warning(self, "Error", "Please select an output folder.")
            return

        parent = self.parent()
        format_name = self.format_combo.currentText()
        format_ext = IMAGE_EXPORT_FORMATS[format_name]["extension"]

        if self.export_mode == "single":
            filename = self.filename_pattern.text().replace(
                "####", f"{parent.current_frame + 1:04d}"
            )
            filepath = os.path.join(self.output_folder.text(), filename)
            filepath = ensure_extension(filepath, format_ext)

            try:
                parent.save_image_export_requests(
                    [{"frame": parent.current_frame, "path": filepath}],
                    format_name,
                    jpeg_quality=self.quality_slider.value(),
                    progress_title=f"Exporting Frame {parent.current_frame + 1}",
                )
                parent.remember_export_folder(filepath)
                QMessageBox.information(
                    self, "Export Complete", f"Frame exported to {filepath}"
                )
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))
                return
        else:
            QMessageBox.information(
                self, "Export Complete", "Sequence export functionality coming soon!"
            )

        self.accept()


class ExportBookmarksDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Export Bookmarks")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QFormLayout(self)

        info = QLabel(
            f"{len(parent.bookmarks)} bookmark(s) can export as an image sequence or a stitched video."
        )
        info.setWordWrap(True)
        layout.addRow(info)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Image Sequence", "images")
        self.mode_combo.addItem("Video", "video")
        self.mode_combo.currentIndexChanged.connect(self.update_mode_state)
        layout.addRow("Export Type:", self.mode_combo)

        self.output_folder = QLineEdit(parent.get_default_export_folder())
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.output_folder)
        self.browse_output_folder_btn = QPushButton("...")
        self.browse_output_folder_btn.setFixedWidth(30)
        self.browse_output_folder_btn.clicked.connect(self.browse_output_folder)
        folder_layout.addWidget(self.browse_output_folder_btn)
        layout.addRow("Output Folder:", folder_layout)

        self.filename_prefix = QLineEdit(parent.get_loaded_source_name())
        layout.addRow("Filename Prefix:", self.filename_prefix)

        self.format_combo = QComboBox()
        self.format_combo.addItems(list(IMAGE_EXPORT_FORMATS.keys()))
        self.format_combo.currentTextChanged.connect(self.update_quality_state)
        layout.addRow("Format:", self.format_combo)

        self.jpeg_quality = QSlider(Qt.Orientation.Horizontal)
        self.jpeg_quality.setRange(80, 100)
        self.jpeg_quality.setValue(95)
        self.jpeg_quality_label = QLabel("JPEG Quality: 95")
        self.jpeg_quality.valueChanged.connect(self.update_quality_label)

        quality_layout = QVBoxLayout()
        quality_layout.addWidget(self.jpeg_quality_label)
        quality_layout.addWidget(self.jpeg_quality)
        layout.addRow("JPEG:", quality_layout)

        default_name = build_bookmark_video_export_filename(
            parent.get_loaded_source_name(), ".mp4"
        )
        default_path = os.path.join(parent.get_default_export_folder(), default_name)
        self.output_path = QLineEdit(default_path)
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_path)
        self.browse_output_path_btn = QPushButton("...")
        self.browse_output_path_btn.setFixedWidth(30)
        self.browse_output_path_btn.clicked.connect(self.browse_output_path)
        output_layout.addWidget(self.browse_output_path_btn)
        layout.addRow("Output File:", output_layout)

        self.hold_spinbox = QSpinBox()
        self.hold_spinbox.setRange(1, 9999)
        self.hold_spinbox.setValue(1)
        self.hold_spinbox.setSuffix(" frame(s)")
        self.hold_spinbox.valueChanged.connect(self.update_duration_hint)

        self.duration_hint = QLabel()
        self.duration_hint.setWordWrap(True)
        self.duration_hint.setStyleSheet("color: gray; font-size: 10px;")
        hold_layout = QVBoxLayout()
        hold_layout.addWidget(self.hold_spinbox)
        hold_layout.addWidget(self.duration_hint)
        layout.addRow("Hold Per Bookmark:", hold_layout)

        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(1, 120)
        self.fps_spinbox.setValue(parent.get_export_fps())
        self.fps_spinbox.setSuffix(" fps")
        self.fps_spinbox.valueChanged.connect(self.update_duration_hint)
        fps_hint = QLabel("Frame rate of the exported video.")
        fps_hint.setStyleSheet("color: gray; font-size: 10px;")
        fps_layout = QVBoxLayout()
        fps_layout.addWidget(self.fps_spinbox)
        fps_layout.addWidget(fps_hint)
        layout.addRow("Export FPS:", fps_layout)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 10)
        self.quality_slider.setValue(5)
        self.quality_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.quality_slider.setTickInterval(1)

        self.quality_label = QLabel("Quality: 5 (Balanced)")
        self.quality_slider.valueChanged.connect(self.update_video_quality_label)

        video_quality_layout = QVBoxLayout()
        video_quality_layout.addWidget(self.quality_label)
        video_quality_layout.addWidget(self.quality_slider)
        video_quality_hint = QLabel(
            "Lower quality = Smaller file size.\n10 is near lossless."
        )
        video_quality_hint.setStyleSheet("color: gray; font-size: 10px;")
        video_quality_layout.addWidget(video_quality_hint)
        layout.addRow("Video Compression:", video_quality_layout)

        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["ultrafast", "fast", "medium", "slow"])
        self.speed_combo.setCurrentIndex(1)
        speed_hint = QLabel("'ultrafast' exports quickly but file is slightly larger.")
        speed_hint.setStyleSheet("color: gray; font-size: 10px;")
        speed_layout = QVBoxLayout()
        speed_layout.addWidget(self.speed_combo)
        speed_layout.addWidget(speed_hint)
        layout.addRow("Speed:", speed_layout)

        self.include_audio_checkbox = QCheckBox("Include Audio")
        has_audio = getattr(parent, "_has_audio", False)
        self.include_audio_checkbox.setChecked(has_audio)
        self.include_audio_checkbox.setEnabled(has_audio)
        self.audio_hint = QLabel(
            "Source has audio: ✓" if has_audio else "Source has no audio track."
        )
        self.audio_hint.setStyleSheet("color: gray; font-size: 10px;")
        audio_layout = QVBoxLayout()
        audio_layout.addWidget(self.include_audio_checkbox)
        audio_layout.addWidget(self.audio_hint)
        layout.addRow("Audio:", audio_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.update_quality_state(self.format_combo.currentText())
        self.update_video_quality_label(self.quality_slider.value())
        self.update_duration_hint()
        self.update_mode_state()

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder.setText(folder)

    def browse_output_path(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export Bookmarks as Video",
            self.output_path.text().strip(),
            "MP4 Video (*.mp4)",
        )
        if filepath:
            self.output_path.setText(ensure_extension(filepath, ".mp4"))

    def get_format_name(self):
        return self.format_combo.currentText()

    def is_video_mode(self):
        return self.mode_combo.currentData() == "video"

    def update_quality_label(self, value):
        self.jpeg_quality_label.setText(f"JPEG Quality: {value}")

    def update_quality_state(self, format_name):
        is_jpeg = format_name == "JPEG"
        self.jpeg_quality.setEnabled(is_jpeg)
        self.jpeg_quality_label.setEnabled(is_jpeg)

    def update_duration_hint(self, _value=None):
        fps = self.fps_spinbox.value()
        hold_frames = max(1, self.hold_spinbox.value())
        total_output_frames = hold_frames * len(self.parent_window.bookmarks)
        total_duration = total_output_frames / fps
        self.duration_hint.setText(
            f"Each bookmark held for {hold_frames} frame(s) at {fps} fps. "
            f"Estimated reel length: {total_duration:.2f} seconds."
        )

    def update_video_quality_label(self, val):
        if val <= 3:
            desc = "Small File"
        elif val <= 6:
            desc = "Balanced"
        else:
            desc = "High Quality"
        self.quality_label.setText(f"Quality: {val} ({desc})")

    def update_mode_state(self):
        image_mode = not self.is_video_mode()

        self.output_folder.setEnabled(image_mode)
        self.browse_output_folder_btn.setEnabled(image_mode)
        self.filename_prefix.setEnabled(image_mode)
        self.format_combo.setEnabled(image_mode)
        self.update_quality_state(self.format_combo.currentText() if image_mode else "")
        if not image_mode:
            self.jpeg_quality.setEnabled(False)
            self.jpeg_quality_label.setEnabled(False)

        self.output_path.setEnabled(not image_mode)
        self.browse_output_path_btn.setEnabled(not image_mode)
        self.hold_spinbox.setEnabled(not image_mode)
        self.fps_spinbox.setEnabled(not image_mode)
        self.quality_slider.setEnabled(not image_mode)
        self.speed_combo.setEnabled(not image_mode)


class ExportBookmarksVideoDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Export Bookmarks as Video")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QFormLayout(self)

        info = QLabel(
            f"{len(parent.bookmarks)} bookmark(s) will stitch in timeline order."
        )
        info.setWordWrap(True)
        layout.addRow(info)

        default_name = build_bookmark_video_export_filename(
            parent.get_loaded_source_name(), ".mp4"
        )
        default_path = os.path.join(parent.get_default_export_folder(), default_name)
        self.output_path = QLineEdit(default_path)

        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_path)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self.browse_output_path)
        output_layout.addWidget(browse_btn)
        layout.addRow("Output File:", output_layout)

        self.hold_spinbox = QSpinBox()
        self.hold_spinbox.setRange(1, 9999)
        self.hold_spinbox.setValue(1)
        self.hold_spinbox.setSuffix(" frame(s)")
        self.hold_spinbox.valueChanged.connect(self.update_duration_hint)

        self.duration_hint = QLabel()
        self.duration_hint.setWordWrap(True)
        self.duration_hint.setStyleSheet("color: gray; font-size: 10px;")

        hold_layout = QVBoxLayout()
        hold_layout.addWidget(self.hold_spinbox)
        hold_layout.addWidget(self.duration_hint)
        layout.addRow("Hold Per Bookmark:", hold_layout)

        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(1, 120)
        self.fps_spinbox.setValue(parent.get_export_fps())
        self.fps_spinbox.setSuffix(" fps")
        self.fps_spinbox.valueChanged.connect(self.update_duration_hint)
        fps_hint = QLabel("Frame rate of the exported video.")
        fps_hint.setStyleSheet("color: gray; font-size: 10px;")
        fps_layout = QVBoxLayout()
        fps_layout.addWidget(self.fps_spinbox)
        fps_layout.addWidget(fps_hint)
        layout.addRow("Export FPS:", fps_layout)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 10)
        self.quality_slider.setValue(5)
        self.quality_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.quality_slider.setTickInterval(1)

        self.quality_label = QLabel("Quality: 5 (Balanced)")
        self.quality_slider.valueChanged.connect(self.update_quality_label)

        quality_layout = QVBoxLayout()
        quality_layout.addWidget(self.quality_label)
        quality_layout.addWidget(self.quality_slider)

        quality_hint = QLabel("Lower quality = Smaller file size.\n10 is near lossless.")
        quality_hint.setStyleSheet("color: gray; font-size: 10px;")
        quality_layout.addWidget(quality_hint)
        layout.addRow("Compression:", quality_layout)

        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["ultrafast", "fast", "medium", "slow"])
        self.speed_combo.setCurrentIndex(1)
        speed_hint = QLabel("'ultrafast' exports quickly but file is slightly larger.")
        speed_hint.setStyleSheet("color: gray; font-size: 10px;")
        speed_layout = QVBoxLayout()
        speed_layout.addWidget(self.speed_combo)
        speed_layout.addWidget(speed_hint)
        layout.addRow("Speed:", speed_layout)

        self.include_audio_checkbox = QCheckBox("Include Audio")
        has_audio = getattr(parent, "_has_audio", False)
        self.include_audio_checkbox.setChecked(has_audio)
        self.include_audio_checkbox.setEnabled(has_audio)
        self.audio_hint = QLabel(
            "Source has audio: ✓" if has_audio else "Source has no audio track."
        )
        self.audio_hint.setStyleSheet("color: gray; font-size: 10px;")
        audio_layout = QVBoxLayout()
        audio_layout.addWidget(self.include_audio_checkbox)
        audio_layout.addWidget(self.audio_hint)
        layout.addRow("Audio:", audio_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.update_quality_label(self.quality_slider.value())
        self.update_duration_hint(self.hold_spinbox.value())

    def browse_output_path(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export Bookmarks as Video",
            self.output_path.text().strip(),
            "MP4 Video (*.mp4)",
        )
        if filepath:
            self.output_path.setText(ensure_extension(filepath, ".mp4"))

    def update_duration_hint(self, _value=None):
        fps = self.fps_spinbox.value()
        hold_frames = max(1, self.hold_spinbox.value())
        total_output_frames = hold_frames * len(self.parent_window.bookmarks)
        total_duration = total_output_frames / fps
        self.duration_hint.setText(
            f"Each bookmark held for {hold_frames} frame(s) at {fps} fps. "
            f"Estimated reel length: {total_duration:.2f} seconds."
        )

    def update_quality_label(self, val):
        if val <= 3:
            desc = "Small File"
        elif val <= 6:
            desc = "Balanced"
        else:
            desc = "High Quality"

        self.quality_label.setText(f"Quality: {val} ({desc})")


class ExportMp4Dialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Export to MP4")
        self.setModal(True)
        self.setMinimumWidth(350)

        layout = QFormLayout(self)

        self.start_spinbox = QSpinBox()
        self.start_spinbox.setRange(0, parent.total_frames - 1)
        self.start_spinbox.setValue(0)
        layout.addRow("Start Frame:", self.start_spinbox)

        self.end_spinbox = QSpinBox()
        self.end_spinbox.setRange(0, parent.total_frames - 1)
        self.end_spinbox.setValue(parent.total_frames - 1)
        layout.addRow("End Frame:", self.end_spinbox)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 10)
        self.quality_slider.setValue(5)
        self.quality_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.quality_slider.setTickInterval(1)

        self.quality_label = QLabel("Quality: 5 (Balanced)")
        self.quality_slider.valueChanged.connect(self.update_quality_label)

        quality_layout = QVBoxLayout()
        quality_layout.addWidget(self.quality_label)
        quality_layout.addWidget(self.quality_slider)

        # Add a helpful hint
        hint = QLabel("Lower quality = Smaller file size.\n10 is near lossless.")
        hint.setStyleSheet("color: gray; font-size: 10px;")
        quality_layout.addWidget(hint)

        layout.addRow("Compression:", quality_layout)

        # Speed preset
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["ultrafast", "fast", "medium", "slow"])
        self.speed_combo.setCurrentIndex(1)  # default to 'fast'
        speed_hint = QLabel("'ultrafast' exports quickly but file is slightly larger.")
        speed_hint.setStyleSheet("color: gray; font-size: 10px;")
        speed_layout = QVBoxLayout()
        speed_layout.addWidget(self.speed_combo)
        speed_layout.addWidget(speed_hint)
        layout.addRow("Speed:", speed_layout)

        self.include_audio_checkbox = QCheckBox("Include Audio")
        has_audio = getattr(parent, "_has_audio", False)
        self.include_audio_checkbox.setChecked(has_audio)
        self.include_audio_checkbox.setEnabled(has_audio)
        self.audio_hint = QLabel(
            "Source has audio: ✓" if has_audio else "Source has no audio track."
        )
        self.audio_hint.setStyleSheet("color: gray; font-size: 10px;")
        audio_layout = QVBoxLayout()
        audio_layout.addWidget(self.include_audio_checkbox)
        audio_layout.addWidget(self.audio_hint)
        layout.addRow("Audio:", audio_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def update_quality_label(self, val):
        if val <= 3:
            desc = "Small File"
        elif val <= 6:
            desc = "Balanced"
        else:
            desc = "High Quality"

        self.quality_label.setText(f"Quality: {val} ({desc})")


class GemmaShotDetectionDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Detect Shots")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QFormLayout(self)

        self.plan_info = QLabel()
        self.plan_info.setWordWrap(True)
        layout.addRow(self.plan_info)

        default_output_folder = parent.get_default_export_folder()
        self.output_folder = QLineEdit(default_output_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.output_folder)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self.browse_output_folder)
        folder_layout.addWidget(browse_btn)
        layout.addRow("Output Folder:", folder_layout)

        default_prefix = sanitize_filename_part(parent.get_loaded_source_name())
        self.filename_prefix = QLineEdit(f"{default_prefix}_shots")
        layout.addRow("Filename Prefix:", self.filename_prefix)

        self.api_key = QLineEdit("")
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText(
            "Optional here if GOOGLE_API_KEY or GEMINI_API_KEY is set in .env"
        )
        api_hint = QLabel(
            "Uses the selected Google model for this run; leaving the field blank uses GOOGLE_API_KEY or GEMINI_API_KEY from .env."
        )
        api_hint.setWordWrap(True)
        api_hint.setStyleSheet("color: gray; font-size: 10px;")
        api_layout = QVBoxLayout()
        api_layout.addWidget(self.api_key)
        api_layout.addWidget(api_hint)
        layout.addRow("Google API Key:", api_layout)

        self.model_combo = QComboBox()
        self.model_combo.addItem("Gemini 3 Flash", "gemini-3-flash-preview")
        self.model_combo.addItem("Gemini 3.1 Flash-Lite", "gemini-3.1-flash-lite-preview")
        self.model_combo.addItem("Gemma 4 31B Instruct", "gemma-4-31b-it")
        self.model_combo.addItem("Gemma 4 26B A4B Instruct", "gemma-4-26b-a4b-it")
        model_hint = QLabel(
            "Supported local options include Gemini 3 Flash, Gemini 3.1 Flash-Lite, and Gemma 4 models."
        )
        model_hint.setWordWrap(True)
        model_hint.setStyleSheet("color: gray; font-size: 10px;")
        model_layout = QVBoxLayout()
        model_layout.addWidget(self.model_combo)
        model_layout.addWidget(model_hint)
        layout.addRow("Model:", model_layout)

        self.start_spinbox = QSpinBox()
        self.start_spinbox.setRange(0, parent.total_frames - 1)
        self.start_spinbox.setValue(0)
        self.start_spinbox.valueChanged.connect(self.update_plan_preview)
        layout.addRow("Start Frame:", self.start_spinbox)

        self.end_spinbox = QSpinBox()
        self.end_spinbox.setRange(0, parent.total_frames - 1)
        self.end_spinbox.setValue(parent.total_frames - 1)
        self.end_spinbox.valueChanged.connect(self.update_plan_preview)
        layout.addRow("End Frame:", self.end_spinbox)

        self.add_bookmarks_checkbox = QCheckBox("Add detected shots as bookmarks")
        self.add_bookmarks_checkbox.setChecked(True)
        self.add_bookmarks_checkbox.toggled.connect(self.update_bookmark_options)
        layout.addRow("Bookmarks:", self.add_bookmarks_checkbox)

        self.clear_bookmarks_checkbox = QCheckBox("Clear existing bookmarks first")
        self.clear_bookmarks_checkbox.setChecked(False)
        layout.addRow("", self.clear_bookmarks_checkbox)

        strategy_hint = QLabel(
            f"The detector uses a hybrid pipeline: {SHOT_ANALYSIS_CHUNK_SECONDS:.0f}-second Gemma video chunks for semantic shot descriptions, "
            "dense traditional cut scoring for frame-accurate candidates, and Gemma image checks to reconcile seam duplicates and missed strong cuts."
        )
        strategy_hint.setWordWrap(True)
        strategy_hint.setStyleSheet("color: gray; font-size: 10px;")
        layout.addRow(strategy_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.update_bookmark_options()
        self.update_plan_preview()

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder.setText(folder)

    def update_bookmark_options(self):
        enabled = self.add_bookmarks_checkbox.isChecked()
        self.clear_bookmarks_checkbox.setEnabled(enabled)
        if not enabled:
            self.clear_bookmarks_checkbox.setChecked(False)

    def update_plan_preview(self, *_args):
        start_frame = self.start_spinbox.value()
        end_frame = self.end_spinbox.value()
        if start_frame > end_frame:
            self.plan_info.setText("Invalid frame range: Start > End")
            return

        fps = float(self.parent_window.get_export_fps())
        total_frames = end_frame - start_frame + 1
        chunks = plan_shot_analysis_chunks(total_frames, fps)
        seconds = total_frames / max(fps, 1e-6)
        self.plan_info.setText(
            f"{total_frames} frame(s) / {seconds:.2f} second(s) will be analyzed as "
            f"{len(chunks)} Gemma chunk(s) of up to {SHOT_ANALYSIS_CHUNK_SECONDS:.0f} seconds each."
        )


class WanFramePickerDialog(QDialog):
    """Shows frames around a chunk range so the user can pick a replacement frame."""

    def __init__(self, parent, chunk_start, chunk_end, current_frame, load_frame_fn):
        super().__init__(parent)
        self.setWindowTitle("Pick a Frame")
        self.setModal(True)
        self.picked_frame = current_frame
        self.load_frame_fn = load_frame_fn
        self.chunk_start = chunk_start
        self.chunk_end = chunk_end

        self.setMinimumSize(700, 480)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QLabel(
            f"Scrub to choose a replacement frame (chunk range: {chunk_start}–{chunk_end})"
        )
        header.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(header)

        # Large preview
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(300)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview_label.setStyleSheet(
            "background: #1a1a2e; border: 1px solid #333; border-radius: 4px;"
        )
        layout.addWidget(self.preview_label)

        # Slider for frame scrubbing
        slider_layout = QHBoxLayout()
        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setRange(chunk_start, chunk_end)
        self.frame_slider.setValue(current_frame)
        self.frame_slider.valueChanged.connect(self._on_slider_changed)
        slider_layout.addWidget(self.frame_slider)

        self.frame_num_label = QLabel(f"Frame {current_frame}")
        self.frame_num_label.setFixedWidth(90)
        self.frame_num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slider_layout.addWidget(self.frame_num_label)
        layout.addLayout(slider_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        pick_btn = QPushButton("Use This Frame")
        pick_btn.setDefault(True)
        pick_btn.setStyleSheet(
            "QPushButton { background: #4a6cf7; color: white; padding: 8px 24px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #3b5de7; }"
        )
        pick_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("padding: 8px 16px;")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(pick_btn)
        layout.addLayout(btn_layout)

        self._update_preview(current_frame)

    def _on_slider_changed(self, value):
        self.picked_frame = value
        self.frame_num_label.setText(f"Frame {value}")
        self._update_preview(value)

    def _update_preview(self, frame_num):
        pixmap = self.load_frame_fn(frame_num)
        if pixmap:
            scaled = pixmap.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled)
        else:
            self.preview_label.setText("Could not load frame")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview(self.picked_frame)


class _ClickableThumbnail(QLabel):
    """A thumbnail label that emits a click signal with its index."""
    clicked = pyqtSignal(int)

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self._index = index
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, event):
        self.clicked.emit(self._index)
        super().mousePressEvent(event)


class WanFrameReviewDialog(QDialog):
    """Shows all selected grid frames for review before export.

    The user can accept the selection or click any thumbnail to replace it
    by picking from the chunk's frame range.
    """

    THUMB_SIZE = 160

    def __init__(self, parent, selection_data, load_frame_fn):
        """
        Args:
            parent: parent widget (the main window).
            selection_data: list of dicts, one per chunk:
                {
                    "chunk_index": int,
                    "abs_start": int,
                    "abs_end": int,
                    "selected_frames": [int, ...],
                }
            load_frame_fn: callable(frame_num) -> QPixmap or None.
        """
        super().__init__(parent)
        self.setWindowTitle("Review Grid Frame Selections")
        self.setModal(True)
        self.load_frame_fn = load_frame_fn
        self.selection_data = selection_data
        self._thumbnails = []  # list of (thumbnail_widget, flat_index, chunk_idx, frame_idx_in_chunk)

        self.setMinimumSize(660, 420)

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        header = QLabel(
            "Review the frames selected for each chunk's grid slots.\n"
            "Click any thumbnail to replace it with a different frame from that chunk."
        )
        header.setWordWrap(True)
        header.setStyleSheet("font-size: 13px; padding: 4px 0;")
        outer.addWidget(header)

        # Scrollable area for all thumbnails
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: none; }"
        )
        scroll_widget = QWidget()
        self.thumbs_layout = QVBoxLayout(scroll_widget)
        self.thumbs_layout.setSpacing(12)
        scroll.setWidget(scroll_widget)
        outer.addWidget(scroll, stretch=1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        accept_btn = QPushButton("Accept && Export")
        accept_btn.setDefault(True)
        accept_btn.setStyleSheet(
            "QPushButton { background: #2ecc71; color: white; padding: 10px 28px; "
            "border-radius: 5px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background: #27ae60; }"
        )
        accept_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("padding: 10px 18px; font-size: 13px;")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(accept_btn)
        outer.addLayout(btn_layout)

        self._build_thumbnails()

    def _build_thumbnails(self):
        """Create thumbnail widgets for every selected frame, grouped by chunk."""
        # Clear previous widgets
        while self.thumbs_layout.count():
            item = self.thumbs_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            sub = item.layout()
            if sub:
                while sub.count():
                    child = sub.takeAt(0)
                    cw = child.widget()
                    if cw:
                        cw.deleteLater()

        self._thumbnails.clear()
        flat_index = 0

        for chunk_data in self.selection_data:
            chunk_idx = chunk_data["chunk_index"]
            abs_start = chunk_data["abs_start"]
            abs_end = chunk_data["abs_end"]
            frames = chunk_data["selected_frames"]

            # Chunk header
            chunk_header = QLabel(
                f"Chunk {chunk_idx + 1}  "
                f"<span style='color: #888; font-size: 11px;'>"
                f"(frames {abs_start}–{abs_end})</span>"
            )
            chunk_header.setStyleSheet(
                "font-weight: bold; font-size: 12px; padding: 2px 0 0 0;"
            )
            self.thumbs_layout.addWidget(chunk_header)

            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)
            for fi, frame_num in enumerate(frames):
                thumb = _ClickableThumbnail(flat_index)
                thumb.setFixedSize(self.THUMB_SIZE, self.THUMB_SIZE)
                thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
                thumb.setStyleSheet(
                    "QLabel { background: #1a1a2e; border: 2px solid #333; "
                    "border-radius: 4px; }"
                    "QLabel:hover { border-color: #4a6cf7; }"
                )
                thumb.setToolTip(
                    f"Frame {frame_num}  (click to replace)"
                )
                thumb.clicked.connect(self._on_thumb_clicked)

                self._set_thumbnail_pixmap(thumb, frame_num)
                row_layout.addWidget(thumb)
                self._thumbnails.append((thumb, flat_index, chunk_idx, fi))
                flat_index += 1

            row_layout.addStretch()
            self.thumbs_layout.addLayout(row_layout)

        self.thumbs_layout.addStretch()

    def _set_thumbnail_pixmap(self, label, frame_num):
        """Load a frame and set it as a scaled pixmap on the label."""
        pixmap = self.load_frame_fn(frame_num)
        if pixmap:
            scaled = pixmap.scaled(
                self.THUMB_SIZE - 4, self.THUMB_SIZE - 4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(scaled)
        else:
            label.setText(f"F{frame_num}")

    def _on_thumb_clicked(self, flat_index):
        """Open the frame picker for the chunk owning this thumbnail."""
        entry = None
        for t_widget, t_flat, t_chunk, t_fi in self._thumbnails:
            if t_flat == flat_index:
                entry = (t_widget, t_flat, t_chunk, t_fi)
                break
        if entry is None:
            return

        widget, _, chunk_idx, fi = entry
        chunk_data = self.selection_data[chunk_idx]
        current_frame = chunk_data["selected_frames"][fi]

        picker = WanFramePickerDialog(
            self,
            chunk_data["abs_start"],
            chunk_data["abs_end"],
            current_frame,
            self.load_frame_fn,
        )
        if picker.exec() == QDialog.DialogCode.Accepted:
            new_frame = picker.picked_frame
            chunk_data["selected_frames"][fi] = new_frame
            self._set_thumbnail_pixmap(widget, new_frame)
            widget.setToolTip(f"Frame {new_frame}  (click to replace)")

    def get_all_selected_frames(self):
        """Return the (possibly modified) selection data."""
        return self.selection_data


class WanPreparationDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Wan Preparation")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QFormLayout(self)
        self.plan_info = QLabel()
        self.plan_info.setWordWrap(True)
        layout.addRow(self.plan_info)

        default_output_folder = parent.get_default_export_folder()
        self.output_folder = QLineEdit(default_output_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.output_folder)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self.browse_output_folder)
        folder_layout.addWidget(browse_btn)
        layout.addRow("Output Folder:", folder_layout)

        if getattr(parent.project, "is_video", False) and hasattr(
            parent.project, "video_path"
        ):
            default_name = os.path.splitext(os.path.basename(parent.project.video_path))[0]
        else:
            default_name = parent.project.name
        self.filename_prefix = QLineEdit(sanitize_filename_part(default_name))
        layout.addRow("Filename Prefix:", self.filename_prefix)

        self.start_spinbox = QSpinBox()
        self.start_spinbox.setRange(0, parent.total_frames - 1)
        self.start_spinbox.setValue(0)
        self.start_spinbox.valueChanged.connect(self.update_chunk_preview)
        layout.addRow("Start Frame:", self.start_spinbox)

        self.end_spinbox = QSpinBox()
        self.end_spinbox.setRange(0, parent.total_frames - 1)
        self.end_spinbox.setValue(parent.total_frames - 1)
        self.end_spinbox.valueChanged.connect(self.update_chunk_preview)
        layout.addRow("End Frame:", self.end_spinbox)

        self.grid_combo = QComboBox()
        self.grid_combo.addItem("Auto (Dynamic)", None)
        self.grid_combo.addItem("2x2 Grid", "2x2")
        self.grid_combo.addItem("3x3 Grid", "3x3")
        layout.addRow("Grid Size:", self.grid_combo)

        self.per_chunk_grid_checkbox = QCheckBox("One grid per chunk")
        self.per_chunk_grid_checkbox.setChecked(False)
        layout.addRow("Grid Mode:", self.per_chunk_grid_checkbox)

        self.chunk_size_spinbox = QSpinBox()
        self.chunk_size_spinbox.setRange(1, 10000)
        self.chunk_size_spinbox.setValue(WAN_CHUNK_SIZE)
        self.chunk_size_spinbox.valueChanged.connect(self.update_chunk_preview)
        layout.addRow("Chunk Size:", self.chunk_size_spinbox)

        self.overlap_checkbox = QCheckBox("Enable overlap")
        self.overlap_checkbox.toggled.connect(self.update_overlap_state)
        self.overlap_spinbox = QSpinBox()
        self.overlap_spinbox.setRange(WAN_OVERLAP_MIN, WAN_OVERLAP_MAX)
        self.overlap_spinbox.setValue(8)
        self.overlap_spinbox.setEnabled(False)
        self.overlap_spinbox.valueChanged.connect(self.update_chunk_preview)

        overlap_layout = QHBoxLayout()
        overlap_layout.addWidget(self.overlap_checkbox)
        overlap_layout.addWidget(self.overlap_spinbox)
        overlap_layout.addWidget(QLabel("frames"))
        overlap_layout.addStretch()
        layout.addRow("Overlap:", overlap_layout)

        self.chunk_label = QLabel()
        self.chunk_label.setWordWrap(True)
        layout.addRow("Chunk Rule:", self.chunk_label)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 10)
        self.quality_slider.setValue(5)
        self.quality_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.quality_slider.setTickInterval(1)

        self.quality_label = QLabel("Quality: 5 (Balanced)")
        self.quality_slider.valueChanged.connect(self.update_quality_label)

        quality_layout = QVBoxLayout()
        quality_layout.addWidget(self.quality_label)
        quality_layout.addWidget(self.quality_slider)
        layout.addRow("Compression:", quality_layout)

        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["ultrafast", "fast", "medium", "slow"])
        self.speed_combo.setCurrentIndex(1)
        layout.addRow("Speed:", self.speed_combo)

        padding_hint = QLabel(
            "Short clips are padded by repeating the last frame until they land on a WAN 2.2-safe length."
        )
        padding_hint.setWordWrap(True)
        padding_hint.setStyleSheet("color: gray; font-size: 10px;")
        layout.addRow(padding_hint)

        self.include_audio_checkbox = QCheckBox("Include Audio")
        has_audio = getattr(parent, "_has_audio", False)
        self.include_audio_checkbox.setChecked(has_audio)
        self.include_audio_checkbox.setEnabled(has_audio)
        self.audio_hint = QLabel(
            "Source has audio: ✓" if has_audio else "Source has no audio track."
        )
        self.audio_hint.setStyleSheet("color: gray; font-size: 10px;")
        audio_layout = QVBoxLayout()
        audio_layout.addWidget(self.include_audio_checkbox)
        audio_layout.addWidget(self.audio_hint)
        layout.addRow("Audio:", audio_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.update_chunk_preview()

    def get_chunk_size(self):
        return normalize_wan_chunk_size(self.chunk_size_spinbox.value())

    def get_overlap(self):
        if not self.overlap_checkbox.isChecked():
            return 0
        return normalize_chunk_overlap(
            self.overlap_spinbox.value(), self.get_chunk_size()
        )

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder.setText(folder)

    def update_overlap_state(self, checked=False):
        self.overlap_spinbox.setEnabled(self.overlap_checkbox.isChecked())
        self.update_chunk_preview()

    def update_chunk_preview(self, *_args):
        start_f = self.start_spinbox.value()
        end_f = self.end_spinbox.value()
        if start_f > end_f:
            self.plan_info.setText("Invalid frame range: Start > End")
            return

        total_span = end_f - start_f + 1

        requested_chunk_size = self.chunk_size_spinbox.value()
        snapped_chunk_size = normalize_wan_chunk_size(requested_chunk_size)

        max_overlap = min(WAN_OVERLAP_MAX, snapped_chunk_size - 1)
        overlap_available = max_overlap >= WAN_OVERLAP_MIN

        self.overlap_checkbox.setEnabled(overlap_available)
        if overlap_available:
            self.overlap_spinbox.setRange(WAN_OVERLAP_MIN, max_overlap)
            if self.overlap_spinbox.value() > max_overlap:
                self.overlap_spinbox.setValue(max_overlap)
        else:
            self.overlap_spinbox.setEnabled(False)
            if self.overlap_checkbox.isChecked():
                self.overlap_checkbox.blockSignals(True)
                self.overlap_checkbox.setChecked(False)
                self.overlap_checkbox.blockSignals(False)

        overlap = self.get_overlap()
        self.overlap_spinbox.setEnabled(
            overlap_available and self.overlap_checkbox.isChecked()
        )
        plans = plan_wan_chunks(total_span, snapped_chunk_size, overlap)

        target_lengths = [str(chunk.target_length) for chunk in plans]
        target_preview = ", ".join(target_lengths[:6])
        if len(target_lengths) > 6:
            target_preview += ", ..."

        raw_lengths = [
            str(chunk.source_length)
            if chunk.pad_count == 0
            else f"{chunk.source_length}->{chunk.target_length}"
            for chunk in plans
        ]
        raw_preview = ", ".join(raw_lengths[:6])
        if len(raw_lengths) > 6:
            raw_preview += ", ..."

        self.plan_info.setText(
            f"{total_span} source frames will export as "
            f"{len(plans)} WAN-safe clip(s): {target_preview}"
        )

        overlap_text = (
            f"{overlap}-frame overlap between chunks."
            if overlap
            else "Overlap off."
        )
        tail_padding = plans[-1].pad_count if plans else 0
        padding_text = (
            f"Only the final chunk is padded by {tail_padding} frame(s)."
            if tail_padding
            else "No trailing padding needed."
        )
        self.chunk_label.setText(
            f"Requested {requested_chunk_size} frames, using {snapped_chunk_size} "
            f"(nearest WAN-safe chunk rounded down). {overlap_text}\n"
            f"Source chunk lengths: {raw_preview}. {padding_text}"
        )

    def update_quality_label(self, val):
        if val <= 3:
            desc = "Small File"
        elif val <= 6:
            desc = "Balanced"
        else:
            desc = "High Quality"

        self.quality_label.setText(f"Quality: {val} ({desc})")


class MinimaxPreparationDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("MiniMax H3 Preparation")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QFormLayout(self)
        self.plan_info = QLabel()
        self.plan_info.setWordWrap(True)
        layout.addRow(self.plan_info)

        default_output_folder = parent.get_default_export_folder()
        self.output_folder = QLineEdit(default_output_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.output_folder)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self.browse_output_folder)
        folder_layout.addWidget(browse_btn)
        layout.addRow("Output Folder:", folder_layout)

        if getattr(parent.project, "is_video", False) and hasattr(
            parent.project, "video_path"
        ):
            default_name = os.path.splitext(os.path.basename(parent.project.video_path))[0]
        else:
            default_name = parent.project.name
        self.filename_prefix = QLineEdit(sanitize_filename_part(default_name))
        layout.addRow("Filename Prefix:", self.filename_prefix)

        self.start_spinbox = QSpinBox()
        self.start_spinbox.setRange(0, parent.total_frames - 1)
        self.start_spinbox.setValue(0)
        self.start_spinbox.valueChanged.connect(self.update_chunk_preview)
        layout.addRow("Start Frame:", self.start_spinbox)

        self.end_spinbox = QSpinBox()
        self.end_spinbox.setRange(0, parent.total_frames - 1)
        self.end_spinbox.setValue(parent.total_frames - 1)
        self.end_spinbox.valueChanged.connect(self.update_chunk_preview)
        layout.addRow("End Frame:", self.end_spinbox)

        self.grid_combo = QComboBox()
        self.grid_combo.addItem("Auto (Dynamic)", None)
        self.grid_combo.addItem("2x2 Grid", "2x2")
        self.grid_combo.addItem("3x3 Grid", "3x3")
        layout.addRow("Grid Size:", self.grid_combo)

        self.per_chunk_grid_checkbox = QCheckBox("One grid per chunk")
        self.per_chunk_grid_checkbox.setChecked(False)
        layout.addRow("Grid Mode:", self.per_chunk_grid_checkbox)

        self.chunk_size_spinbox = QSpinBox()
        self.chunk_size_spinbox.setRange(MINIMAX_MIN_FRAMES, 10000)
        self.chunk_size_spinbox.setValue(MINIMAX_DEFAULT_CHUNK)
        self.chunk_size_spinbox.valueChanged.connect(self.update_chunk_preview)
        layout.addRow("Chunk Size:", self.chunk_size_spinbox)

        self.overlap_checkbox = QCheckBox("Enable overlap")
        self.overlap_checkbox.toggled.connect(self.update_overlap_state)
        self.overlap_spinbox = QSpinBox()
        self.overlap_spinbox.setRange(MINIMAX_OVERLAP_MIN, MINIMAX_OVERLAP_MAX)
        self.overlap_spinbox.setValue(MINIMAX_STRIDE)
        self.overlap_spinbox.setEnabled(False)
        self.overlap_spinbox.valueChanged.connect(self.update_chunk_preview)

        overlap_layout = QHBoxLayout()
        overlap_layout.addWidget(self.overlap_checkbox)
        overlap_layout.addWidget(self.overlap_spinbox)
        overlap_layout.addWidget(QLabel("frames"))
        overlap_layout.addStretch()
        layout.addRow("Overlap:", overlap_layout)

        self.chunk_label = QLabel()
        self.chunk_label.setWordWrap(True)
        layout.addRow("Chunk Rule:", self.chunk_label)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 10)
        self.quality_slider.setValue(5)
        self.quality_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.quality_slider.setTickInterval(1)

        self.quality_label = QLabel("Quality: 5 (Balanced)")
        self.quality_slider.valueChanged.connect(self.update_quality_label)

        quality_layout = QVBoxLayout()
        quality_layout.addWidget(self.quality_label)
        quality_layout.addWidget(self.quality_slider)
        layout.addRow("Compression:", quality_layout)

        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["ultrafast", "fast", "medium", "slow"])
        self.speed_combo.setCurrentIndex(1)
        layout.addRow("Speed:", self.speed_combo)

        padding_hint = QLabel(
            "Short clips are padded by repeating the last frame until they land on a MiniMax H3-safe length (17k + 5)."
        )
        padding_hint.setWordWrap(True)
        padding_hint.setStyleSheet("color: gray; font-size: 10px;")
        layout.addRow(padding_hint)

        self.include_audio_checkbox = QCheckBox("Include Audio")
        has_audio = getattr(parent, "_has_audio", False)
        self.include_audio_checkbox.setChecked(has_audio)
        self.include_audio_checkbox.setEnabled(has_audio)
        self.audio_hint = QLabel(
            "Source has audio: ✓" if has_audio else "Source has no audio track."
        )
        self.audio_hint.setStyleSheet("color: gray; font-size: 10px;")
        audio_layout = QVBoxLayout()
        audio_layout.addWidget(self.include_audio_checkbox)
        audio_layout.addWidget(self.audio_hint)
        layout.addRow("Audio:", audio_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.update_chunk_preview()

    def get_chunk_size(self):
        return normalize_minimax_chunk_size(self.chunk_size_spinbox.value())

    def get_overlap(self):
        if not self.overlap_checkbox.isChecked():
            return 0
        return normalize_minimax_overlap(
            self.overlap_spinbox.value(), self.get_chunk_size()
        )

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder.setText(folder)

    def update_overlap_state(self, checked=False):
        self.overlap_spinbox.setEnabled(self.overlap_checkbox.isChecked())
        self.update_chunk_preview()

    def update_chunk_preview(self, *_args):
        start_f = self.start_spinbox.value()
        end_f = self.end_spinbox.value()
        if start_f > end_f:
            self.plan_info.setText("Invalid frame range: Start > End")
            return

        total_span = end_f - start_f + 1
        requested_chunk_size = self.chunk_size_spinbox.value()
        snapped_chunk_size = normalize_minimax_chunk_size(requested_chunk_size)

        max_overlap = min(MINIMAX_OVERLAP_MAX, snapped_chunk_size - MINIMAX_MIN_FRAMES)
        overlap_available = max_overlap >= MINIMAX_OVERLAP_MIN

        self.overlap_checkbox.setEnabled(overlap_available)
        if overlap_available:
            self.overlap_spinbox.setRange(MINIMAX_OVERLAP_MIN, max_overlap)
            if self.overlap_spinbox.value() > max_overlap:
                self.overlap_spinbox.setValue(max_overlap)
        else:
            self.overlap_spinbox.setEnabled(False)
            if self.overlap_checkbox.isChecked():
                self.overlap_checkbox.blockSignals(True)
                self.overlap_checkbox.setChecked(False)
                self.overlap_checkbox.blockSignals(False)

        overlap = self.get_overlap()
        self.overlap_spinbox.setEnabled(
            overlap_available and self.overlap_checkbox.isChecked()
        )
        plans = plan_minimax_chunks(total_span, snapped_chunk_size, overlap)

        target_lengths = [str(chunk.target_length) for chunk in plans]
        target_preview = ", ".join(target_lengths[:6])
        if len(target_lengths) > 6:
            target_preview += ", ..."

        raw_lengths = [
            str(chunk.source_length)
            if chunk.pad_count == 0
            else f"{chunk.source_length}->{chunk.target_length}"
            for chunk in plans
        ]
        raw_preview = ", ".join(raw_lengths[:6])
        if len(raw_lengths) > 6:
            raw_preview += ", ..."

        self.plan_info.setText(
            f"{total_span} source frames will export as "
            f"{len(plans)} MiniMax H3-safe clip(s): {target_preview}"
        )

        overlap_text = (
            f"{overlap}-frame overlap between chunks."
            if overlap
            else "Overlap off."
        )
        tail_padding = plans[-1].pad_count if plans else 0
        padding_text = (
            f"Only the final chunk is padded by {tail_padding} frame(s)."
            if tail_padding
            else "No trailing padding needed."
        )
        self.chunk_label.setText(
            f"Requested {requested_chunk_size} frames, using {snapped_chunk_size} "
            f"(nearest MiniMax H3-safe chunk rounded down). {overlap_text}\n"
            f"Source chunk lengths: {raw_preview}. {padding_text}"
        )

    def update_quality_label(self, val):
        if val <= 3:
            desc = "Small File"
        elif val <= 6:
            desc = "Balanced"
        else:
            desc = "High Quality"
        self.quality_label.setText(f"Quality: {val} ({desc})")
