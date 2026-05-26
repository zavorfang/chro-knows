import sys
import os
from typing import Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QMenu, QToolBar, QStatusBar, QMessageBox, QFileDialog,
    QInputDialog, QLabel, QFrame, QDialog, QDialogButtonBox, QSplitter
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QCloseEvent

from .models import Project, MediaSource, Bookmark, FrameMetadata
from .engine import PlayerEngine
from .widgets import (
    ViewerWidget, TimelineWidget, SourceListWidget, PlaybackControls,
    BookmarksPanel
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KFPlayer - Animation Review")
        self.setMinimumSize(640, 480)
        
        self.project: Project = Project()
        self.engine = PlayerEngine()
        
        self.is_playing = False
        self.playback_speed = 1.0
        self.hold_frame = False
        self.current_frame = 0
        self.current_source_id: Optional[str] = None
        
        self.selection_start: Optional[int] = None
        self.selection_end: Optional[int] = None
        self.selection_mode = False
        
        self._setup_ui()
        self._setup_menu()
        self._setup_timer()
        
        self.showMaximized()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(2)
        
        self.viewer = ViewerWidget()
        left_layout.addWidget(self.viewer, 1)
        
        self.controls = PlaybackControls()
        left_layout.addWidget(self.controls)
        
        self.timeline = TimelineWidget()
        left_layout.addWidget(self.timeline)
        
        self.source_list = SourceListWidget()
        left_layout.addWidget(self.source_list)
        
        self.bookmarks_panel = BookmarksPanel()
        
        content_splitter.addWidget(left_widget)
        content_splitter.addWidget(self.bookmarks_panel)
        content_splitter.setStretchFactor(0, 1)
        content_splitter.setStretchFactor(1, 0)
        
        main_layout.addWidget(content_splitter)
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("No project loaded")
        self.status_bar.addWidget(self.status_label)

        self.controls.play_pause_clicked.connect(self.toggle_play)
        self.controls.step_back_clicked.connect(self.step_back)
        self.controls.step_forward_clicked.connect(self.step_forward)
        self.controls.jump_start_clicked.connect(self.jump_to_start)
        self.controls.jump_end_clicked.connect(self.jump_to_end)
        self.controls.hold_toggled.connect(self.set_hold)
        self.controls.speed_combo.currentTextChanged.connect(self.set_speed)
        self.controls.fps_combo.currentTextChanged.connect(self.set_fps)
        
        self.timeline.seek_requested.connect(self.seek_to_frame)
        
        self.viewer.zoom_changed.connect(self.on_viewer_zoom_changed)
        self.viewer.pan_changed.connect(self.on_viewer_pan_changed)
        
        self.source_list.itemClicked.connect(self.on_source_selected)
        
        self.bookmarks_panel.btn_add_bm.clicked.connect(lambda: self.add_bookmark("single"))
        self.bookmarks_panel.btn_add_range.clicked.connect(lambda: self.add_bookmark("range"))
        self.bookmarks_panel.btn_export.clicked.connect(self.export_bookmarks)
        self.bookmarks_panel.bookmark_list.itemDoubleClicked.connect(self.on_bookmark_activated)
        self.bookmarks_panel.note_edit.textChanged.connect(self.on_note_changed)
        self.bookmarks_panel.hold_check.toggled.connect(self.on_hold_changed)

    def _setup_menu(self):
        menubar = self.menuBar()
        
        file_menu = menubar.addMenu("File")
        
        new_action = QAction("New Project", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.new_project)
        
        open_action = QAction("Open Project", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_project)
        
        save_action = QAction("Save Project", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_project)
        
        add_sources_action = QAction("Add Sources...", self)
        add_sources_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        add_sources_action.triggered.connect(self.add_sources)
        
        export_action = QAction("Export Frame...", self)
        export_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        export_action.triggered.connect(self.export_current_frame)
        
        file_menu.addAction(new_action)
        file_menu.addAction(open_action)
        file_menu.addAction(save_action)
        file_menu.addSeparator()
        file_menu.addAction(add_sources_action)
        file_menu.addAction(export_action)
        
        edit_menu = menubar.addMenu("Edit")
        
        add_bm_action = QAction("Add Bookmark", self)
        add_bm_action.setShortcut(QKeySequence("B"))
        add_bm_action.triggered.connect(lambda: self.add_bookmark("single"))
        
        add_range_action = QAction("Add Range Bookmark", self)
        add_range_action.setShortcut(QKeySequence("R"))
        add_range_action.triggered.connect(lambda: self.add_bookmark("range"))
        
        edit_menu.addAction(add_bm_action)
        edit_menu.addAction(add_range_action)
        
        view_menu = menubar.addMenu("View")
        
        reset_view_action = QAction("Reset View", self)
        reset_view_action.setShortcut(QKeySequence("0"))
        reset_view_action.triggered.connect(self.reset_view)
        
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
        zoom_in_action.triggered.connect(self.zoom_in)
        
        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        zoom_out_action.triggered.connect(self.zoom_out)
        
        view_menu.addAction(reset_view_action)
        view_menu.addAction(zoom_in_action)
        view_menu.addAction(zoom_out_action)

    def _setup_timer(self):
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self.playback_tick)
        
        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self.auto_save)
        self.auto_save_timer.start(30000)

    def new_project(self):
        if self.project.project_path:
            reply = QMessageBox.question(
                self, "Save Project?",
                "Save current project first?",
                QMessageBox.StandardButton.Save | 
                QMessageBox.StandardButton.Discard | 
                QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Save:
                self.save_project()
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder")
        if folder:
            name, ok = QInputDialog.getText(self, "Project Name", "Enter project name:")
            if not ok or not name:
                name = "Untitled"
            
            project_path = os.path.join(folder, f"{name}.kfp_basic")
            self.project = Project(name=name)
            self.project.new_project(name, project_path)
            self._update_ui()
            self.status_label.setText(f"New project: {name}")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            "KFPlayer Project (*.kfp_basic)"
        )
        if path:
            try:
                self.project = Project.load(path)
                self._load_sources()
                self._update_ui()
                self.status_label.setText(f"Opened: {self.project.name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open project: {e}")

    def save_project(self):
        if not self.project.project_path:
            folder = QFileDialog.getExistingDirectory(self, "Select Project Folder")
            if not folder:
                return
            name = self.project.name
            path = os.path.join(folder, f"{name}.kfp_basic")
            self.project.project_path = path
        
        try:
            self.project.save()
            self.status_label.setText(f"Saved: {self.project.name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save project: {e}")

    def auto_save(self):
        if self.project.project_path and self.is_playing:
            self.save_project()

    def add_sources(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add Sources", "",
            "Media Files (*.mp4 *.avi *.mov *.mkv *.png *.jpg *.jpeg *.tga);;All Files (*)"
        )
        
        for file_path in files:
            self._add_source_file(file_path)
        
        self._update_ui()

    def _add_source_file(self, path: str):
        if not os.path.exists(path):
            return

        ext = os.path.splitext(path)[1].lower()
        
        if ext in ['.mp4', '.avi', '.mov', '.mkv', '.webm']:
            source = MediaSource(path=path, type="video")
            self.engine.load_video(path)
            source.trim_out = self.engine.frame_count - 1
        else:
            source = MediaSource(path=path, type="sequence")
            if self.engine.load_sequence(path):
                source.trim_out = self.engine.frame_count - 1
                source.start_index = 1
                source.end_index = self.engine.frame_count
                source.padding = 4

        if self.project.sources:
            source.in_frame = self.project.sources[-1].out_frame + 1
        else:
            source.in_frame = 0
        
        source.trim_in = source.in_frame
        source.trim_out = source.out_frame

        self.project.add_source(source)

    def _load_sources(self):
        for source in self.project.sources:
            if source.type == "video":
                if os.path.exists(source.path):
                    self.engine.load_video(source.path)
                    break
            elif source.type == "sequence":
                if os.path.exists(os.path.dirname(source.path)):
                    self.engine.load_sequence(source.path, source.start_index, source.padding)
                    break

    def _update_ui(self):
        self.source_list.clear()
        for src in self.project.sources:
            item = self.source_list.count()
            self.source_list.addItem(f"{src.name} ({src.frame_count} frames)")
        
        self.timeline.set_project(self.project)
        self.bookmarks_panel.set_bookmarks(self.project.bookmarks)
        
        if self.project.total_frames > 0:
            self.current_frame = 0
            self._load_frame(0)

    def _load_frame(self, frame: int):
        source, local_frame = self.project.get_source_at_frame(frame)
        
        if source and source.type == "video":
            self.engine.load_video(source.path)
        elif source and source.type == "sequence":
            self.engine.load_sequence(source.path, source.start_index, source.padding)
        
        if source:
            adjusted_frame = local_frame - source.trim_in + source.in_frame
            frame_data = self.engine.get_frame(adjusted_frame)
            if frame_data is not None:
                self.viewer.set_frame(frame_data)
        
        metadata = self.project.get_frame_metadata(frame)
        self.viewer.set_pan(metadata.pan_x, metadata.pan_y)
        self.viewer.set_zoom(metadata.zoom)
        
        self.bookmarks_panel.set_frame_info(frame, metadata)
        
        self.timeline.set_frame(frame)
        self.controls.set_frame_label(frame, self.project.total_frames)

    def toggle_play(self):
        self.is_playing = not self.is_playing
        self.controls.set_playing(self.is_playing)
        
        if self.is_playing:
            fps = self.project.fps * self.playback_speed
            interval = int(1000 / fps)
            self.play_timer.start(interval)
        else:
            self.play_timer.stop()

    def playback_tick(self):
        if not self.hold_frame:
            self.current_frame += 1
            if self.current_frame >= self.project.total_frames:
                self.current_frame = 0
            self._load_frame(self.current_frame)

    def step_back(self):
        if self.current_frame > 0:
            self.current_frame -= 1
            self._load_frame(self.current_frame)

    def step_forward(self):
        if self.current_frame < self.project.total_frames - 1:
            self.current_frame += 1
            self._load_frame(self.current_frame)

    def jump_to_start(self):
        self.current_frame = 0
        self._load_frame(self.current_frame)

    def jump_to_end(self):
        self.current_frame = max(0, self.project.total_frames - 1)
        self._load_frame(self.current_frame)

    def seek_to_frame(self, frame: int):
        self.current_frame = frame
        self._load_frame(frame)

    def set_hold(self, hold: bool):
        self.hold_frame = hold

    def set_speed(self, speed_str: str):
        speed_map = {"0.25x": 0.25, "0.5x": 0.5, "1x": 1.0, "2x": 2.0}
        self.playback_speed = speed_map.get(speed_str, 1.0)
        
        if self.is_playing:
            fps = self.project.fps * self.playback_speed
            interval = int(1000 / fps)
            self.play_timer.start(interval)

    def set_fps(self, fps_str: str):
        fps = int(fps_str)
        self.project.fps = fps
        
        if self.is_playing:
            interval = int(1000 / (fps * self.playback_speed))
            self.play_timer.start(interval)

    def add_bookmark(self, btype: str):
        if btype == "single":
            label, ok = QInputDialog.getText(self, "Add Bookmark", "Label:")
            if ok and label:
                bm = Bookmark(
                    frame=self.current_frame,
                    type="single",
                    label=label,
                    color="#4EC9B0"
                )
                self.project.add_bookmark(bm)
                self.bookmarks_panel.set_bookmarks(self.project.bookmarks)
                self.timeline.update()
        else:
            start, ok1 = QInputDialog.getInt(self, "Add Range", "Start frame:", self.current_frame)
            if not ok1:
                return
            end, ok2 = QInputDialog.getInt(self, "Add Range", "End frame:", self.current_frame)
            if not ok2:
                return
            label, ok3 = QInputDialog.getText(self, "Add Range", "Label:")
            if ok3:
                bm = Bookmark(
                    start_frame=start,
                    end_frame=end,
                    type="range",
                    label=label,
                    color="#CE9178"
                )
                self.project.add_bookmark(bm)
                self.bookmarks_panel.set_bookmarks(self.project.bookmarks)
                self.timeline.update()

    def on_bookmark_activated(self, item):
        bm_id = item.data(Qt.ItemDataRole.UserRole)
        for bm in self.project.bookmarks:
            if bm.id == bm_id:
                if bm.type == "single":
                    self.seek_to_frame(bm.frame)
                else:
                    self.seek_to_frame(bm.start_frame or 0)
                break

    def on_note_changed(self, text: str):
        metadata = self.project.get_frame_metadata(self.current_frame)
        metadata.note = text
        self.project.set_frame_metadata(self.current_frame, metadata)

    def on_hold_changed(self, checked: bool):
        metadata = self.project.get_frame_metadata(self.current_frame)
        metadata.hold = checked
        self.project.set_frame_metadata(self.current_frame, metadata)
        self.hold_frame = checked
        self.controls.set_hold(checked)

    def on_viewer_zoom_changed(self, zoom: float):
        metadata = self.project.get_frame_metadata(self.current_frame)
        metadata.zoom = zoom

    def on_viewer_pan_changed(self, x: float, y: float):
        metadata = self.project.get_frame_metadata(self.current_frame)
        metadata.pan_x = x
        metadata.pan_y = y

    def on_source_selected(self, item):
        index = self.source_list.row(item)
        if 0 <= index < len(self.project.sources):
            source = self.project.sources[index]
            self.seek_to_frame(source.in_frame)

    def reset_view(self):
        self.viewer.pan_x = 0.0
        self.viewer.pan_y = 0.0
        self.viewer.zoom = 1.0
        self.viewer.update_display()

    def zoom_in(self):
        self.viewer.zoom = min(4.0, self.viewer.zoom * 1.2)
        self.viewer.update_display()

    def zoom_out(self):
        self.viewer.zoom = max(0.25, self.viewer.zoom / 1.2)
        self.viewer.update_display()

    def export_bookmarks(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Bookmarks", "",
            "CSV Files (*.csv)"
        )
        if path:
            try:
                with open(path, 'w') as f:
                    f.write("Type,Frame,Start,End,Label,Color\n")
                    for bm in self.project.bookmarks:
                        if bm.type == "single":
                            f.write(f"single,{bm.frame},,,{bm.label},{bm.color}\n")
                        else:
                            f.write(f"range,,{bm.start_frame},{bm.end_frame},{bm.label},{bm.color}\n")
                QMessageBox.information(self, "Export", "Bookmarks exported successfully!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export: {e}")

    def export_current_frame(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Frame", "",
            "PNG Files (*.png)"
        )
        if path:
            try:
                import cv2
                frame = self.engine.get_frame(self.current_frame)
                if frame is not None:
                    cv2.imwrite(path, frame)
                    QMessageBox.information(self, "Export", "Frame exported successfully!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export: {e}")

    def keyPressEvent(self, event):
        key = event.key()
        
        if key == Qt.Key.Key_Space:
            self.toggle_play()
        elif key == Qt.Key.Key_Left:
            self.step_back()
        elif key == Qt.Key.Key_Right:
            self.step_forward()
        elif key == Qt.Key.Key_Home:
            self.jump_to_start()
        elif key == Qt.Key.Key_End:
            self.jump_to_end()
        elif key == Qt.Key.Key_B:
            self.add_bookmark("single")
        elif key == Qt.Key.Key_R:
            self.add_bookmark("range")
        elif key == Qt.Key.Key_N:
            self.bookmarks_panel.note_edit.setFocus()
        elif key == Qt.Key.Key_Delete:
            pass
        elif key == Qt.Key.Key_0:
            self.reset_view()
        elif key == Qt.Key.Key_Plus or key == Qt.Key.Key_Equal:
            self.zoom_in()
        elif key == Qt.Key.Key_Minus:
            self.zoom_out()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent):
        if self.project.project_path:
            self.save_project()
        event.accept()
