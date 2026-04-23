from PyQt6.QtWidgets import QWidget, QScrollArea, QHBoxLayout, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QRect, QSize, pyqtSignal, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QMouseEvent, QFont


class TimelineWidget(QWidget):
    frame_selected = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMaximumHeight(200)
        self.setStyleSheet("background-color: #2a2a2a;")
        
        self.total_frames = 0
        self.current_frame = 0
        self.playhead = 0
        self.thumbnails = {}
        self.bookmarks = set()
        
        self.thumbnail_size = 64
        self.frame_width = 8
        
        self.in_point = None
        self.out_point = None
        
        self.dragging_playhead = False
        
    def set_total_frames(self, frames):
        self.total_frames = frames
        self.update()
    
    def set_playhead(self, frame):
        self.playhead = frame
        self.update()
    
    def set_thumbnail(self, frame, pixmap):
        self.thumbnails[frame] = pixmap
        self.update()
    
    def add_bookmark(self, frame):
        self.bookmarks.add(frame)
        self.update()
    
    def remove_bookmark(self, frame):
        if frame in self.bookmarks:
            self.bookmarks.remove(frame)
            self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        total_width = max(self.total_frames * self.frame_width + 100, self.width())
        self.setMinimumWidth(total_width)
        
        painter.fillRect(0, 0, total_width, self.height(), QColor(42, 42, 42))
        
        frame_offset = 50
        
        sorted_frames = sorted(self.thumbnails.keys())
        for i, frame in enumerate(sorted_frames):
            x = frame_offset + frame * self.frame_width
            next_frame = sorted_frames[i+1] if i + 1 < len(sorted_frames) else self.total_frames
            # Calculate width to the next thumbnail, but cap it so the last thumbnail doesn't stretch infinitely if total_frames is very large
            width = min((next_frame - frame) * self.frame_width, self.thumbnail_size * 5)
            
            thumb = self.thumbnails[frame]
            
            painter.save()
            target_h = max(10, self.height() - 25)
            clip_rect = QRect(int(x), 0, int(width), target_h)
            painter.setClipRect(clip_rect)
            
            thumb_scaled = thumb.scaled(
                int(width), target_h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            
            tx = x + (width - thumb_scaled.width()) // 2
            ty = max(0, (target_h - thumb_scaled.height()) // 2)
            painter.drawPixmap(int(tx), int(ty), thumb_scaled)
            painter.restore()

        for frame in range(self.total_frames):
            x = frame_offset + frame * self.frame_width
            
            if frame % 10 == 0:
                painter.setPen(QColor(100, 100, 100))
                painter.drawLine(x, self.height() - 20, x, self.height() - 10)
                
                painter.setPen(QColor(200, 200, 200))
                font = painter.font()
                font.setPointSize(8)
                painter.setFont(font)
                painter.drawText(x - 10, self.height() - 5, str(frame + 1))
        
        if self.in_point is not None:
            ix = frame_offset + self.in_point * self.frame_width
            painter.setPen(QColor(255, 255, 0))
            painter.setBrush(QBrush(QColor(255, 255, 0, 100)))
            painter.drawRect(ix, 0, 10, self.height())
        
        if self.out_point is not None:
            ox = frame_offset + self.out_point * self.frame_width
            painter.setPen(QColor(255, 255, 0))
            painter.setBrush(QBrush(QColor(255, 255, 0, 100)))
            painter.drawRect(ox - 10, 0, 10, self.height())
        
        for bookmark_frame in self.bookmarks:
            bx = frame_offset + bookmark_frame * self.frame_width
            painter.setPen(QColor(255, 107, 53))
            painter.setBrush(QBrush(QColor(255, 107, 53)))
            painter.drawEllipse(bx - 4, 5, 8, 8)
        
        playhead_x = frame_offset + self.playhead * self.frame_width
        painter.setPen(QColor(0, 255, 136))
        painter.setBrush(QBrush(QColor(0, 255, 136)))
        painter.drawRect(playhead_x - 1, 0, 3, self.height())
        
        painter.setPen(QColor(0, 255, 136))
        painter.setBrush(QBrush(QColor(0, 255, 136)))
        triangle = [
            QPoint(playhead_x - 6, 0),
            QPoint(playhead_x + 6, 0),
            QPoint(playhead_x, 10)
        ]
        from PyQt6.QtGui import QPolygon
        polygon = QPolygon(triangle)
        painter.drawPolygon(polygon)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            frame_offset = 50
            frame = int((event.pos().x() - frame_offset) / self.frame_width)
            
            if 0 <= frame < self.total_frames:
                self.dragging_playhead = True
                self.playhead = frame
                self.frame_selected.emit(frame)
                self.update()
    
    def mouseMoveEvent(self, event):
        if self.dragging_playhead:
            frame_offset = 50
            frame = int((event.pos().x() - frame_offset) / self.frame_width)
            
            frame = max(0, min(frame, self.total_frames - 1))
            self.playhead = frame
            self.frame_selected.emit(frame)
            self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging_playhead = False
    
    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.thumbnail_size = min(128, self.thumbnail_size + 8)
            else:
                self.thumbnail_size = max(32, self.thumbnail_size - 8)
            
            self.frame_width = max(4, self.thumbnail_size // 8)
            self.update()


class OverviewTimelineWidget(QWidget):
    """Thin global navigation bar representing the full video length."""
    frame_selected = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setMinimumWidth(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.total_frames = 0
        self.playhead = 0
        self.bookmarks = set()
        self.in_point = None
        self.out_point = None
        self._dragging = False
    
    def set_total_frames(self, frames):
        self.total_frames = frames
        self.update()
    
    def set_playhead(self, frame):
        self.playhead = frame
        self.update()
    
    def add_bookmark(self, frame):
        self.bookmarks.add(frame)
        self.update()
    
    def remove_bookmark(self, frame):
        self.bookmarks.discard(frame)
        self.update()
    
    def _frame_from_x(self, x):
        if self.total_frames <= 0:
            return 0
        margin = 4
        usable = self.width() - margin * 2
        frac = max(0.0, min(1.0, (x - margin) / usable))
        return int(frac * (self.total_frames - 1))
    
    def _x_from_frame(self, frame):
        if self.total_frames <= 1:
            return 4
        margin = 4
        usable = self.width() - margin * 2
        return margin + (frame / (self.total_frames - 1)) * usable
    
    def paintEvent(self, event):
        if self.total_frames <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w, h = self.width(), self.height()
        margin = 4
        bar_y = 6
        bar_h = h - 12
        usable = w - margin * 2
        
        # Background bar
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(50, 50, 55))
        painter.drawRoundedRect(margin, bar_y, usable, bar_h, 4, 4)
        
        # Progress / played portion
        px = self._x_from_frame(self.playhead)
        painter.setBrush(QColor(0, 168, 255, 50))
        painter.drawRoundedRect(margin, bar_y, int(px - margin), bar_h, 4, 4)
        
        # Bookmark markers
        for bm in self.bookmarks:
            bx = self._x_from_frame(bm)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 107, 53))
            painter.drawRoundedRect(int(bx) - 1, bar_y, 3, bar_h, 1, 1)
        
        # Playhead
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 255, 136))
        ph_x = int(self._x_from_frame(self.playhead))
        painter.drawRoundedRect(ph_x - 3, bar_y - 2, 6, bar_h + 4, 3, 3)
        
        painter.end()
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            frame = self._frame_from_x(event.pos().x())
            self.playhead = frame
            self.frame_selected.emit(frame)
            self.update()
    
    def mouseMoveEvent(self, event):
        if self._dragging:
            frame = self._frame_from_x(event.pos().x())
            frame = max(0, min(frame, self.total_frames - 1))
            self.playhead = frame
            self.frame_selected.emit(frame)
            self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
