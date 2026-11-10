"""Shot-grid export dialog, live shot table, and progress worker."""

from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_utils import IMAGE_EXPORT_FORMATS
from shot_grid import (
    DEFAULT_INTERVAL,
    DEFAULT_MAX_DIM,
    DEFAULT_MAX_RATIO,
    FitStrategy,
)
from shot_grid_export import (
    NamedShotPlan,
    ShotGridExportOptions,
    ShotGridExportResult,
    build_shot_plans,
    export_shot_grids,
    plan_summary,
)
from shot_grid_render import DEFAULT_GRID_SIDE, ShotGridMedia


GRID_SIDE_CHOICES = (1536, 2048, 3072, 4096)
INTERVAL_CHIPS = (2, 4, 8, 12, 24)


def _normalize_bookmark(bm, index: int = 0) -> tuple[int, str]:
    if isinstance(bm, dict):
        try:
            frame = int(bm.get("frame", -1))
        except (TypeError, ValueError):
            frame = -1
        name = str(bm.get("name") or "").strip()
    elif isinstance(bm, (int, float)):
        frame = int(bm)
        name = ""
    elif hasattr(bm, "frame"):
        try:
            frame = int(getattr(bm, "frame", -1))
        except (TypeError, ValueError):
            frame = -1
        name = str(getattr(bm, "name", "") or "").strip()
    else:
        frame = -1
        name = ""
    if not name and frame >= 0:
        name = f"Bookmark {index + 1}"
    return frame, name


class ShotGridExportWorker(QObject):
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, media, bookmarks, options):
        super().__init__()
        self.media = media
        self.bookmarks = list(bookmarks or [])
        self.options = options
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            result = export_shot_grids(
                self.media,
                self.bookmarks,
                self.options,
                progress_callback=lambda message, done, total: self.progress.emit(
                    message, done, total
                ),
                cancel_check=lambda: self._cancelled,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class ShotGridProgressDialog(QDialog):
    """Modal progress window that keeps the export on a worker thread."""

    def __init__(self, parent, media, bookmarks, options):
        super().__init__(parent)
        self.setWindowTitle("Exporting Shot Grids")
        self.setModal(True)
        self.setFixedSize(470, 150)

        self._result: ShotGridExportResult | None = None
        self._error = ""
        self._thread: QThread | None = None
        self._worker: ShotGridExportWorker | None = None

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Preparing export...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        layout.addWidget(self.bar)
        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._request_cancel)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self._thread = QThread(self)
        self._worker = ShotGridExportWorker(media, bookmarks, options)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)

    def run(self) -> ShotGridExportResult | None:
        self._thread.start()
        self.exec()
        return self._result

    def _on_progress(self, message, done, total):
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        self.status_label.setText(message)

    def _on_worker_finished(self, result):
        self._result = result
        self.status_label.setText(
            "Export finished." if not result.cancelled else "Export cancelled."
        )
        self.cancel_button.setEnabled(False)

    def _on_worker_failed(self, message):
        self._error = message
        self.status_label.setText("Export failed.")
        self.cancel_button.setEnabled(False)

    def _on_thread_finished(self):
        self._thread = None
        self._worker = None
        if self._error:
            QMessageBox.critical(self, "Export Error", self._error)
            super().reject()
            return
        super().accept()

    def _request_cancel(self):
        if self._worker is not None:
            self._worker.cancel()
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Cancelling after the current image...")

    def reject(self):
        if self._thread is not None and self._thread.isRunning():
            self._request_cancel()
            return
        super().reject()

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._request_cancel()
            event.ignore()
            return
        super().closeEvent(event)


class ShotGridDialog(QDialog):
    """Preview and configure one grid image per bookmarked shot."""

    def __init__(
        self,
        parent=None,
        *,
        media: ShotGridMedia | None = None,
        bookmarks=None,
        settings=None,
        default_folder: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("Export Shot Grids")
        self.setModal(True)
        self.setMinimumSize(920, 780)

        self.media = media
        self.bookmarks = list(bookmarks if bookmarks is not None else getattr(parent, "bookmarks", []) or [])
        self.settings = dict(settings or {})
        self.default_folder = (
            default_folder
            or (getattr(parent, "get_default_export_folder", lambda: "")() if parent else "")
            or os.path.expanduser("~")
        )
        self.total_frames = (
            media.total_frames
            if media is not None
            else int(getattr(parent, "total_frames", 0) or 0)
        )
        self.fps = (
            media.fps
            if media is not None
            else float(getattr(parent, "fps", 24) or 24)
        )
        self.source_name = (
            media.source_name
            if media is not None
            else str(getattr(parent, "source_name", "") or "kfplayer")
        )
        self.in_point = None
        self.out_point = None
        self._read_timeline_points(parent)

        self.export_options: ShotGridExportOptions | None = None
        self._plans: list[NamedShotPlan] = []
        self._checked: dict[tuple[int, int], bool] = {}
        self._loading = True

        self._build_ui()
        self._populate_bookmark_combos()
        self._connect_signals()
        self._apply_settings(self.settings)
        self._loading = False
        self._update_range_controls()
        self._sync_interval_chips()
        self._update_fit_controls()
        self._update_quality_state(self.format_combo.currentText())
        self.refresh_preview()

    # -- construction --------------------------------------------------------

    def _read_timeline_points(self, parent):
        timeline = getattr(parent, "timeline", None) if parent is not None else None
        if timeline is not None:
            self.in_point = getattr(timeline, "in_point", None)
            self.out_point = getattr(timeline, "out_point", None)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(8)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        info = QLabel(
            "Each bookmark starts a shot. The last shot ends at the clip/range end. "
            "Every grid is completely full; long shots are split into equal grids."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray;")
        layout.addWidget(info)

        layout.addWidget(self._build_sampling_group())
        layout.addWidget(self._build_shots_group())
        layout.addWidget(self._build_output_group())

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.export_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.export_button.setText("Export")
        self.buttons.accepted.connect(self._on_export_clicked)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    def _build_sampling_group(self):
        group = QGroupBox("Sampling")
        form = QFormLayout(group)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 120)
        self.interval_spin.setValue(DEFAULT_INTERVAL)
        self.interval_spin.setSuffix(" frames")
        interval_row = QWidget()
        interval_layout = QHBoxLayout(interval_row)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.addWidget(self.interval_spin)
        self.interval_chips = {}
        for value in INTERVAL_CHIPS:
            chip = QPushButton(str(value))
            chip.setCheckable(True)
            chip.setFixedWidth(38)
            chip.setToolTip(f"Every {value}th frame")
            chip.clicked.connect(
                lambda _checked=False, v=value: self._set_interval_from_chip(v)
            )
            self.interval_chips[value] = chip
            interval_layout.addWidget(chip)
        interval_layout.addStretch()
        form.addRow("Every Nth frame:", interval_row)

        self.max_grid_combo = QComboBox()
        for value in (3, 4, 5):
            self.max_grid_combo.addItem(f"{value}×{value} ({value * value} cells)", value)
        self.max_grid_combo.setCurrentIndex(
            self.max_grid_combo.findData(DEFAULT_MAX_DIM)
        )
        form.addRow("Max grid:", self.max_grid_combo)

        self.layout_combo = QComboBox()
        self.layout_combo.addItem("Square", False)
        self.layout_combo.addItem("Compact rectangles", True)
        form.addRow("Layout:", self.layout_combo)

        self.fit_combo = QComboBox()
        self.fit_combo.addItem("Balanced", FitStrategy.BALANCED)
        self.fit_combo.addItem("Trim (never add frames)", FitStrategy.TRIM)
        self.fit_combo.addItem("Fill (never drop frames)", FitStrategy.FILL)
        form.addRow("Fit:", self.fit_combo)

        self.max_ratio_spin = QDoubleSpinBox()
        self.max_ratio_spin.setRange(1.0, 2.0)
        self.max_ratio_spin.setSingleStep(0.05)
        self.max_ratio_spin.setDecimals(2)
        self.max_ratio_spin.setValue(DEFAULT_MAX_RATIO)
        self.max_ratio_spin.setPrefix("×")
        form.addRow("Max spacing change:", self.max_ratio_spin)

        hint = QLabel(
            "Balanced keeps the fewest images that stay close to the requested spacing. "
            "Trim only removes frames; Fill only adds frames."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 10px;")
        form.addRow(hint)
        return group

    def _build_shots_group(self):
        group = QGroupBox("Shots")
        layout = QVBoxLayout(group)

        range_row = QHBoxLayout()
        self.range_combo = QComboBox()
        self.range_combo.addItem("Whole clip", "all")
        self.range_combo.addItem("Custom range", "custom")
        if self.in_point is not None and self.out_point is not None:
            self.range_combo.addItem(
                f"In/Out range ({min(self.in_point, self.out_point) + 1}–"
                f"{max(self.in_point, self.out_point) + 1})",
                "inout",
            )
        range_row.addWidget(QLabel("Range:"))
        range_row.addWidget(self.range_combo, stretch=1)
        self.range_custom_widget = QWidget()
        custom_row = QHBoxLayout(self.range_custom_widget)
        custom_row.setContentsMargins(0, 0, 0, 0)
        self.range_start_spin = QSpinBox()
        self.range_start_spin.setRange(0, max(0, self.total_frames - 1))
        self.range_end_spin = QSpinBox()
        self.range_end_spin.setRange(0, max(0, self.total_frames - 1))
        self.range_end_spin.setValue(max(0, self.total_frames - 1))
        custom_row.addWidget(QLabel("Start:"))
        custom_row.addWidget(self.range_start_spin)
        custom_row.addWidget(QLabel("End:"))
        custom_row.addWidget(self.range_end_spin)
        range_row.addWidget(self.range_custom_widget)
        layout.addLayout(range_row)

        bookmark_row = QHBoxLayout()
        self.start_bookmark_check = QCheckBox("Select start bookmark")
        self.start_bookmark_check.setToolTip(
            "When checked, shots start from the selected bookmark instead of the beginning of the clip."
        )
        self.start_bookmark_combo = QComboBox()
        self.start_bookmark_combo.setEnabled(False)

        self.end_bookmark_check = QCheckBox("Select end bookmark")
        self.end_bookmark_check.setToolTip(
            "When checked, shots end after the selected bookmark instead of the end of the clip."
        )
        self.end_bookmark_combo = QComboBox()
        self.end_bookmark_combo.setEnabled(False)

        bookmark_row.addWidget(self.start_bookmark_check)
        bookmark_row.addWidget(self.start_bookmark_combo, stretch=1)
        bookmark_row.addSpacing(16)
        bookmark_row.addWidget(self.end_bookmark_check)
        bookmark_row.addWidget(self.end_bookmark_combo, stretch=1)
        layout.addLayout(bookmark_row)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["", "#", "Shot / bookmark", "Frames", "Length", "Samples", "Grid", "Spacing"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in range(3, 8):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(210)
        layout.addWidget(self.table)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        return group

    def _build_output_group(self):
        group = QGroupBox("Output")
        form = QFormLayout(group)

        self.output_folder = QLineEdit(self.default_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.output_folder)
        browse = QPushButton("...")
        browse.setFixedWidth(30)
        browse.clicked.connect(self._browse_output_folder)
        folder_row.addWidget(browse)
        form.addRow("Output folder:", folder_row)

        self.prefix_edit = QLineEdit(self.source_name)
        form.addRow("Filename prefix:", self.prefix_edit)

        self.format_combo = QComboBox()
        self.format_combo.addItems(list(IMAGE_EXPORT_FORMATS.keys()))
        form.addRow("Format:", self.format_combo)

        self.jpeg_quality = QSlider(Qt.Orientation.Horizontal)
        self.jpeg_quality.setRange(80, 100)
        self.jpeg_quality.setValue(95)
        self.jpeg_quality_label = QLabel("JPEG quality: 95")
        self.jpeg_quality.valueChanged.connect(self._update_quality_label)
        quality_box = QVBoxLayout()
        quality_box.addWidget(self.jpeg_quality_label)
        quality_box.addWidget(self.jpeg_quality)
        form.addRow("JPEG:", quality_box)

        self.grid_side_combo = QComboBox()
        for side in GRID_SIDE_CHOICES:
            self.grid_side_combo.addItem(f"{side} px longest side", side)
        self.grid_side_combo.addItem("Native", None)
        self.grid_side_combo.setCurrentIndex(
            self.grid_side_combo.findData(DEFAULT_GRID_SIDE)
        )
        form.addRow("Grid size:", self.grid_side_combo)

        self.gap_spin = QSpinBox()
        self.gap_spin.setRange(0, 64)
        self.gap_spin.setValue(0)
        self.gap_spin.setSuffix(" px")
        form.addRow("Gap between cells:", self.gap_spin)

        self.burn_labels_check = QCheckBox("Burn in frame numbers")
        self.subfolder_check = QCheckBox("Subfolder per shot")
        self.individual_frames_check = QCheckBox("Also save individual frames")
        self.manifest_check = QCheckBox("Write manifest JSON")
        self.manifest_check.setChecked(True)
        self.sidecar_check = QCheckBox("Write Smart Grid Splitter sidecars")
        self.sidecar_check.setChecked(True)
        for checkbox in (
            self.burn_labels_check,
            self.subfolder_check,
            self.individual_frames_check,
            self.manifest_check,
            self.sidecar_check,
        ):
            form.addRow("", checkbox)

        hint = QLabel(
            "Grids are written to a '{prefix}_shot_grids' folder. Sidecars let the "
            "Smart Grid Splitter reopen a grid against the full source clip."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 10px;")
        form.addRow(hint)
        return group

    def _get_sorted_bookmarks(self) -> list[tuple[int, str]]:
        seen_frames = set()
        result = []
        raw = []
        for i, bm in enumerate(self.bookmarks or []):
            frame, name = _normalize_bookmark(bm, i)
            if frame >= 0:
                raw.append((frame, name))
        for frame, name in sorted(raw, key=lambda item: item[0]):
            if frame not in seen_frames:
                seen_frames.add(frame)
                result.append((frame, name))
        return result

    def _populate_bookmark_combos(self):
        sorted_bms = self._get_sorted_bookmarks()
        self.start_bookmark_combo.blockSignals(True)
        self.end_bookmark_combo.blockSignals(True)
        try:
            self.start_bookmark_combo.clear()
            self.end_bookmark_combo.clear()

            has_bms = len(sorted_bms) > 0
            self.start_bookmark_check.setEnabled(has_bms)
            self.end_bookmark_check.setEnabled(has_bms)

            for frame, name in sorted_bms:
                label = f"{name} (frame {frame + 1})"
                self.start_bookmark_combo.addItem(label, frame)
                self.end_bookmark_combo.addItem(label, frame)

            if has_bms:
                self.start_bookmark_combo.setCurrentIndex(0)
                self.end_bookmark_combo.setCurrentIndex(len(sorted_bms) - 1)
        finally:
            self.start_bookmark_combo.blockSignals(False)
            self.end_bookmark_combo.blockSignals(False)

    def _on_start_bookmark_toggled(self, checked: bool):
        self.start_bookmark_combo.setEnabled(checked)
        if checked and self.end_bookmark_check.isChecked():
            if self.start_bookmark_combo.currentIndex() > self.end_bookmark_combo.currentIndex():
                self.end_bookmark_combo.setCurrentIndex(self.start_bookmark_combo.currentIndex())
        self.refresh_preview()

    def _on_end_bookmark_toggled(self, checked: bool):
        self.end_bookmark_combo.setEnabled(checked)
        if checked and self.start_bookmark_check.isChecked():
            if self.end_bookmark_combo.currentIndex() < self.start_bookmark_combo.currentIndex():
                self.start_bookmark_combo.setCurrentIndex(self.end_bookmark_combo.currentIndex())
        self.refresh_preview()

    def _on_start_bookmark_combo_changed(self, index: int):
        if getattr(self, "_loading", False):
            return
        if self.end_bookmark_check.isChecked() and index >= 0:
            if index > self.end_bookmark_combo.currentIndex():
                self.end_bookmark_combo.setCurrentIndex(index)
        self.refresh_preview()

    def _on_end_bookmark_combo_changed(self, index: int):
        if getattr(self, "_loading", False):
            return
        if self.start_bookmark_check.isChecked() and index >= 0:
            if index < self.start_bookmark_combo.currentIndex():
                self.start_bookmark_combo.setCurrentIndex(index)
        self.refresh_preview()

    def _connect_signals(self):
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        self.max_grid_combo.currentIndexChanged.connect(self.refresh_preview)
        self.layout_combo.currentIndexChanged.connect(self.refresh_preview)
        self.fit_combo.currentIndexChanged.connect(self._update_fit_controls)
        self.max_ratio_spin.valueChanged.connect(self.refresh_preview)
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        self.range_start_spin.valueChanged.connect(self.refresh_preview)
        self.range_end_spin.valueChanged.connect(self.refresh_preview)
        self.start_bookmark_check.toggled.connect(self._on_start_bookmark_toggled)
        self.start_bookmark_combo.currentIndexChanged.connect(
            self._on_start_bookmark_combo_changed
        )
        self.end_bookmark_check.toggled.connect(self._on_end_bookmark_toggled)
        self.end_bookmark_combo.currentIndexChanged.connect(
            self._on_end_bookmark_combo_changed
        )
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
        self.format_combo.currentTextChanged.connect(self._update_quality_state)

    # -- settings ------------------------------------------------------------

    def _apply_settings(self, settings):
        settings = settings or {}

        def _set_combo(combo, value):
            for index in range(combo.count()):
                if combo.itemData(index) == value:
                    combo.setCurrentIndex(index)
                    return

        try:
            interval = int(settings.get("interval", DEFAULT_INTERVAL))
        except (TypeError, ValueError):
            interval = DEFAULT_INTERVAL
        self.interval_spin.setValue(max(1, min(120, interval)))

        try:
            max_grid = int(settings.get("max_grid", DEFAULT_MAX_DIM))
        except (TypeError, ValueError):
            max_grid = DEFAULT_MAX_DIM
        _set_combo(self.max_grid_combo, max_grid if max_grid in (3, 4, 5) else 5)

        _set_combo(
            self.layout_combo,
            bool(settings.get("rectangular", settings.get("layout") == "rectangles")),
        )

        strategy = settings.get("strategy", FitStrategy.BALANCED)
        try:
            strategy = FitStrategy(strategy)
        except ValueError:
            strategy = FitStrategy.BALANCED
        _set_combo(self.fit_combo, strategy)

        try:
            ratio = float(settings.get("max_ratio", DEFAULT_MAX_RATIO))
        except (TypeError, ValueError):
            ratio = DEFAULT_MAX_RATIO
        self.max_ratio_spin.setValue(max(1.0, min(2.0, ratio)))

        grid_side = settings.get("grid_side", DEFAULT_GRID_SIDE)
        if isinstance(grid_side, str):
            grid_side = None if grid_side.lower() == "native" else int(grid_side)
        if grid_side is not None and grid_side not in GRID_SIDE_CHOICES:
            grid_side = DEFAULT_GRID_SIDE
        _set_combo(self.grid_side_combo, grid_side)

        format_name = settings.get("format", "PNG")
        if format_name not in IMAGE_EXPORT_FORMATS:
            format_name = "PNG"
        self.format_combo.setCurrentText(format_name)

        try:
            quality = int(settings.get("jpeg_quality", 95))
        except (TypeError, ValueError):
            quality = 95
        self.jpeg_quality.setValue(max(80, min(100, quality)))

        try:
            gap = int(settings.get("gap", 0))
        except (TypeError, ValueError):
            gap = 0
        self.gap_spin.setValue(max(0, min(64, gap)))

        self.burn_labels_check.setChecked(
            bool(settings.get("burn_frame_numbers", False))
        )
        self.subfolder_check.setChecked(
            bool(settings.get("subfolder_per_shot", False))
        )
        self.individual_frames_check.setChecked(
            bool(settings.get("save_individual_frames", False))
        )
        self.manifest_check.setChecked(bool(settings.get("write_manifest", True)))
        self.sidecar_check.setChecked(
            bool(settings.get("write_splitter_sidecars", True))
        )

        folder = str(settings.get("output_folder") or self.default_folder)
        self.output_folder.setText(folder)
        prefix = str(settings.get("prefix") or self.source_name)
        self.prefix_edit.setText(prefix)

        start_bm_enabled = bool(settings.get("start_bookmark_enabled", False))
        if self.start_bookmark_check.isEnabled():
            self.start_bookmark_check.setChecked(start_bm_enabled)
            self.start_bookmark_combo.setEnabled(start_bm_enabled)
            saved_start = settings.get("start_bookmark_frame")
            if saved_start is not None:
                idx = self.start_bookmark_combo.findData(int(saved_start))
                if idx >= 0:
                    self.start_bookmark_combo.setCurrentIndex(idx)

        end_bm_enabled = bool(settings.get("end_bookmark_enabled", False))
        if self.end_bookmark_check.isEnabled():
            self.end_bookmark_check.setChecked(end_bm_enabled)
            self.end_bookmark_combo.setEnabled(end_bm_enabled)
            saved_end = settings.get("end_bookmark_frame")
            if saved_end is not None:
                idx = self.end_bookmark_combo.findData(int(saved_end))
                if idx >= 0:
                    self.end_bookmark_combo.setCurrentIndex(idx)

    def collect_settings(self) -> dict:
        return {
            "interval": self.interval_spin.value(),
            "max_grid": int(self.max_grid_combo.currentData() or DEFAULT_MAX_DIM),
            "rectangular": bool(self.layout_combo.currentData()),
            "layout": "rectangles" if self.layout_combo.currentData() else "square",
            "strategy": FitStrategy(self.fit_combo.currentData()).value,
            "max_ratio": float(self.max_ratio_spin.value()),
            "grid_side": self.grid_side_combo.currentData(),
            "gap": self.gap_spin.value(),
            "burn_frame_numbers": self.burn_labels_check.isChecked(),
            "subfolder_per_shot": self.subfolder_check.isChecked(),
            "save_individual_frames": self.individual_frames_check.isChecked(),
            "write_manifest": self.manifest_check.isChecked(),
            "write_splitter_sidecars": self.sidecar_check.isChecked(),
            "start_bookmark_enabled": self.start_bookmark_check.isChecked(),
            "start_bookmark_frame": self.start_bookmark_combo.currentData(),
            "end_bookmark_enabled": self.end_bookmark_check.isChecked(),
            "end_bookmark_frame": self.end_bookmark_combo.currentData(),
            "format": self.format_combo.currentText(),
            "jpeg_quality": self.jpeg_quality.value(),
            "output_folder": self.output_folder.text().strip(),
            "prefix": self.prefix_edit.text().strip(),
        }

    # -- range and preview ---------------------------------------------------

    def _range_values(self) -> tuple[int, int]:
        mode = self.range_combo.currentData()
        if mode == "custom":
            base_start, base_end = (
                self.range_start_spin.value(),
                self.range_end_spin.value(),
            )
        elif mode == "inout" and self.in_point is not None and self.out_point is not None:
            base_start = min(self.in_point, self.out_point)
            base_end = max(self.in_point, self.out_point)
        else:
            base_start = 0
            base_end = max(0, self.total_frames - 1)

        range_start = base_start
        range_end = base_end

        if (
            hasattr(self, "start_bookmark_check")
            and self.start_bookmark_check.isChecked()
        ):
            start_bm_frame = self.start_bookmark_combo.currentData()
            if start_bm_frame is not None:
                range_start = int(start_bm_frame)

        if (
            hasattr(self, "end_bookmark_check")
            and self.end_bookmark_check.isChecked()
        ):
            end_bm_frame = self.end_bookmark_combo.currentData()
            if end_bm_frame is not None:
                end_frame = int(end_bm_frame)
                sorted_frames = [f for f, _ in self._get_sorted_bookmarks()]
                next_frames = [f for f in sorted_frames if f > end_frame]
                if next_frames:
                    range_end = next_frames[0] - 1
                else:
                    range_end = max(0, self.total_frames - 1)

        return range_start, range_end

    def _update_range_controls(self):
        custom = self.range_combo.currentData() == "custom"
        self.range_custom_widget.setVisible(custom)

    def _set_interval_from_chip(self, value):
        self.interval_spin.setValue(value)
        self._sync_interval_chips()

    def _on_range_changed(self, _index=None):
        self._update_range_controls()
        self.refresh_preview()

    def _collect_options(self) -> ShotGridExportOptions:
        range_start, range_end = self._range_values()
        included = frozenset(
            plan.shot.index for plan in self._plans if self._is_checked(plan)
        )
        return ShotGridExportOptions(
            output_folder=self.output_folder.text().strip(),
            prefix=self.prefix_edit.text().strip() or self.source_name,
            range_start=range_start,
            range_end=range_end,
            interval=self.interval_spin.value(),
            max_dim=int(self.max_grid_combo.currentData() or DEFAULT_MAX_DIM),
            rectangular=bool(self.layout_combo.currentData()),
            strategy=FitStrategy(self.fit_combo.currentData()),
            max_ratio=float(self.max_ratio_spin.value()),
            format_name=self.format_combo.currentText(),
            jpeg_quality=self.jpeg_quality.value(),
            grid_side=self.grid_side_combo.currentData(),
            gap=self.gap_spin.value(),
            burn_frame_numbers=self.burn_labels_check.isChecked(),
            subfolder_per_shot=self.subfolder_check.isChecked(),
            save_individual_frames=self.individual_frames_check.isChecked(),
            write_manifest=self.manifest_check.isChecked(),
            write_splitter_sidecars=self.sidecar_check.isChecked(),
            include_shots=included,
        )

    def _key_for(self, plan: NamedShotPlan):
        return (plan.shot.index, plan.shot.start)

    def _is_checked(self, plan: NamedShotPlan) -> bool:
        key = self._key_for(plan)
        if key in self._checked:
            return self._checked[key]
        return plan.shot.index != 0

    def refresh_preview(self, *_args):
        if getattr(self, "_loading", False):
            return

        if self.media is None or self.total_frames <= 0:
            self._plans = []
            self.table.setRowCount(0)
            self.summary_label.setText("No media loaded.")
            self.export_button.setEnabled(False)
            return

        if not self.bookmarks:
            self._plans = []
            self.table.setRowCount(0)
            self.summary_label.setText(
                "Add a bookmark at the start of each shot, or run Detect Shots first."
            )
            self.export_button.setEnabled(False)
            return

        range_start, range_end = self._range_values()
        if range_start > range_end:
            self._plans = []
            self.table.setRowCount(0)
            self.summary_label.setText("Invalid range: start is after end.")
            self.export_button.setEnabled(False)
            return

        options = self._collect_options()
        try:
            self._plans = build_shot_plans(
                self.bookmarks,
                range_end=range_end,
                options=options,
                range_start=range_start,
                include_lead_in=True,
            )
        except Exception as exc:
            self._plans = []
            self.table.setRowCount(0)
            self.summary_label.setText(f"Could not plan this range: {exc}")
            self.export_button.setEnabled(False)
            return

        if not self._plans:
            self.table.setRowCount(0)
            self.summary_label.setText(
                "No bookmarks inside the selected range."
            )
            self.export_button.setEnabled(False)
            return

        self._rebuild_table()
        self._update_summary()

    def _rebuild_table(self):
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self._plans))
            for row, plan in enumerate(self._plans):
                checked = self._is_checked(plan)
                self._checked[self._key_for(plan)] = checked

                check_item = QTableWidgetItem("")
                check_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                check_item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
                check_item.setData(Qt.ItemDataRole.UserRole, self._key_for(plan))
                self.table.setItem(row, 0, check_item)

                values = [
                    str(plan.shot.index),
                    plan.name,
                    f"{plan.shot.start + 1}–{plan.shot.end + 1}",
                    str(plan.shot.length),
                    str(plan.plan.samples_at_interval),
                    self._layout_label(plan),
                    self._spacing_label(plan),
                ]
                for column, value in enumerate(values, start=1):
                    item = QTableWidgetItem(value)
                    if column >= 3:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight
                            | Qt.AlignmentFlag.AlignVCenter
                        )
                    self.table.setItem(row, column, item)
        finally:
            self.table.blockSignals(False)

    @staticmethod
    def _layout_label(plan: NamedShotPlan) -> str:
        rows = plan.plan.parts[0].rows
        cols = plan.plan.parts[0].cols
        if len(plan.plan.parts) == 1:
            return f"{rows}×{cols}"
        return f"{len(plan.plan.parts)} × {rows}×{cols}"

    @staticmethod
    def _spacing_label(plan: NamedShotPlan) -> str:
        spacing = plan.plan.effective_interval
        return "–" if spacing is None else f"{spacing:.2f}"

    def _on_table_item_changed(self, item):
        if item is None or item.column() != 0:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key is None:
            return
        self._checked[key] = item.checkState() == Qt.CheckState.Checked
        self._update_summary()

    def _on_table_double_clicked(self, row, _column):
        if row < 0 or row >= len(self._plans):
            return
        seek = getattr(self.parent(), "seek_to_frame", None)
        if callable(seek):
            seek(self._plans[row].shot.start)

    def _update_summary(self):
        included = {
            plan.shot.index for plan in self._plans if self._is_checked(plan)
        }
        summary = plan_summary(self._plans, included)
        shot_word = "shot" if summary["shots"] == 1 else "shots"
        image_word = "image" if summary["images"] == 1 else "images"
        text = (
            f"{summary['shots']} {shot_word} → {summary['images']} {image_word}, "
            f"{summary['empty_cells']} empty cell(s)"
        )
        if summary["short_shots"]:
            text += f" · {len(summary['short_shots'])} shot(s) shorter than the interval"
        if any(p.shot.index == 0 for p in self._plans) and 0 not in included:
            text += " · lead-in excluded"
        self.summary_label.setText(text)
        self.export_button.setEnabled(
            bool(self.media is not None and self.bookmarks and summary["shots"] > 0)
        )

    # -- small control updates ----------------------------------------------

    def _on_interval_changed(self, _value=None):
        self._sync_interval_chips()
        self.refresh_preview()

    def _sync_interval_chips(self):
        value = self.interval_spin.value()
        for chip_value, chip in self.interval_chips.items():
            chip.setChecked(chip_value == value)

    def _update_fit_controls(self, *_args):
        balanced = self.fit_combo.currentData() == FitStrategy.BALANCED
        self.max_ratio_spin.setEnabled(balanced)
        self.refresh_preview()

    def _update_quality_state(self, format_name):
        is_jpeg = format_name == "JPEG"
        self.jpeg_quality.setEnabled(is_jpeg)
        self.jpeg_quality_label.setEnabled(is_jpeg)

    def _update_quality_label(self, value):
        self.jpeg_quality_label.setText(f"JPEG quality: {value}")

    def _browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder.setText(folder)

    # -- export --------------------------------------------------------------

    def _on_export_clicked(self):
        if self.media is None or self.total_frames <= 0:
            QMessageBox.warning(self, "Export", "No media is loaded.")
            return
        if not self.bookmarks:
            QMessageBox.warning(
                self, "Export", "No bookmarks available. Add one at each shot start."
            )
            return
        range_start, range_end = self._range_values()
        if range_start > range_end:
            QMessageBox.warning(self, "Export", "The range start is after the range end.")
            return
        output_folder = self.output_folder.text().strip()
        if not output_folder:
            QMessageBox.warning(self, "Export", "Choose an output folder.")
            return
        included = [
            plan for plan in self._plans if self._is_checked(plan)
        ]
        if not included:
            QMessageBox.warning(self, "Export", "Select at least one shot to export.")
            return

        if (
            self.grid_side_combo.currentData() is None
            and self.media.width > 0
            and self.media.height > 0
        ):
            largest_cells = max(
                plan.plan.parts[0].rows * plan.plan.parts[0].cols
                for plan in included
            )
            pixels = largest_cells * self.media.width * self.media.height
            if pixels >= 100_000_000:
                memory_mb = pixels * 3 / 1_000_000
                answer = QMessageBox.question(
                    self,
                    "Large Native Grid",
                    f"The largest grid will be about {pixels / 1_000_000:.0f} "
                    f"megapixels (~{memory_mb:.0f} MB in memory). Export it "
                    "at Native size?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return

        self.export_options = self._collect_options()
        save_settings = getattr(self.parent(), "save_shot_grid_settings", None)
        if callable(save_settings):
            save_settings(self.collect_settings())
        self.accept()


def show_shot_grid_export(parent, dialog: ShotGridDialog):
    """Run a configured dialog's export and show its summary.

    Kept here so the main window stays a thin caller and tests can drive the
    dialog without opening the progress window.
    """
    if dialog.export_options is None:
        return None
    progress = ShotGridProgressDialog(
        parent,
        dialog.media,
        dialog.bookmarks,
        dialog.export_options,
    )
    result = progress.run()
    if result is None:
        return None
    if result.errors:
        detail = "\n".join(result.errors[:6])
        if len(result.errors) > 6:
            detail += f"\n…and {len(result.errors) - 6} more."
        QMessageBox.warning(
            parent,
            "Export Finished with Errors",
            f"Saved {result.image_count} image(s) to:\n{result.output_root}\n\n{detail}",
        )
    elif result.cancelled:
        QMessageBox.information(
            parent,
            "Export Cancelled",
            f"Cancelled after saving {result.image_count} image(s) to:\n"
            f"{result.output_root}",
        )
    else:
        QMessageBox.information(
            parent,
            "Export Complete",
            f"Exported {result.image_count} image(s) for {result.shot_count} shot(s) to:\n"
            f"{result.output_root}",
        )
    return result
