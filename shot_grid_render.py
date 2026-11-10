"""Rendering helpers for shot grids and reusable contact sheets.

The planner in :mod:`shot_grid` is pure Python. This module owns the image side:
reading frames efficiently, computing a cell size that keeps the source aspect
ratio, composing rows by row, and writing the result.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Sequence

import cv2
import numpy as np
from PIL import Image

from shot_grid import GridPart


DEFAULT_GRID_SIDE = 2048
DEFAULT_BACKGROUND = (0, 0, 0)


class FrameReadError(RuntimeError):
    """Raised when a frame cannot be read."""

    def __init__(self, frame_num: int, message: str = ""):
        self.frame_num = frame_num
        detail = f": {message}" if message else ""
        super().__init__(f"Could not read frame {frame_num}{detail}")


@dataclass(frozen=True)
class ShotGridMedia:
    source_name: str
    total_frames: int
    fps: float
    kind: str                 # "video", "gif" or "sequence"
    path: str = ""
    files: tuple[str, ...] = ()
    width: int = 0            # optional source dimensions for size warnings
    height: int = 0


@dataclass(frozen=True)
class GridRenderOptions:
    max_side: int | None = DEFAULT_GRID_SIDE
    gap: int = 0
    burn_frame_numbers: bool = False
    background: tuple[int, int, int] = DEFAULT_BACKGROUND


def _as_rgb_array(frame) -> np.ndarray:
    array = np.asarray(frame)
    if array.ndim == 2:
        array = cv2.cvtColor(array, cv2.COLOR_GRAY2RGB)
    elif array.ndim == 3 and array.shape[2] == 4:
        array = cv2.cvtColor(array, cv2.COLOR_RGBA2RGB)
    elif array.ndim == 3 and array.shape[2] == 3:
        pass
    else:
        raise ValueError(f"Unsupported frame shape: {array.shape}")
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(array)


class VideoFrameReader:
    """Reads a video through one OpenCV capture, ascending-frame friendly.

    Frames are normally requested in ascending order. Reading forward uses
    ``grab()`` to skip without decoding, and seeking backwards repositions the
    capture. This avoids reopening the file for every cell.
    """

    def __init__(self, path: str):
        self.path = path
        self._cap = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            raise FrameReadError(0, f"could not open video {path}")
        self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._next_frame = 0
        if self.width <= 0 or self.height <= 0:
            ok, frame = self._cap.read()
            if ok:
                self.height, self.width = frame.shape[:2]
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self._next_frame = 0

    def read(self, frame_num: int) -> np.ndarray:
        if frame_num < 0:
            raise FrameReadError(frame_num, "negative frame number")
        if frame_num < self._next_frame:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            self._next_frame = frame_num

        while self._next_frame < frame_num:
            if not self._cap.grab():
                # Some codecs dislike long grab chains. Re-seek once.
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                self._next_frame = frame_num
                break
            self._next_frame += 1

        ok, frame = self._cap.read()
        if not ok:
            # A single re-seek is a cheap retry for keyframe-based codecs.
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ok, frame = self._cap.read()
            self._next_frame = frame_num + 1
        else:
            self._next_frame += 1

        if not ok or frame is None:
            raise FrameReadError(frame_num, f"video {os.path.basename(self.path)}")
        return _as_rgb_array(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    def close(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class GifFrameReader:
    def __init__(self, path: str):
        self.path = path
        self._image = Image.open(path)
        self.width, self.height = self._image.size

    def read(self, frame_num: int) -> np.ndarray:
        try:
            self._image.seek(frame_num)
            frame = self._image.convert("RGB")
            return _as_rgb_array(np.array(frame))
        except Exception as exc:
            raise FrameReadError(frame_num, str(exc)) from exc

    def close(self):
        if self._image is not None:
            self._image.close()
            self._image = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class SequenceFrameReader:
    def __init__(self, files: Sequence[str]):
        self.files = tuple(files)
        if not self.files:
            raise FrameReadError(0, "the image sequence is empty")
        try:
            with Image.open(self.files[0]) as image:
                self.width, self.height = image.size
        except Exception as exc:
            raise FrameReadError(0, f"could not open {self.files[0]}: {exc}") from exc

    def read(self, frame_num: int) -> np.ndarray:
        if frame_num < 0 or frame_num >= len(self.files):
            raise FrameReadError(frame_num, "frame is outside the image sequence")
        path = self.files[frame_num]
        try:
            with Image.open(path) as image:
                return _as_rgb_array(np.array(image.convert("RGB")))
        except Exception as exc:
            raise FrameReadError(frame_num, f"{path}: {exc}") from exc

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def create_frame_reader(media: ShotGridMedia):
    if media.kind == "video":
        return VideoFrameReader(media.path)
    if media.kind == "gif":
        return GifFrameReader(media.path)
    if media.kind == "sequence":
        return SequenceFrameReader(media.files)
    raise ValueError(f"Unsupported media kind: {media.kind}")


def compute_cell_size(
    rows: int,
    cols: int,
    source_width: int,
    source_height: int,
    max_side: int | None = DEFAULT_GRID_SIDE,
    gap: int = 0,
) -> tuple[int, int]:
    """Return a cell size that fits the grid inside ``max_side``.

    ``max_side`` is the longest side of the finished grid. A value of ``None``
    (or <= 0) means native source-pixel cells.
    """
    if rows < 1 or cols < 1:
        raise ValueError("rows and cols must be >= 1")
    if source_width < 1 or source_height < 1:
        raise ValueError("source dimensions must be >= 1")
    gap = max(0, int(gap))
    if max_side is None or max_side <= 0:
        return source_width, source_height

    max_side = int(max_side)
    available_w = max_side - (cols - 1) * gap
    available_h = max_side - (rows - 1) * gap
    if available_w < cols or available_h < rows:
        raise ValueError("gap is too large for the requested grid size")

    max_cell_w = available_w // cols
    max_cell_h = available_h // rows
    aspect = source_width / source_height

    if source_width >= source_height:
        cell_w = max_cell_w
        cell_h = max(1, round(cell_w / aspect))
        if cell_h > max_cell_h:
            cell_h = max_cell_h
            cell_w = max(1, round(cell_h * aspect))
    else:
        cell_h = max_cell_h
        cell_w = max(1, round(cell_h * aspect))
        if cell_w > max_cell_w:
            cell_w = max_cell_w
            cell_h = max(1, round(cell_w / aspect))

    cell_w = max(1, min(cell_w, max_cell_w))
    cell_h = max(1, min(cell_h, max_cell_h))
    return cell_w, cell_h


def _resize_rgb(frame: np.ndarray, cell_w: int, cell_h: int) -> np.ndarray:
    if frame.shape[1] == cell_w and frame.shape[0] == cell_h:
        return frame
    interpolation = cv2.INTER_AREA if frame.shape[1] > cell_w or frame.shape[0] > cell_h else cv2.INTER_LINEAR
    return cv2.resize(frame, (cell_w, cell_h), interpolation=interpolation)


def _draw_frame_label(
    image: np.ndarray,
    x: int,
    y: int,
    cell_w: int,
    cell_h: int,
    frame_num: int,
):
    text = f"{frame_num + 1}"
    scale = max(0.35, min(1.1, cell_h / 360.0))
    thickness = max(1, int(round(scale * 2)))
    (text_w, text_h), baseline = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness
    )
    pad = max(2, cell_h // 80)
    left = x + pad
    bottom = y + cell_h - pad
    top = max(y, bottom - text_h - baseline - pad)
    right = min(x + cell_w, left + text_w + pad)
    cv2.rectangle(image, (left, top), (right, bottom), (0, 0, 0), -1)
    cv2.putText(
        image,
        text,
        (left + pad // 2, bottom - baseline - pad // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def render_part(
    part: GridPart,
    frame_source,
    options: GridRenderOptions | None = None,
    cell_size: tuple[int, int] | None = None,
    frame_callback=None,
) -> np.ndarray:
    """Render one grid part into an RGB numpy array.

    ``frame_source`` is any object with ``width``, ``height`` and
    ``read(frame_num) -> RGB array``. Frames must be requested in ascending
    order (the planner guarantees that), so a video source can skip with
    ``grab()`` instead of reopening the file for every cell.

    ``frame_callback``, when supplied, is called as
    ``frame_callback(frame_num, rgb_frame)`` for each source frame before it is
    resized. It lets the exporter write individual frames without reading the
    video twice.
    """
    options = options or GridRenderOptions()
    expected = part.rows * part.cols
    if len(part.frames) != expected:
        raise ValueError(
            f"part {part.part} has {len(part.frames)} frames for {expected} cells"
        )

    if cell_size is None:
        cell_size = compute_cell_size(
            part.rows,
            part.cols,
            frame_source.width,
            frame_source.height,
            options.max_side,
            options.gap,
        )
    cell_w, cell_h = cell_size
    gap = max(0, int(options.gap))
    grid_w = part.cols * cell_w + (part.cols - 1) * gap
    grid_h = part.rows * cell_h + (part.rows - 1) * gap

    image = np.empty((grid_h, grid_w, 3), dtype=np.uint8)
    image[:] = options.background

    for cell_index, frame_num in enumerate(part.frames):
        row = cell_index // part.cols
        col = cell_index % part.cols
        x = col * (cell_w + gap)
        y = row * (cell_h + gap)
        try:
            frame = frame_source.read(frame_num)
        except FrameReadError:
            raise
        except Exception as exc:
            raise FrameReadError(frame_num, str(exc)) from exc
        if frame_callback is not None:
            frame_callback(frame_num, frame)
        image[y:y + cell_h, x:x + cell_w] = _resize_rgb(frame, cell_w, cell_h)
        if options.burn_frame_numbers:
            _draw_frame_label(image, x, y, cell_w, cell_h, frame_num)

    return image


def compose_grid(
    images: Iterable[np.ndarray | None],
    rows: int,
    cols: int,
    gap: int = 0,
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
    cell_size: tuple[int, int] | None = None,
    burn_labels: Sequence[int] | None = None,
) -> np.ndarray:
    """Compose images row by row, padding missing cells with ``background``.

    This is the shared contact-sheet composer used by WAN preparation. It is
    intentionally more forgiving than :func:`render_part`: ``None`` entries
    become empty background cells.
    """
    if rows < 1 or cols < 1:
        raise ValueError("rows and cols must be >= 1")
    images = list(images)
    provided = [img for img in images if img is not None]
    if not provided:
        raise ValueError("at least one image is required")

    if cell_size is None:
        cell_h, cell_w = provided[0].shape[:2]
    else:
        cell_w, cell_h = cell_size
    gap = max(0, int(gap))
    grid_w = cols * cell_w + (cols - 1) * gap
    grid_h = rows * cell_h + (rows - 1) * gap
    output = np.empty((grid_h, grid_w, 3), dtype=np.uint8)
    output[:] = background

    for index in range(rows * cols):
        image = images[index] if index < len(images) else None
        if image is None:
            continue
        row = index // cols
        col = index % cols
        x = col * (cell_w + gap)
        y = row * (cell_h + gap)
        output[y:y + cell_h, x:x + cell_w] = _resize_rgb(
            _as_rgb_array(image), cell_w, cell_h
        )
        if burn_labels and index < len(burn_labels):
            _draw_frame_label(
                output, x, y, cell_w, cell_h, int(burn_labels[index])
            )
    return output


def write_rgb_image(
    path: str,
    rgb: np.ndarray,
    format_name: str = "PNG",
    jpeg_quality: int = 95,
):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    params = []
    if format_name == "JPEG":
        params = [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)]
    elif format_name == "PNG":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 1]
    if not cv2.imwrite(path, bgr, params):
        raise ValueError(f"Failed to save image: {path}")
