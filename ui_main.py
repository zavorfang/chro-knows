import json
import os
import shutil
import threading

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
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QPointF, QRectF
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
from wan_chunks import (
    WAN_CHUNK_SIZE,
    WAN_OVERLAP_MAX,
    WAN_OVERLAP_MIN,
    normalize_chunk_overlap,
    normalize_wan_chunk_size,
    plan_wan_chunks,
)
from app_utils import (
    IMAGE_EXPORT_FILTER,
    IMAGE_EXPORT_FORMATS,
    build_bookmark_export_filename,
    build_frame_export_filename,
    build_recent_file_label,
    ensure_extension,
    normalize_image_format,
    normalize_recent_files,
    push_recent_file,
    sanitize_filename_part,
)


class MainWindow(QMainWindow):
    frame_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Keyframe Pro Lite")
        self.setGeometry(100, 100, 1400, 900)
        self.setMinimumSize(1000, 700)

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
        right_layout.addWidget(QLabel("Bookmarks"))
        right_layout.addWidget(self.bookmark_list)

        add_bookmark_btn = QPushButton("+ Add Bookmark")
        add_bookmark_btn.clicked.connect(self.add_bookmark)
        right_layout.addWidget(add_bookmark_btn)

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

        export_action = QAction("Export...", self)
        export_action.setShortcut(QKeySequence.StandardKey.Print)
        export_action.triggered.connect(self.show_export_dialog)
        file_menu.addAction(export_action)

        export_current_frame_action = QAction("Export Current Frame Image...", self)
        export_current_frame_action.triggered.connect(self.export_current_frame_image)
        file_menu.addAction(export_current_frame_action)

        export_first_frame_action = QAction("Export First Frame Image...", self)
        export_first_frame_action.triggered.connect(self.export_first_frame_image)
        file_menu.addAction(export_first_frame_action)

        export_last_frame_action = QAction("Export Last Frame Image...", self)
        export_last_frame_action.triggered.connect(self.export_last_frame_image)
        file_menu.addAction(export_last_frame_action)

        export_bookmarks_action = QAction("Export Bookmarks as Images...", self)
        export_bookmarks_action.triggered.connect(self.show_export_bookmarks_dialog)
        file_menu.addAction(export_bookmarks_action)

        export_mp4_action = QAction("Export MP4...", self)
        export_mp4_action.triggered.connect(self.show_export_mp4_dialog)
        file_menu.addAction(export_mp4_action)

        wan_prep_action = QAction("Wan Preparation...", self)
        wan_prep_action.triggered.connect(self.show_wan_preparation_dialog)
        file_menu.addAction(wan_prep_action)

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

        help_menu = menubar.addMenu("Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def init_timeline(self):
        # Overview bar (thin, full-width, no thumbnails)
        self.overview_timeline = OverviewTimelineWidget(self)
        self.overview_timeline.frame_selected.connect(self.seek_to_frame)
        self.timeline_layout.addWidget(self.overview_timeline)

        # Thumbnail timeline (scrollable, for fine scrubbing)
        self.timeline = TimelineWidget(self)
        self.timeline.frame_selected.connect(self.seek_to_frame)

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

    def get_settings_path(self):
        return os.path.join(os.path.expanduser("~"), ".kfpro_lite_settings.json")

    def get_default_export_folder(self):
        if self.export_folder and os.path.isdir(self.export_folder):
            return self.export_folder
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
        self.frame_cache = {}
        self.timeline.thumbnails.clear()
        self.timeline.bookmarks.clear()
        self.timeline.set_playhead(0)
        self.overview_timeline.bookmarks.clear()
        self.overview_timeline.set_playhead(0)
        if clear_bookmarks:
            self.bookmarks = []
            self.update_bookmark_list()

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
                    self.scrub_sensitivity = settings.get("scrub_sensitivity", 5)
                    self.auto_save_enabled = settings.get("auto_save", True)
                    self.recent_files = normalize_recent_files(
                        settings.get("recent_files", [])
                    )
            except:
                pass

    def save_settings(self):
        settings_path = self.get_settings_path()
        settings = {
            "cache_size": self.cache_size_mb,
            "default_fps": self.fps,
            "export_folder": self.export_folder,
            "audio_scrub": self.audio_scrub,
            "scrub_sensitivity": self.scrub_sensitivity,
            "auto_save": self.auto_save_enabled,
            "recent_files": self.recent_files,
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

            self.project.add_source(folder, sequences[0])
            self.total_frames = len(sequences[0]["files"])
            self.current_frame = 0
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
                # Regular video handling with OpenCV
                cap = cv2.VideoCapture(video_path)
                if not cap.isOpened():
                    return None

                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                cap.release()

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

    def play_step(self):
        if self.is_playing:
            self.current_frame += 1

            if self.current_frame >= self.total_frames:
                if self.loop_enabled:
                    self.current_frame = 0
                else:
                    self.is_playing = False
                    self.play_pause_btn.setText("▶")
                    self.play_timer.stop()
                    return

            self.load_frame(self.current_frame)
            self.update_frame_display()
            self.timeline.set_playhead(self.current_frame)
            self.overview_timeline.set_playhead(self.current_frame)
            self.sync_timeline_scroll()

    def toggle_play(self):
        self.is_playing = not self.is_playing

        if self.is_playing:
            self.play_pause_btn.setText("❚❚")
            # Use video FPS if available, otherwise use project FPS
            fps = self.fps
            if getattr(self.project, "is_video", False) and hasattr(
                self.project, "video_fps"
            ):
                fps = int(self.project.video_fps) if self.project.video_fps > 0 else 24
            interval = int(1000 / (fps * self.playback_speed))
            self.play_timer.start(interval)
        else:
            self.play_pause_btn.setText("▶")
            self.play_timer.stop()

    def prev_frame(self):
        if self.current_frame > 0:
            self.current_frame -= 1
            self.load_frame(self.current_frame)
            self.update_frame_display()
            self.timeline.set_playhead(self.current_frame)
            self.overview_timeline.set_playhead(self.current_frame)

    def next_frame(self):
        if self.current_frame < self.total_frames - 1:
            self.current_frame += 1
            self.load_frame(self.current_frame)
            self.update_frame_display()
            self.timeline.set_playhead(self.current_frame)
            self.overview_timeline.set_playhead(self.current_frame)

    def jump_to_start(self):
        self.current_frame = 0
        self.load_frame(0)
        self.update_frame_display()
        self.timeline.set_playhead(0)
        self.overview_timeline.set_playhead(0)

    def jump_to_end(self):
        self.current_frame = max(0, self.total_frames - 1)
        self.load_frame(self.current_frame)
        self.update_frame_display()
        self.timeline.set_playhead(self.current_frame)
        self.overview_timeline.set_playhead(self.current_frame)

    def toggle_loop(self):
        self.loop_enabled = not self.loop_enabled

    def set_speed(self, speed_text):
        speed_map = {"0.25x": 0.25, "0.5x": 0.5, "1x": 1.0, "2x": 2.0}
        self.playback_speed = speed_map.get(speed_text, 1.0)

        if self.is_playing:
            self.play_timer.stop()
            interval = int(1000 / (self.fps * self.playback_speed))
            self.play_timer.start(interval)

    def update_frame_display(self):
        self.frame_label.setText(
            f"Frame: {self.current_frame + 1} / {self.total_frames}"
        )

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

        export_bookmarks_action = QAction("Export Bookmarks as Images...", self)
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

        output_folder = dialog.output_folder.text().strip()
        prefix = dialog.filename_prefix.text().strip()
        format_name = dialog.get_format_name()
        jpeg_quality = dialog.jpeg_quality.value()

        if not output_folder:
            QMessageBox.warning(self, "Export", "Please choose an output folder.")
            return

        self.export_bookmarks_as_images(
            output_folder,
            prefix,
            format_name,
            jpeg_quality=jpeg_quality,
        )

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
            self.seek_to_frame(bookmark_data["frame"])

    def add_bookmark(self):
        if self.total_frames == 0:
            return

        bookmark = {
            "frame": self.current_frame,
            "name": f"Bookmark {len(self.bookmarks) + 1}",
            "color": "#ff6b35",
        }

        self.bookmarks.append(bookmark)
        self.update_bookmark_list()
        self.timeline.add_bookmark(self.current_frame)
        self.overview_timeline.add_bookmark(self.current_frame)

    def update_bookmark_list(self):
        self.bookmark_list.clear()

        for bm in sorted(self.bookmarks, key=lambda x: x["frame"]):
            item = QListWidgetItem(f"Frame {bm['frame'] + 1}: {bm['name']}")
            item.setData(Qt.ItemDataRole.UserRole, bm)

            color = QColor(bm.get("color", "#ff6b35"))
            item.setForeground(color)

            self.bookmark_list.addItem(item)

    def show_bookmark_context_menu(self, position):
        item = self.bookmark_list.itemAt(position)
        if item:
            menu = QMenu()
            export_action = QAction("Export Bookmark Image...", self)
            export_action.triggered.connect(
                lambda: self.export_selected_bookmark_image(item)
            )
            menu.addAction(export_action)

            export_all_action = QAction("Export All Bookmarks as Images...", self)
            export_all_action.triggered.connect(self.show_export_bookmarks_dialog)
            export_all_action.setEnabled(bool(self.bookmarks))
            menu.addAction(export_all_action)

            menu.addSeparator()
            delete_action = QAction("Delete Bookmark", self)
            delete_action.triggered.connect(lambda: self.delete_bookmark(item))
            menu.addAction(delete_action)
            menu.exec(self.bookmark_list.mapToGlobal(position))

    def delete_bookmark(self, item):
        bookmark_data = item.data(Qt.ItemDataRole.UserRole)
        if bookmark_data:
            frame = bookmark_data["frame"]
            self.bookmarks = [b for b in self.bookmarks if b["frame"] != frame]
            self.timeline.remove_bookmark(frame)
            self.overview_timeline.remove_bookmark(frame)
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

        if self.project.sources:
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

            if project_data.get("sources"):
                source_data = project_data["sources"][0]
                folder = source_data.get("absolute", source_data.get("path", ""))

                if os.path.exists(folder):
                    self.project.folder = folder
                    self.scan_folder(folder, add_to_recent=False)

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
            if filepath:
                self.export_mp4(filepath, start_frame, end_frame, quality, preset)

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

            self.prepare_wan(
                output_folder, prefix, chunk_size, overlap, quality, preset,
                start_frame, end_frame, grid_size, per_chunk_grid
            )

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
        self, filepath, frame_numbers, quality, preset="fast", progress_callback=None
    ):
        import imageio

        if not filepath.endswith(".mp4"):
            filepath += ".mp4"

        writer = imageio.get_writer(
            filepath,
            format="FFMPEG",
            mode="I",
            fps=self.get_export_fps(),
            codec="libx264",
            macro_block_size=None,
            quality=None,
            output_params=["-crf", str(self.quality_to_crf(quality)), "-preset", preset],
        )

        try:
            total = len(frame_numbers)
            for output_index, source_frame in enumerate(frame_numbers, start=1):
                pixmap = self.load_frame_data(source_frame)
                if pixmap is None:
                    raise ValueError(f"Could not load frame {source_frame} for export.")

                writer.append_data(self.pixmap_to_rgb_array(pixmap))

                if progress_callback:
                    progress_callback(output_index, total, source_frame)
        finally:
            writer.close()

    def export_mp4(self, filepath, start_frame, end_frame, quality, preset="fast"):
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

            self.write_mp4_file(
                filepath,
                frame_numbers,
                quality,
                preset,
                progress_callback=update_progress,
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
        start_frame, end_frame, grid_size, per_chunk_grid=False
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
                
                filename = (
                    f"{prefix}_wan22_{chunk_index:03d}_"
                    f"{chunk.target_length:03d}f_"
                    f"{abs_start:04d}-{abs_end:04d}.mp4"
                )
                filepath = os.path.join(output_folder, filename)

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

                self.write_mp4_file(
                    filepath,
                    frame_numbers,
                    quality,
                    preset,
                    progress_callback=update_progress,
                )

                completed_frames += len(frame_numbers)

                k_i = k_list[chunk_index - 1]
                span = abs_end - abs_start
                if span == 0:
                    indices = [abs_start] * k_i
                else:
                    indices = [abs_start + i * span // (k_i - 1) for i in range(k_i)]
                
                chunk_images = []
                for idx in indices:
                    pixmap = self.load_frame_data(idx)
                    if pixmap:
                        img_rgb = self.pixmap_to_rgb_array(pixmap)
                        chunk_images.append(img_rgb)
                    else:
                        chunk_images.append(np.zeros((256, 256, 3), dtype=np.uint8))
                        
                all_images.extend(chunk_images)
                selection_details.append({
                    "chunk_index": chunk_index - 1,
                    "chunk_data": asdict(chunk),
                    "video_start_frame_abs": abs_start,
                    "video_end_frame_abs": abs_end,
                    "selected_frames_abs": indices
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
                        batch.append(np.zeros((h, w, 3), dtype=np.uint8))
                    
                    rows = []
                    for r in range(best_dim):
                        row_images = batch[r*best_dim : (r+1)*best_dim]
                        row_images = [cv2.resize(img, (w, h)) for img in row_images]
                        rows.append(np.hstack(row_images))
                        
                    grid = np.vstack(rows)
                    grids.append(grid)
            
            saved_grids = []
            for i, grid in enumerate(grids):
                if per_chunk_grid:
                    grid_filename = f"{prefix}_chunk_{i+1:03d}_grid_{best_dim}x{best_dim}.jpg"
                else:
                    grid_filename = f"{prefix}_grid_{best_dim}x{best_dim}_{i:03d}.jpg"
                grid_path = os.path.join(output_folder, grid_filename)
                
                # Write to disk
                frame_bgr = cv2.cvtColor(grid, cv2.COLOR_RGB2BGR)
                params = [cv2.IMWRITE_JPEG_QUALITY, 95]
                cv2.imwrite(grid_path, frame_bgr, params)
                saved_grids.append(grid_filename)
                
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

        self.export_folder = QLineEdit(parent.export_folder)
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
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self.browse_output_folder)
        folder_layout.addWidget(browse_btn)
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
        self.setWindowTitle("Export Bookmarks as Images")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QFormLayout(self)

        info = QLabel(
            f"{len(parent.bookmarks)} bookmark(s) will export at source resolution."
        )
        info.setWordWrap(True)
        layout.addRow(info)

        self.output_folder = QLineEdit(parent.get_default_export_folder())
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.output_folder)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self.browse_output_folder)
        folder_layout.addWidget(browse_btn)
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

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.update_quality_state(self.format_combo.currentText())

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder.setText(folder)

    def get_format_name(self):
        return self.format_combo.currentText()

    def update_quality_label(self, value):
        self.jpeg_quality_label.setText(f"JPEG Quality: {value}")

    def update_quality_state(self, format_name):
        is_jpeg = format_name == "JPEG"
        self.jpeg_quality.setEnabled(is_jpeg)
        self.jpeg_quality_label.setEnabled(is_jpeg)


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

        if parent.export_folder:
            default_output_folder = parent.export_folder
        elif getattr(parent.project, "is_video", False) and hasattr(parent.project, "video_path"):
            default_output_folder = os.path.dirname(parent.project.video_path)
        else:
            default_output_folder = parent.project.folder

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
