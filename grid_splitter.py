"""Smart Grid Splitter – overlay a colorised grid image on a video chunk,
navigate only the frames used to build the grid, adjust alignment, and
export each cell cropped to the original video resolution.

Position logic
--------------
For an NxN grid built from a chunk, each cell corresponds to one selected
frame.  The grid image is exactly N× the video width and N× the video
height.  To align cell *i* (0-indexed, row-major) with the viewport the
grid must be offset by::

    col = i % N
    row = i // N
    offset_x = -col * frame_width
    offset_y = -row * frame_height

A manual nudge (drag) is stored once and re-applied on every frame so the
user only has to correct misalignment once.
"""

import json
import math
import os

import cv2
import numpy as np

from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)


# ---------------------------------------------------------------------------
# Helper – load a video frame as QPixmap via OpenCV
# ---------------------------------------------------------------------------

def _load_video_frame(video_path: str, frame_num: int) -> QPixmap | None:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def _video_dimensions(video_path: str):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0, 0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return w, h


# ---------------------------------------------------------------------------
# Viewport widget – composites video frame + grid overlay
# ---------------------------------------------------------------------------

class _SplitterViewport(QWidget):
    """Draws the video frame with the grid image overlaid.  Supports drag to
    nudge the grid position."""

    position_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #0a0a14;")
        self.setMouseTracking(True)

        self._frame_pixmap: QPixmap | None = None
        self._grid_pixmap: QPixmap | None = None

        # Grid transform state
        self._grid_base_offset = QPointF(0, 0)   # algorithmic offset
        self._grid_nudge = QPointF(0, 0)          # user drag correction
        self._grid_opacity = 0.5
        self._grid_scale = 1.0

        # Drag state
        self._dragging = False
        self._drag_start = QPointF()
        self._nudge_at_drag_start = QPointF()

        # Display-fitting helpers (set during paint)
        self._display_scale = 1.0
        self._display_offset = QPointF(0, 0)

    # -- public API ----------------------------------------------------------

    def set_frame(self, pixmap: QPixmap | None):
        self._frame_pixmap = pixmap
        self.update()

    def set_grid(self, pixmap: QPixmap | None):
        self._grid_pixmap = pixmap
        self.update()

    def set_base_offset(self, x: float, y: float):
        self._grid_base_offset = QPointF(x, y)
        self.update()

    def set_nudge(self, nudge: QPointF):
        self._grid_nudge = QPointF(nudge)
        self.update()

    def nudge(self) -> QPointF:
        return QPointF(self._grid_nudge)

    def set_opacity(self, value: float):
        self._grid_opacity = max(0.0, min(1.0, value))
        self.update()

    def set_scale(self, value: float):
        self._grid_scale = max(0.01, value)
        self.update()

    # -- painting ------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(10, 10, 20))

        if self._frame_pixmap is None:
            painter.setPen(QColor(100, 100, 100))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No frame loaded")
            painter.end()
            return

        fw = self._frame_pixmap.width()
        fh = self._frame_pixmap.height()
        vw = self.width()
        vh = self.height()

        # Fit frame into viewport
        scale = min(vw / fw, vh / fh) if fw and fh else 1.0
        self._display_scale = scale
        sw = int(fw * scale)
        sh = int(fh * scale)
        ox = (vw - sw) / 2.0
        oy = (vh - sh) / 2.0
        self._display_offset = QPointF(ox, oy)

        # Draw video frame
        painter.drawPixmap(QRectF(ox, oy, sw, sh), self._frame_pixmap, QRectF(0, 0, fw, fh))

        # Draw grid overlay
        if self._grid_pixmap is not None:
            painter.setOpacity(self._grid_opacity)
            total_offset = self._grid_base_offset + self._grid_nudge
            gx = ox + total_offset.x() * scale
            gy = oy + total_offset.y() * scale
            gw = self._grid_pixmap.width() * scale * self._grid_scale
            gh = self._grid_pixmap.height() * scale * self._grid_scale
            painter.drawPixmap(
                QRectF(gx, gy, gw, gh),
                self._grid_pixmap,
                QRectF(0, 0, self._grid_pixmap.width(), self._grid_pixmap.height()),
            )
            painter.setOpacity(1.0)

            # Draw thin cell-boundary lines for reference
            grid_dim = round(self._grid_pixmap.width() / fw) if fw else 1
            if grid_dim < 1:
                grid_dim = 1
            pen = QPen(QColor(255, 255, 0, 80), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            cell_w = gw / grid_dim
            cell_h = gh / grid_dim
            for i in range(1, grid_dim):
                painter.drawLine(QPointF(gx + i * cell_w, gy), QPointF(gx + i * cell_w, gy + gh))
                painter.drawLine(QPointF(gx, gy + i * cell_h), QPointF(gx + i * cell_w * 0 + gw, gy + i * cell_h))

        painter.end()

    # -- mouse interaction ---------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.position()
            self._nudge_at_drag_start = QPointF(self._grid_nudge)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.position() - self._drag_start
            scale = self._display_scale if self._display_scale else 1.0
            self._grid_nudge = QPointF(
                self._nudge_at_drag_start.x() + delta.x() / scale,
                self._nudge_at_drag_start.y() + delta.y() / scale,
            )
            self.update()
            self.position_changed.emit()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))


# ---------------------------------------------------------------------------
# Initial setup dialog – pick files and chunk
# ---------------------------------------------------------------------------

class GridSplitterSetupDialog(QDialog):
    """First dialog: user picks the video chunk, JSON, grid image, and chunk index."""

    def __init__(self, parent=None, default_folder=""):
        super().__init__(parent)
        self.setWindowTitle("Smart Grid Splitter – Setup")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QFormLayout(self)

        # Video file
        self._video_path = ""
        self.video_edit = QLabel("(none)")
        self.video_edit.setStyleSheet("color: #aaa;")
        video_btn = QPushButton("Browse…")
        video_btn.clicked.connect(self._browse_video)
        row = QHBoxLayout()
        row.addWidget(self.video_edit, stretch=1)
        row.addWidget(video_btn)
        layout.addRow("Video Chunk:", row)

        # JSON file
        self._json_path = ""
        self.json_edit = QLabel("(none)")
        self.json_edit.setStyleSheet("color: #aaa;")
        json_btn = QPushButton("Browse…")
        json_btn.clicked.connect(self._browse_json)
        row2 = QHBoxLayout()
        row2.addWidget(self.json_edit, stretch=1)
        row2.addWidget(json_btn)
        layout.addRow("JSON Metadata:", row2)

        # Grid image
        self._grid_path = ""
        self.grid_edit = QLabel("(none)")
        self.grid_edit.setStyleSheet("color: #aaa;")
        grid_btn = QPushButton("Browse…")
        grid_btn.clicked.connect(self._browse_grid)
        row3 = QHBoxLayout()
        row3.addWidget(self.grid_edit, stretch=1)
        row3.addWidget(grid_btn)
        layout.addRow("Grid Image:", row3)

        # Chunk selector (populated after JSON is loaded)
        self.chunk_combo = QComboBox()
        self.chunk_combo.setEnabled(False)
        layout.addRow("Select Chunk:", self.chunk_combo)

        # Output folder
        self._output_folder = default_folder
        self.output_edit = QLabel(default_folder or "(same as grid image)")
        self.output_edit.setStyleSheet("color: #aaa;")
        output_btn = QPushButton("Browse…")
        output_btn.clicked.connect(self._browse_output)
        row4 = QHBoxLayout()
        row4.addWidget(self.output_edit, stretch=1)
        row4.addWidget(output_btn)
        layout.addRow("Output Folder:", row4)

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate_and_accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

        self._json_data = None

    # -- browsing helpers ----------------------------------------------------

    def _browse_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video Chunk", "", "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)"
        )
        if path:
            self._video_path = path
            self.video_edit.setText(os.path.basename(path))
            self.video_edit.setToolTip(path)

    def _browse_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select JSON Metadata", "", "JSON Files (*.json);;All Files (*)"
        )
        if path:
            self._json_path = path
            self.json_edit.setText(os.path.basename(path))
            self.json_edit.setToolTip(path)
            self._load_json(path)

    def _browse_grid(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Grid Image", "", "Images (*.jpg *.jpeg *.png *.bmp);;All Files (*)"
        )
        if path:
            self._grid_path = path
            self.grid_edit.setText(os.path.basename(path))
            self.grid_edit.setToolTip(path)
            if not self._output_folder:
                self._output_folder = os.path.dirname(path)
                self.output_edit.setText(self._output_folder)

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self._output_folder = folder
            self.output_edit.setText(folder)

    def _load_json(self, path):
        try:
            with open(path, "r") as f:
                self._json_data = json.load(f)
        except Exception as exc:
            QMessageBox.warning(self, "JSON Error", f"Could not load JSON:\n{exc}")
            return

        self.chunk_combo.clear()
        self.chunk_combo.setEnabled(True)
        chunks = self._json_data.get("chunks", [])
        if chunks:
            for ch in chunks:
                idx = ch.get("chunk_index", 0)
                s = ch.get("video_start_frame_abs", "?")
                e = ch.get("video_end_frame_abs", "?")
                self.chunk_combo.addItem(f"Chunk {idx + 1}  (frames {s}–{e})", idx)
        else:
            # Try the "chunk N" keys for frame lists
            for key in sorted(self._json_data.keys()):
                if key.lower().startswith("chunk "):
                    self.chunk_combo.addItem(key, key)

    def _validate_and_accept(self):
        if not self._video_path or not os.path.isfile(self._video_path):
            QMessageBox.warning(self, "Missing", "Please select a valid video chunk file.")
            return
        if not self._json_path or not os.path.isfile(self._json_path):
            QMessageBox.warning(self, "Missing", "Please select a valid JSON metadata file.")
            return
        if not self._grid_path or not os.path.isfile(self._grid_path):
            QMessageBox.warning(self, "Missing", "Please select a valid grid image file.")
            return
        if self.chunk_combo.count() == 0:
            QMessageBox.warning(self, "Missing", "No chunks found in JSON metadata.")
            return
        if not self._output_folder:
            self._output_folder = os.path.dirname(self._grid_path)
        self.accept()

    # -- result accessors ----------------------------------------------------

    def result_data(self):
        chunk_idx = self.chunk_combo.currentData()
        return {
            "video_path": self._video_path,
            "json_path": self._json_path,
            "json_data": self._json_data,
            "grid_path": self._grid_path,
            "chunk_index": chunk_idx,
            "output_folder": self._output_folder,
        }


# ---------------------------------------------------------------------------
# Main splitter dialog
# ---------------------------------------------------------------------------

class SmartGridSplitterDialog(QDialog):
    """The full splitter workspace: viewport + controls + export."""

    def __init__(self, parent, setup_data: dict):
        super().__init__(parent)
        self.setWindowTitle("Smart Grid Splitter")
        self.setMinimumSize(900, 650)

        self._video_path = setup_data["video_path"]
        self._grid_path = setup_data["grid_path"]
        self._json_data = setup_data["json_data"]
        self._chunk_index = setup_data["chunk_index"]
        self._output_folder = setup_data["output_folder"]

        # Resolve chunk metadata
        self._grid_dim = self._json_data.get("grid_dim", 2)
        self._frame_w, self._frame_h = _video_dimensions(self._video_path)

        # Calculate offset in the grid if multiple chunks share a grid
        chunks = self._json_data.get("chunks", [])
        current_global_index = 0
        for i in range(min(self._chunk_index, len(chunks))):
            current_global_index += len(chunks[i].get("selected_frames_abs", []))

        grid_cap = self._grid_dim * self._grid_dim
        self._grid_cell_offset = current_global_index % grid_cap

        # Find the selected frames for this chunk (relative to chunk start)
        self._chunk_frames_relative = []
        self._chunk_abs_start = 0
        self._chunk_abs_end = 0
        self._resolve_chunk_frames()

        # Load grid pixmap once
        self._grid_pixmap = QPixmap(self._grid_path)

        # Navigation state
        self._nav_index = 0  # index into self._chunk_frames_relative
        # Per-frame nudge: dict mapping frame index -> QPointF
        self._nudges: dict[int, QPointF] = {}
        self._aspect_locked = True

        self._build_ui()
        self._navigate_to(0)

    # -- chunk resolution ----------------------------------------------------

    def _resolve_chunk_frames(self):
        """Extract the list of frame indices (relative to chunk video) for the
        selected chunk from the JSON metadata."""
        chunks = self._json_data.get("chunks", [])
        chunk_meta = None
        for ch in chunks:
            if ch.get("chunk_index") == self._chunk_index:
                chunk_meta = ch
                break

        if chunk_meta:
            self._chunk_abs_start = chunk_meta.get("video_start_frame_abs", 0)
            self._chunk_abs_end = chunk_meta.get("video_end_frame_abs", 0)
            abs_frames = chunk_meta.get("selected_frames_abs", [])
            # Convert absolute frames to relative (0-based within the chunk video)
            self._chunk_frames_relative = [f - self._chunk_abs_start for f in abs_frames]
        else:
            # Fallback: try "chunk N" key
            key = f"chunk {self._chunk_index + 1}" if isinstance(self._chunk_index, int) else self._chunk_index
            frames = self._json_data.get(key, [])
            self._chunk_frames_relative = list(frames)

        if not self._chunk_frames_relative:
            self._chunk_frames_relative = [0]

    # -- UI construction -----------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # Viewport
        self._viewport = _SplitterViewport()
        self._viewport.set_grid(self._grid_pixmap)
        self._viewport.position_changed.connect(self._on_viewport_drag)
        root.addWidget(self._viewport, stretch=1)

        # --- Controls bar ---
        controls = QHBoxLayout()
        controls.setSpacing(12)

        # Navigation
        nav_group = QGroupBox("Navigation")
        nav_lay = QHBoxLayout(nav_group)
        self._prev_btn = QPushButton("◀ Prev")
        self._prev_btn.clicked.connect(lambda: self._navigate_to(self._nav_index - 1))
        self._next_btn = QPushButton("Next ▶")
        self._next_btn.clicked.connect(lambda: self._navigate_to(self._nav_index + 1))
        self._frame_label = QLabel("0 / 0")
        self._frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame_label.setFixedWidth(100)
        nav_lay.addWidget(self._prev_btn)
        nav_lay.addWidget(self._frame_label)
        nav_lay.addWidget(self._next_btn)
        controls.addWidget(nav_group)

        # Opacity
        opacity_group = QGroupBox("Opacity")
        opacity_lay = QVBoxLayout(opacity_group)
        opacity_row = QHBoxLayout()
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(50)
        self._opacity_spinbox = QSpinBox()
        self._opacity_spinbox.setRange(0, 100)
        self._opacity_spinbox.setValue(50)
        self._opacity_spinbox.setSuffix("%")
        self._opacity_spinbox.setFixedWidth(70)
        self._opacity_slider.valueChanged.connect(self._on_opacity_slider)
        self._opacity_spinbox.valueChanged.connect(self._on_opacity_spinbox)
        opacity_row.addWidget(self._opacity_slider, stretch=1)
        opacity_row.addWidget(self._opacity_spinbox)
        opacity_lay.addLayout(opacity_row)
        controls.addWidget(opacity_group)

        # Scale
        scale_group = QGroupBox("Scale")
        scale_lay = QVBoxLayout(scale_group)
        scale_row = QHBoxLayout()
        self._scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._scale_slider.setRange(10, 300)
        self._scale_slider.setValue(100)
        self._scale_spinbox = QSpinBox()
        self._scale_spinbox.setRange(10, 300)
        self._scale_spinbox.setValue(100)
        self._scale_spinbox.setSuffix("%")
        self._scale_spinbox.setFixedWidth(70)
        self._scale_slider.valueChanged.connect(self._on_scale_slider)
        self._scale_spinbox.valueChanged.connect(self._on_scale_spinbox)
        scale_row.addWidget(self._scale_slider, stretch=1)
        scale_row.addWidget(self._scale_spinbox)
        scale_lay.addLayout(scale_row)
        controls.addWidget(scale_group)

        # Aspect lock
        self._lock_cb = QCheckBox("Lock Aspect")
        self._lock_cb.setChecked(True)
        self._lock_cb.toggled.connect(self._on_aspect_toggle)
        controls.addWidget(self._lock_cb)

        # Reset nudge
        reset_btn = QPushButton("Reset Position")
        reset_btn.clicked.connect(self._reset_nudge)
        controls.addWidget(reset_btn)

        root.addLayout(controls)

        # Export button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        export_btn = QPushButton("Export Split Images")
        export_btn.setStyleSheet(
            "QPushButton { background: #2ecc71; color: white; padding: 10px 28px; "
            "border-radius: 5px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background: #27ae60; }"
        )
        export_btn.clicked.connect(self._do_export)
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("padding: 10px 18px; font-size: 13px;")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        btn_row.addWidget(export_btn)
        root.addLayout(btn_row)

    # -- navigation ----------------------------------------------------------

    def _save_current_nudge(self):
        """Persist the viewport's current nudge into the per-frame dict."""
        self._nudges[self._nav_index] = self._viewport.nudge()

    def _navigate_to(self, index: int):
        n = len(self._chunk_frames_relative)
        if n == 0:
            return

        # Save the nudge of the frame we're leaving
        self._save_current_nudge()

        index = max(0, min(index, n - 1))
        self._nav_index = index

        frame_num = self._chunk_frames_relative[index]
        pixmap = _load_video_frame(self._video_path, frame_num)
        self._viewport.set_frame(pixmap)

        # Compute algorithmic grid offset for this cell
        grid_index = index + self._grid_cell_offset
        col = grid_index % self._grid_dim
        row = grid_index // self._grid_dim
        base_x = -col * self._frame_w
        base_y = -row * self._frame_h
        self._viewport.set_base_offset(base_x, base_y)

        # Restore this frame's own nudge (default to zero if never adjusted)
        nudge = self._nudges.get(index, QPointF(0, 0))
        self._viewport.set_nudge(nudge)

        self._frame_label.setText(f"{index + 1} / {n}")
        self._prev_btn.setEnabled(index > 0)
        self._next_btn.setEnabled(index < n - 1)

    # -- control callbacks ---------------------------------------------------

    def _on_opacity_slider(self, val):
        self._opacity_spinbox.blockSignals(True)
        self._opacity_spinbox.setValue(val)
        self._opacity_spinbox.blockSignals(False)
        self._viewport.set_opacity(val / 100.0)

    def _on_opacity_spinbox(self, val):
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(val)
        self._opacity_slider.blockSignals(False)
        self._viewport.set_opacity(val / 100.0)

    def _on_scale_slider(self, val):
        self._scale_spinbox.blockSignals(True)
        self._scale_spinbox.setValue(val)
        self._scale_spinbox.blockSignals(False)
        self._viewport.set_scale(val / 100.0)

    def _on_scale_spinbox(self, val):
        self._scale_slider.blockSignals(True)
        self._scale_slider.setValue(val)
        self._scale_slider.blockSignals(False)
        self._viewport.set_scale(val / 100.0)

    def _on_aspect_toggle(self, checked):
        self._aspect_locked = checked

    def _on_viewport_drag(self):
        # Store the nudge for the current frame only
        self._nudges[self._nav_index] = self._viewport.nudge()

    def _reset_nudge(self):
        self._nudges[self._nav_index] = QPointF(0, 0)
        self._viewport.set_nudge(QPointF(0, 0))

    # -- export --------------------------------------------------------------

    def _do_export(self):
        if not self._output_folder:
            self._output_folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
            if not self._output_folder:
                return

        os.makedirs(self._output_folder, exist_ok=True)

        # Save current frame's nudge before exporting
        self._save_current_nudge()

        n = len(self._chunk_frames_relative)
        dim = self._grid_dim
        scale = self._scale_slider.value() / 100.0

        # Load the grid as a numpy array (BGR)
        grid_bgr = cv2.imread(self._grid_path, cv2.IMREAD_COLOR)
        if grid_bgr is None:
            QMessageBox.critical(self, "Error", "Could not load grid image for export.")
            return

        grid_h, grid_w = grid_bgr.shape[:2]
        # Apply scale to grid if needed
        if abs(scale - 1.0) > 0.001:
            new_w = int(grid_w * scale)
            new_h = int(grid_h * scale)
            grid_bgr = cv2.resize(grid_bgr, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
            grid_h, grid_w = grid_bgr.shape[:2]

        fw = self._frame_w
        fh = self._frame_h

        progress = QDialog(self)
        progress.setWindowTitle("Exporting…")
        progress.setFixedSize(320, 80)
        pbar = QProgressBar()
        pbar.setRange(0, n)
        pl = QVBoxLayout(progress)
        pl.addWidget(QLabel("Exporting split images…"))
        pl.addWidget(pbar)
        progress.show()

        base_name = os.path.splitext(os.path.basename(self._grid_path))[0]
        exported = []

        try:
            for i in range(n):
                grid_index = i + self._grid_cell_offset
                col = grid_index % dim
                row = grid_index // dim
                nudge_i = self._nudges.get(i, QPointF(0, 0))

                cell_gw = grid_w / dim
                cell_gh = grid_h / dim
                # Nudge shifts the grid relative to the frame, so the crop
                # region shifts in the opposite direction within the grid.
                nx = nudge_i.x() * scale
                ny = nudge_i.y() * scale
                x1 = int(col * cell_gw - nx)
                y1 = int(row * cell_gh - ny)
                x2 = int(x1 + cell_gw)
                y2 = int(y1 + cell_gh)

                # Clamp
                x1 = max(0, min(x1, grid_w))
                y1 = max(0, min(y1, grid_h))
                x2 = max(0, min(x2, grid_w))
                y2 = max(0, min(y2, grid_h))

                cell_crop = grid_bgr[y1:y2, x1:x2]

                # Resize to match original video frame dimensions
                if cell_crop.shape[0] > 0 and cell_crop.shape[1] > 0:
                    cell_crop = cv2.resize(cell_crop, (fw, fh), interpolation=cv2.INTER_LANCZOS4)

                frame_rel = self._chunk_frames_relative[i]
                out_name = f"{base_name}_split_{i:03d}_f{frame_rel:04d}.png"
                out_path = os.path.join(self._output_folder, out_name)
                cv2.imwrite(out_path, cell_crop)
                exported.append(out_name)

                pbar.setValue(i + 1)
                QApplication.processEvents()

        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "Export Error", str(exc))
            return

        progress.close()
        QMessageBox.information(
            self,
            "Export Complete",
            f"Exported {len(exported)} split image(s) to:\n{self._output_folder}",
        )
