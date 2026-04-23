from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap


class AnnotationLayer:
    def __init__(self, parent=None):
        self.parent = parent
        self.strokes = {}
        self.current_stroke = []
        self.is_drawing = False
        self.color = '#ff6b35'
        self.brush_size = 3
        self.visible = True
        
        self.tool = 'freehand'
    
    def start_stroke(self, point):
        self.is_drawing = True
        self.current_stroke = [point]
    
    def add_point(self, point):
        if self.is_drawing:
            self.current_stroke.append(point)
    
    def end_stroke(self, frame):
        if self.is_drawing and self.current_stroke:
            if frame not in self.strokes:
                self.strokes[frame] = []
            
            self.strokes[frame].append({
                'color': self.color,
                'size': self.brush_size,
                'points': list(self.current_stroke),
                'tool': self.tool
            })
        
        self.is_drawing = False
        self.current_stroke = []
    
    def get_strokes(self, frame=None):
        if frame is not None:
            return self.strokes.get(frame, [])
        return self.strokes
    
    def set_strokes(self, frame, strokes):
        self.strokes[frame] = strokes
    
    def clear_strokes(self, frame=None):
        if frame is not None:
            if frame in self.strokes:
                del self.strokes[frame]
        else:
            self.strokes = {}
    
    def set_color(self, color):
        self.color = color
    
    def set_brush_size(self, size):
        self.brush_size = size
    
    def set_tool(self, tool):
        self.tool = tool
    
    def set_visible(self, visible):
        self.visible = visible
    
    def is_visible(self):
        return self.visible
    
    def render(self, painter, rect):
        if not self.visible:
            return
        
        painter.save()
        
        painter.setPen(QPen(QColor(self.color), self.brush_size))
        
        if self.parent and self.parent.current_frame in self.strokes:
            for stroke in self.strokes[self.parent.current_frame]:
                color = stroke.get('color', self.color)
                size = stroke.get('size', self.brush_size)
                points = stroke.get('points', [])
                
                painter.setPen(QPen(QColor(color), size))
                
                if len(points) > 1:
                    for i in range(len(points) - 1):
                        painter.drawLine(points[i], points[i + 1])
                elif len(points) == 1:
                    painter.drawPoint(points[0])
        
        if self.is_drawing and self.current_stroke:
            painter.setPen(QPen(QColor(self.color), self.brush_size))
            
            if len(self.current_stroke) > 1:
                for i in range(len(self.current_stroke) - 1):
                    painter.drawLine(self.current_stroke[i], self.current_stroke[i + 1])
        
        painter.restore()
    
    def export_strokes_json(self):
        return self.strokes
    
    def import_strokes_json(self, data):
        self.strokes = data
