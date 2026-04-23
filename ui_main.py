import json
import os
import threading
from datetime import datetime

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

        export_mp4_action = QAction("Export MP4...", self)
        export_mp4_action.triggered.connect(self.show_export_mp4_dialog)
        file_menu.addAction(export_mp4_action)

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

    def load_settings(self):
        settings_path = os.path.join(
            os.path.expanduser("~"), ".kfpro_lite_settings.json"
        )
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
            except:
                pass

    def save_settings(self):
        settings_path = os.path.join(
            os.path.expanduser("~"), ".kfpro_lite_settings.json"
        )
        settings = {
            "cache_size": self.cache_size_mb,
            "default_fps": self.fps,
            "export_folder": self.export_folder,
            "audio_scrub": self.audio_scrub,
            "scrub_sensitivity": self.scrub_sensitivity,
            "auto_save": self.auto_save_enabled,
        }
        with open(settings_path, "w") as f:
            json.dump(settings, f)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.project.folder = folder
            self.scan_folder(folder)

    def scan_folder(self, folder):
        from viewer import detect_sequence

        # Reset video state when loading folder
        if hasattr(self.project, "is_video"):
            self.project.is_video = False
        if hasattr(self.project, "video_path"):
            delattr(self.project, "video_path")

        sequences = detect_sequence(folder)

        if sequences:
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
        else:
            QMessageBox.warning(
                self, "No Sequences", "No image sequences found in the selected folder."
            )

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

    def load_video(self, file_path):
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
                return
        else:
            # Regular video handling with OpenCV
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                QMessageBox.warning(
                    self, "Error", f"Could not open video file: {file_path}"
                )
                return

            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

        # Clear existing sources when loading a video
        self.project.sources = []

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

        copy_action = QAction("📋 Copy to Clipboard (Fastest Email Paste)", self)
        copy_action.setToolTip("Copy the current frame to paste directly into an email")
        copy_action.triggered.connect(self.copy_frame_to_clipboard)
        menu.addAction(copy_action)

        save_action = QAction("📸 Save Frame As... (Best Quality JPG)", self)
        save_action.setToolTip(
            "Fast, high-quality save optimized for email attachments"
        )
        save_action.triggered.connect(self.save_frame_for_email)
        menu.addAction(save_action)

        menu.exec(self.viewer.mapToGlobal(position))

    def copy_frame_to_clipboard(self):
        if not self.viewer.current_pixmap:
            return
        clipboard = QApplication.clipboard()
        clipboard.setPixmap(self.viewer.current_pixmap)
        self.statusBar().showMessage(
            "✅ Frame copied to clipboard. Ready to paste!", 4000
        )

    def save_frame_for_email(self):
        if not self.viewer.current_pixmap:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        default_name = os.path.join(
            desktop_path, f"KFPlayer_Frame_{self.current_frame + 1}_{timestamp}.jpg"
        )

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save Frame for Email",
            default_name,
            "JPEG Image (*.jpg);;PNG Image (*.png)",
        )

        if filepath:
            try:
                if filepath.lower().endswith(".jpg") or filepath.lower().endswith(
                    ".jpeg"
                ):
                    self.viewer.current_pixmap.save(filepath, "JPG", quality=95)
                else:
                    self.viewer.current_pixmap.save(filepath, "PNG", quality=-1)

                self.statusBar().showMessage(
                    f"✅ Frame saved successfully: {os.path.basename(filepath)}", 4000
                )
            except Exception as e:
                QMessageBox.warning(self, "Save Error", f"Failed to save image: {e}")

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
                    self.scan_folder(folder)

                    if "timeline" in project_data:
                        self.current_frame = project_data["timeline"].get("current", 0)
                        self.seek_to_frame(self.current_frame)

                    if "bookmarks" in project_data:
                        self.bookmarks = project_data["bookmarks"]
                        self.update_bookmark_list()
                        for bm in self.bookmarks:
                            self.timeline.add_bookmark(bm["frame"])

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

    def export_mp4(self, filepath, start_frame, end_frame, quality, preset="fast"):
        import imageio
        import numpy as np

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
            fps = (
                self.project.video_fps
                if getattr(self.project, "is_video", False)
                and hasattr(self.project, "video_fps")
                else self.fps
            )
            fps = int(fps) if fps > 0 else 24

            # Map simple 1-10 quality to FFMPEG CRF range (roughly 35 to 15, lower is better quality/bigger file)
            # FFMPEG H264 defaults to about 23.
            crf = int(35 - ((quality - 1) * (20 / 9)))

            writer = imageio.get_writer(
                filepath,
                format="FFMPEG",
                mode="I",
                fps=fps,
                codec="libx264",
                macro_block_size=None,
                quality=None,
                output_params=["-crf", str(crf), "-preset", preset],
            )

            for f in range(start_frame, end_frame + 1):
                pixmap = self.load_frame_data(f)
                if pixmap:
                    img = pixmap.toImage()
                    img = img.convertToFormat(QImage.Format.Format_RGB888)

                    ptr = img.bits()
                    ptr.setsize(img.sizeInBytes())

                    height = img.height()
                    width = img.width()
                    arr = np.array(ptr).reshape((height, img.bytesPerLine()))
                    arr = arr[:, : width * 3].reshape((height, width, 3))

                    writer.append_data(arr)

                bar.setValue(f)
                QApplication.processEvents()

            writer.close()
            QMessageBox.information(
                self,
                "Export Complete",
                f"Successfully exported frames {start_frame}-{end_frame}",
            )
        except Exception as e:
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
        self.format_combo.addItems(["PNG", "JPEG", "TIFF", "EXR"])
        layout.addRow("Format:", self.format_combo)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(90)
        layout.addRow("JPEG Quality:", self.quality_slider)

        self.output_folder = QLineEdit(
            parent.export_folder if parent.export_folder else ""
        )
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
        format_ext = self.format_combo.currentText().lower()

        if self.export_mode == "single":
            frame = parent.load_frame_data(parent.current_frame)
            if frame:
                filename = self.filename_pattern.text().replace(
                    "####", f"{parent.current_frame:04d}"
                )
                filepath = os.path.join(self.output_folder.text(), filename)
                frame.save(filepath)
                QMessageBox.information(
                    self, "Export Complete", f"Frame exported to {filepath}"
                )
        else:
            QMessageBox.information(
                self, "Export Complete", "Sequence export functionality coming soon!"
            )

        self.accept()


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


from PyQt6.QtWidgets import QSizePolicy, QRadioButton
