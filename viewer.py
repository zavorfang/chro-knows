import os
import re
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, QPointF, pyqtSignal, QRectF
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QBrush


class ViewerWidget(QWidget):
    frame_clicked = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setStyleSheet("background-color: #000000;")
        
        self.current_pixmap = None
        self.pan = QPointF(0, 0)
        self.zoom = 1.0
        self.is_panning = False
        self.last_mouse_pos = None
        
    def set_image(self, pixmap):
        self.current_pixmap = pixmap
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        
        if self.current_pixmap is not None:
            scaled = self.current_pixmap.scaled(
                self.size(), 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            
            self._image_offset = (x, y, scaled.width(), scaled.height())
            
            cx = x + scaled.width() // 2 + int(self.pan.x())
            cy = y + scaled.height() // 2 + int(self.pan.y())
            painter.translate(cx, cy)
            painter.scale(self.zoom, self.zoom)
            painter.translate(-scaled.width() // 2, -scaled.height() // 2)
            
            painter.drawPixmap(0, 0, scaled)
            
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_panning = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.is_panning = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
    
    def mouseMoveEvent(self, event):
        if self.is_panning and self.last_mouse_pos:
            delta = event.pos() - self.last_mouse_pos
            self.pan += QPointF(delta.x() / self.zoom, delta.y() / self.zoom)
            self.last_mouse_pos = event.pos()
            self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self.is_panning = False
            self.last_mouse_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def _get_image_coords(self, pos):
        if hasattr(self, '_image_offset'):
            x, y, w, h = self._image_offset
            img_x = (pos.x() - x - w // 2) / self.zoom + w // 2
            img_y = (pos.y() - y - h // 2) / self.zoom + h // 2
            return QPointF(img_x, img_y)
        return QPointF(pos.x(), pos.y())
    
    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
    
    def zoom_in(self):
        self.zoom = min(4.0, self.zoom * 1.2)
        self.update()
    
    def zoom_out(self):
        self.zoom = max(0.25, self.zoom / 1.2)
        self.update()
    
    def fit_to_window(self):
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.update()
    
    def reset_view(self):
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.update()


def detect_sequence(folder):
    extensions = ['.exr', '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.dpx', '.tga', '.bmp']
    
    files_by_name = {}
    
    for root, dirs, files in os.walk(folder):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext in extensions:
                filepath = os.path.join(root, filename)
                
                match = re.match(r'^(.+?)[\._](\d+)\.[^.]+$', filename)
                if match:
                    base_name = match.group(1)
                    frame_num = int(match.group(2))
                    
                    if base_name not in files_by_name:
                        files_by_name[base_name] = []
                    
                    files_by_name[base_name].append((frame_num, filepath))
    
    sequences = []
    for base_name, frames in files_by_name.items():
        if len(frames) > 1:
            frames.sort(key=lambda x: x[0])
            sequences.append({
                'name': base_name,
                'files': [f[1] for f in frames],
                'start': frames[0][0],
                'end': frames[-1][0],
                'folder': folder
            })
    
    return sorted(sequences, key=lambda x: len(x['files']), reverse=True)


def load_image_sequence(folder, pattern, start_frame, end_frame):
    files = []
    
    for root, dirs, filenames in os.walk(folder):
        for filename in filenames:
            match = re.match(pattern.replace('####', r'(\d+)'), filename)
            if match:
                frame_num = int(match.group(1))
                if start_frame <= frame_num <= end_frame:
                    files.append((frame_num, os.path.join(root, filename)))
    
    files.sort(key=lambda x: x[0])
    return [f[1] for f in files]
