import os
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, List
from PIL import Image
import glob


class PlayerEngine:
    def __init__(self):
        self.current_path: str = ""
        self.cap: Optional[cv2.VideoCapture] = None
        self.frame_count: int = 0
        self.fps: float = 24.0
        self.width: int = 0
        self.height: int = 0
        self.is_sequence: bool = False
        self.is_gif: bool = False
        self.gif_frames: List[np.ndarray] = []
        self.sequence_files: List[str] = []
        self.padding: int = 4
        self.start_index: int = 1
        self._current_frame_idx: int = 0

    def load_video(self, path: str) -> bool:
        self.unload()
        self.current_path = path

        if not os.path.exists(path):
            return False

        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            self.cap = None
            return False

        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.is_sequence = False
        self.is_gif = False

        return True

    def load_gif(self, path: str) -> bool:
        self.unload()
        self.current_path = path

        if not os.path.exists(path):
            return False

        try:
            gif = Image.open(path)
            self.gif_frames = []

            while True:
                # Convert to RGB and then to numpy array in BGR format for consistency with OpenCV
                frame = gif.convert("RGB")
                frame_np = np.array(frame)
                frame_bgr = cv2.cvtColor(frame_np, cv2.COLOR_RGB2BGR)
                self.gif_frames.append(frame_bgr)

                try:
                    gif.seek(gif.tell() + 1)
                except EOFError:
                    break

            self.frame_count = len(self.gif_frames)

            # Get GIF duration for FPS calculation
            gif.seek(0)
            duration = gif.info.get(
                "duration", 100
            )  # Default 100ms per frame if not specified
            self.fps = 1000 / duration if duration > 0 else 24.0

            if self.frame_count > 0:
                self.height, self.width = self.gif_frames[0].shape[:2]

            self.is_gif = True
            self.is_sequence = False
            return True
        except Exception:
            return False

    def load_sequence(self, path: str, start_index: int = 1, padding: int = 4) -> bool:
        self.unload()
        self.current_path = path
        self.padding = padding
        self.start_index = start_index

        directory = os.path.dirname(path)
        basename = os.path.basename(path)
        pattern = basename.replace(f"{start_index:0{padding}d}", f"*{'0' * padding}d")
        pattern = pattern.replace("[", "[").replace("]", "]")

        search_pattern = os.path.join(directory, pattern.replace("*", "*"))

        base_name = (
            basename.rsplit("_", 1)[0]
            if "_" in basename
            else basename.rsplit(".", 1)[0]
        )
        ext = os.path.splitext(basename)[1]

        if not os.path.isdir(directory):
            return False

        files = sorted(glob.glob(os.path.join(directory, f"{base_name}*{ext}")))

        if not files:
            files = sorted(glob.glob(os.path.join(directory, "*" + ext)))

        if not files:
            return False

        self.sequence_files = files
        self.frame_count = len(files)

        first_frame = self._load_sequence_frame(0)
        if first_frame is not None:
            self.height, self.width = first_frame.shape[:2]

        self.is_sequence = True
        self._current_frame_idx = 0

        img = first_frame
        if img is not None:
            self.height, self.width = img.shape[:2]

        return True

    def _load_sequence_frame(self, index: int) -> Optional[np.ndarray]:
        if index < 0 or index >= len(self.sequence_files):
            return None

        img_path = self.sequence_files[index]
        img = cv2.imread(img_path)
        return img

    def load(self, path: str, start_index: int = 1, padding: int = 4) -> bool:
        if os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in [".mp4", ".avi", ".mov", ".mkv", ".webm"]:
                return self.load_video(path)
            elif ext == ".gif":
                return self.load_gif(path)
            elif ext in [".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tiff"]:
                directory = os.path.dirname(path)
                base_name = os.path.basename(path)
                ext = os.path.splitext(base_name)[1]

                seq_files = sorted(glob.glob(os.path.join(directory, f"*{ext}")))
                if len(seq_files) > 1:
                    for f in seq_files:
                        if os.path.basename(f) == base_name:
                            idx = seq_files.index(f)
                            return self.load_sequence(
                                path, start_index=idx + 1, padding=padding
                            )

                if len(seq_files) == 1:
                    return self.load_sequence(path, start_index=1, padding=padding)

        if os.path.isfile(path):
            return self.load_video(path)

        if os.path.isdir(path):
            return self.load_sequence(path, start_index, padding)

        return False

    def get_frame(self, index: int) -> Optional[np.ndarray]:
        if self.is_sequence:
            if 0 <= index < self.frame_count:
                return self._load_sequence_frame(index)
            return None

        if self.is_gif:
            if 0 <= index < len(self.gif_frames):
                return self.gif_frames[index].copy()
            return None

        if self.cap is None:
            return None

        if index < 0 or index >= self.frame_count:
            return None

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ret, frame = self.cap.read()

        if ret:
            return frame
        return None

    def get_frame_rgb(self, index: int) -> Optional[np.ndarray]:
        frame = self.get_frame(index)
        if frame is not None:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return None

    def unload(self):
        if self.cap:
            self.cap.release()
            self.cap = None
        self.current_path = ""
        self.frame_count = 0
        self.fps = 0
        self.width = 0
        self.height = 0
        self.is_sequence = False
        self.is_gif = False
        self.gif_frames = []
        self.sequence_files = []
        self._current_frame_idx = 0

    def is_loaded(self) -> bool:
        return bool(self.cap or self.is_sequence or self.is_gif)

    @property
    def current_index(self) -> int:
        return self._current_frame_idx

    @current_index.setter
    def current_index(self, value: int):
        self._current_frame_idx = max(0, min(value, self.frame_count - 1))
