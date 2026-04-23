import sys
from typing import Optional, List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QFrame, QSplitter, QListWidget, QListWidgetItem,
    QLineEdit, QComboBox, QToolBar, QMenuBar, QMenu, QStatusBar,
    QDialog, QDialogButtonBox, QFileDialog, QMessageBox, QInputDialog,
    QColorDialog, QScrollArea, QGroupBox, QCheckBox, QApplication
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QPointF
from PyQt6.QtGui import QImage, QPixmap, QKeyEvent, QWheelEvent, QColor, QPainter, QPen, QBrush
from PyQt6.QtCore import QRectF
import numpy as np

from .models import Project, MediaSource, Bookmark, FrameMetadata
from .engine import PlayerEngine


COLOR_BG = "#1E1E1E"
COLOR_PANEL = "#252526"
COLOR_ACCENT = "#007ACC"
COLOR_ACCENT_GREEN = "#4EC9B0"
COLOR_ACCENT_ORANGE = "#CE9178"
COLOR_TEXT = "#D4D4D4"
COLOR_TEXT_SEC = "#808080"
COLOR_TIMELINE = "#2D2D30"
COLOR_PLAYHEAD = "#FF6B6B"


class ViewerWidget(QFrame):
    frame_changed = pyqtSignal(int)
    zoom_changed = pyqtSignal(float)
    pan_changed = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {COLOR_BG};")
        self.setMinimumSize(320, 180)
        
        self.current_frame: Optional[np.ndarray] = None
        self.frame_display: QLabel = QLabel(self)
        self.frame_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame_display.setScaledContents(False)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.frame_display)
        
        self.pan_x: float = 0.0
        self.pan_y: float = 0.0
        self.zoom: float = 1.0
        self.is_panning: bool = False
        self.last_mouse_pos = None
        
        self.setMouseTracking(True)
        self.frame_display.setMouseTracking(True)

    def set_frame(self, frame: np.ndarray):
        self.current_frame = frame
        self.update_display()

    def update_display(self):
        if self.current_frame is None:
            self.frame_display.setPixmap(QPixmap())
            return

        h, w = self.current_frame.shape[:2]
        bytes_per_line = w * 3
        q_image = QImage(
            self.current_frame.data, w, h, bytes_per_line, 
            QImage.Format.Format_BGR888
        )
        
        pixmap = QPixmap.fromImage(q_image)
        
        scaled_w = int(w * self.zoom)
        scaled_h = int(h * self.zoom)
        
        if scaled_w > 0 and scaled_h > 0:
            scaled_pixmap = pixmap.scaled(
                scaled_w, scaled_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            canvas_w = self.frame_display.width()
            canvas_h = self.frame_display.height()
            
            offset_x = int((canvas_w - scaled_pixmap.width()) / 2 + self.pan_x)
            offset_y = int((canvas_h - scaled_pixmap.height()) / 2 + self.pan_y)
            
            result = QPixmap(canvas_w, canvas_h)
            result.fill(QColor(COLOR_BG))
            
            painter = QPainter(result)
            painter.drawPixmap(offset_x, offset_y, scaled_pixmap)
            painter.end()
            
            self.frame_display.setPixmap(result)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_display()

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() == Qt.KeyboardModifier.NoModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom = min(4.0, self.zoom * 1.1)
            else:
                self.zoom = max(0.25, self.zoom / 1.1)
            self.zoom_changed.emit(self.zoom)
            self.update_display()
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and 
            event.modifiers() == Qt.KeyboardModifier.AltModifier
        ):
            self.is_panning = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_panning and self.last_mouse_pos:
            delta = event.pos() - self.last_mouse_pos
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self.last_mouse_pos = event.pos()
            self.pan_changed.emit(self.pan_x, self.pan_y)
            self.update_display()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.is_panning:
            self.is_panning = False
            self.last_mouse_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.zoom = 1.0
        self.zoom_changed.emit(self.zoom)
        self.pan_changed.emit(self.pan_x, self.pan_y)
        self.update_display()
        event.accept()

    def set_pan(self, x: float, y: float):
        self.pan_x = x
        self.pan_y = y
        self.update_display()

    def set_zoom(self, zoom: float):
        self.zoom = zoom
        self.update_display()


class TimelineWidget(QFrame):
    seek_requested = pyqtSignal(int)
    bookmark_selected = pyqtSignal(int)
    trim_changed = pyqtSignal(str, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setStyleSheet(f"background-color: {COLOR_TIMELINE};")
        
        self.total_frames: int = 0
        self.current_frame: int = 0
        self.project: Optional[Project] = None
        self.sources: List[MediaSource] = []
        
        self.bookmarks: List[Bookmark] = []
        
        self.is_dragging_playhead = False
        self.is_dragging_trim_in = False
        self.is_dragging_trim_out = False
        self.dragging_source_id: Optional[str] = None

    def set_project(self, project: Project):
        self.project = project
        self.sources = project.sources
        self.bookmarks = project.bookmarks
        self.total_frames = project.total_frames
        self.update()

    def set_frame(self, frame: int):
        self.current_frame = frame
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.project:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        if self.total_frames <= 0:
            return

        x_scale = w / self.total_frames
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#3C3C3C")))
        painter.drawRect(0, h//2 - 15, w, 30)
        
        current = 0
        colors = ["#4A5568", "#2D3748"]
        for i, src in enumerate(self.sources):
            src_w = src.frame_count * x_scale
            color = colors[i % len(colors)]
            painter.setBrush(QBrush(QColor(color)))
            painter.drawRect(int(current), h//2 - 12, int(src_w), 24)
            current += src_w
        
        for bm in self.bookmarks:
            if bm.type == "single":
                x = bm.frame * x_scale
                painter.setPen(QPen(QColor(bm.color), 2))
                painter.drawLine(int(x), 5, int(x), h - 5)
            else:
                if bm.start_frame is not None and bm.end_frame is not None:
                    x1 = bm.start_frame * x_scale
                    x2 = bm.end_frame * x_scale
                    painter.setBrush(QBrush(QColor(bm.color)))
                    painter.setOpacity(0.5)
                    painter.drawRect(int(x1), h//2 - 10, int(x2 - x1), 20)
                    painter.setOpacity(1.0)

        if self.total_frames > 0:
            playhead_x = self.current_frame * x_scale
            painter.setPen(QPen(QColor(COLOR_PLAYHEAD), 2))
            painter.drawLine(int(playhead_x), 0, int(playhead_x), h)
            
            painter.setBrush(QBrush(QColor(COLOR_PLAYHEAD)))
            triangle = [
                QPointF(playhead_x - 6, 0),
                QPointF(playhead_x + 6, 0),
                QPointF(playhead_x, 8)
            ]
            painter.drawPolygon(triangle)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos().x()
            frame = int(pos / self.width() * self.total_frames)
            frame = max(0, min(frame, self.total_frames - 1))
            self.seek_requested.emit(frame)
            self.is_dragging_playhead = True
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_dragging_playhead:
            pos = event.pos().x()
            frame = int(pos / self.width() * self.total_frames)
            frame = max(0, min(frame, self.total_frames - 1))
            self.seek_requested.emit(frame)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.is_dragging_playhead = False
        event.accept()


class SourceListWidget(QListWidget):
    source_selected = pyqtSignal(str)
    source_reordered = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLOR_PANEL};
                color: {COLOR_TEXT};
                border: none;
            }}
            QListWidget::item {{
                padding: 4px;
            }}
            QListWidget::item:selected {{
                background-color: {COLOR_ACCENT};
            }}
        """)
        self.setMaximumHeight(60)


class BookmarkListWidget(QListWidget):
    bookmark_activated = pyqtSignal(str)
    bookmark_deleted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLOR_PANEL};
                color: {COLOR_TEXT};
                border: none;
            }}
        """)


class PlaybackControls(QFrame):
    play_pause_clicked = pyqtSignal()
    step_back_clicked = pyqtSignal()
    step_forward_clicked = pyqtSignal()
    jump_start_clicked = pyqtSignal()
    jump_end_clicked = pyqtSignal()
    hold_toggled = pyqtSignal(bool)
    speed_changed = pyqtSignal(float)
    fps_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {COLOR_PANEL};")
        self.setMaximumHeight(50)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        self.btn_jump_start = QPushButton("|◀")
        self.btn_step_back = QPushButton("◀")
        self.btn_play = QPushButton("▶")
        self.btn_step_forward = QPushButton("▶")
        self.btn_jump_end = QPushButton("▶|")
        
        self.btn_jump_start.setFixedSize(40, 28)
        self.btn_step_back.setFixedSize(30, 28)
        self.btn_play.setFixedSize(40, 28)
        self.btn_step_forward.setFixedSize(30, 28)
        self.btn_jump_end.setFixedSize(40, 28)

        self.btn_hold = QPushButton("HOLD")
        self.btn_hold.setCheckable(True)
        self.btn_hold.setFixedWidth(50)

        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.25x", "0.5x", "1x", "2x"])
        self.speed_combo.setCurrentText("1x")
        self.speed_combo.setFixedWidth(60)

        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["12", "24", "25", "30", "60"])
        self.fps_combo.setCurrentText("24")
        self.fps_combo.setFixedWidth(60)

        self.frame_label = QLabel("Frame: 0 / 0")
        
        for btn in [self.btn_jump_start, self.btn_step_back, self.btn_play, 
                    self.btn_step_forward, self.btn_jump_end, self.btn_hold]:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #3C3C3C;
                    color: {COLOR_TEXT};
                    border: none;
                    border-radius: 3px;
                }}
                QPushButton:hover {{ background-color: #4A4A4A; }}
                QPushButton:pressed {{ background-color: #2D2D2D; }}
                QPushButton:checked {{ background-color: {COLOR_ACCENT}; }}
            """)

        self.btn_jump_start.clicked.connect(self.jump_start_clicked.emit)
        self.btn_step_back.clicked.connect(self.step_back_clicked.emit)
        self.btn_play.clicked.connect(self.play_pause_clicked.emit)
        self.btn_step_forward.clicked.connect(self.step_forward_clicked.emit)
        self.btn_jump_end.clicked.connect(self.jump_end_clicked.emit)
        self.btn_hold.toggled.connect(self.hold_toggled.emit)

        layout.addWidget(self.btn_jump_start)
        layout.addWidget(self.btn_step_back)
        layout.addWidget(self.btn_play)
        layout.addWidget(self.btn_step_forward)
        layout.addWidget(self.btn_jump_end)
        layout.addWidget(self.btn_hold)
        layout.addWidget(self.speed_combo)
        layout.addWidget(QLabel("FPS:"))
        layout.addWidget(self.fps_combo)
        layout.addStretch()
        layout.addWidget(self.frame_label)

    def set_playing(self, playing: bool):
        self.btn_play.setText("⏸" if playing else "▶")

    def set_frame_label(self, current: int, total: int):
        self.frame_label.setText(f"Frame: {current} / {total}")

    def set_hold(self, hold: bool):
        self.btn_hold.setChecked(hold)


class BookmarksPanel(QFrame):
    add_bookmark = pyqtSignal(str, str)
    add_range = pyqtSignal(int, int, str)
    delete_bookmark = pyqtSignal(str)
    edit_bookmark = pyqtSignal(str, str)
    frame_note_changed = pyqtSignal(int, str)
    hold_changed = pyqtSignal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(280)
        self.setStyleSheet(f"background-color: {COLOR_PANEL};")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        title = QLabel("Bookmarks & Notes")
        title.setStyleSheet(f"color: {COLOR_TEXT}; font-weight: bold;")

        btn_layout = QHBoxLayout()
        self.btn_add_bm = QPushButton("+ Bookmark")
        self.btn_add_range = QPushButton("+ Range")
        self.btn_export = QPushButton("Export")
        
        for btn in [self.btn_add_bm, self.btn_add_range, self.btn_export]:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #3C3C3C;
                    color: {COLOR_TEXT};
                    border: none;
                    padding: 4px;
                }}
                QPushButton:hover {{ background-color: #4A4A4A; }}
            """)
        
        btn_layout.addWidget(self.btn_add_bm)
        btn_layout.addWidget(self.btn_add_range)
        btn_layout.addWidget(self.btn_export)

        self.bookmark_list = BookmarkListWidget()

        self.note_group = QGroupBox("Frame Notes")
        note_layout = QVBoxLayout()
        
        self.note_label = QLabel("Frame: 0")
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Add note for this frame...")
        
        self.hold_check = QCheckBox("Hold Frame")
        self.hold_check.setStyleSheet(f"color: {COLOR_TEXT};")
        
        note_layout.addWidget(self.note_label)
        note_layout.addWidget(self.note_edit)
        note_layout.addWidget(self.hold_check)
        
        self.note_group.setLayout(note_layout)
        self.note_group.setStyleSheet(f"""
            QGroupBox {{
                color: {COLOR_TEXT};
                border: 1px solid #3C3C3C;
                margin-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
            }}
            QLineEdit {{
                background-color: #3C3C3C;
                color: {COLOR_TEXT};
                border: none;
                padding: 4px;
            }}
        """)

        layout.addWidget(title)
        layout.addLayout(btn_layout)
        layout.addWidget(self.bookmark_list, 1)
        layout.addWidget(self.note_group)

    def set_bookmarks(self, bookmarks: List[Bookmark]):
        self.bookmark_list.clear()
        for bm in bookmarks:
            if bm.type == "single":
                text = f"● Frame {bm.frame}: {bm.label}"
            else:
                text = f"■ Range {bm.start_frame}-{bm.end_frame}: {bm.label}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, bm.id)
            if bm.color:
                item.setForeground(QColor(bm.color))
            self.bookmark_list.addItem(item)

    def set_frame_info(self, frame: int, metadata: FrameMetadata):
        self.note_label.setText(f"Frame: {frame}")
        self.note_edit.setText(metadata.note)
        self.hold_check.setChecked(metadata.hold)
