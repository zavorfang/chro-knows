import json
import uuid
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict


@dataclass
class FrameMetadata:
    pan_x: float = 0.0
    pan_y: float = 0.0
    zoom: float = 1.0
    hold: bool = False
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FrameMetadata':
        return cls(
            pan_x=data.get('pan_x', 0.0),
            pan_y=data.get('pan_y', 0.0),
            zoom=data.get('zoom', 1.0),
            hold=data.get('hold', False),
            note=data.get('note', '')
        )


@dataclass
class Bookmark:
    id: str = field(default_factory=lambda: f"bm_{uuid.uuid4().hex[:8]}")
    frame: int = 0
    type: str = "single"  # single or range
    label: str = ""
    color: str = "#4EC9B0"
    start_frame: Optional[int] = None
    end_frame: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Bookmark':
        return cls(
            id=data.get('id', f"bm_{uuid.uuid4().hex[:8]}"),
            frame=data.get('frame', 0),
            type=data.get('type', 'single'),
            label=data.get('label', ''),
            color=data.get('color', '#4EC9B0'),
            start_frame=data.get('start_frame'),
            end_frame=data.get('end_frame')
        )


@dataclass
class MediaSource:
    id: str = field(default_factory=lambda: f"src_{uuid.uuid4().hex[:8]}")
    path: str = ""
    type: str = "video"  # video or sequence
    in_frame: int = 0
    out_frame: int = 0
    trim_in: int = 0
    trim_out: int = 0
    start_index: int = 1
    end_index: int = 1
    padding: int = 4
    name: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = os.path.basename(self.path)

    @property
    def frame_count(self) -> int:
        return self.trim_out - self.trim_in + 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MediaSource':
        return cls(
            id=data.get('id', f"src_{uuid.uuid4().hex[:8]}"),
            path=data.get('path', ''),
            type=data.get('type', 'video'),
            in_frame=data.get('in_frame', 0),
            out_frame=data.get('out_frame', 0),
            trim_in=data.get('trim_in', 0),
            trim_out=data.get('trim_out', 0),
            start_index=data.get('start_index', 1),
            end_index=data.get('end_index', 1),
            padding=data.get('padding', 4),
            name=data.get('name', '')
        )


class Project:
    VERSION = "1.0"

    def __init__(self, name: str = "Untitled", fps: int = 24):
        self.name = name
        self.fps = fps
        self.sources: List[MediaSource] = []
        self.bookmarks: List[Bookmark] = []
        self.frame_data: Dict[int, FrameMetadata] = {}
        self.project_path: Optional[str] = None

    @property
    def total_frames(self) -> int:
        total = 0
        for src in self.sources:
            total += src.frame_count
        return total

    def get_source_at_frame(self, frame: int) -> tuple[Optional[MediaSource], int]:
        current = 0
        for src in self.sources:
            src_frames = src.frame_count
            if current <= frame < current + src_frames:
                local_frame = frame - current + src.trim_in
                return src, local_frame
            current += src_frames
        return None, 0

    def get_global_frame(self, source_id: str, local_frame: int) -> int:
        current = 0
        for src in self.sources:
            if src.id == source_id:
                return current + (local_frame - src.trim_in)
            current += src.frame_count
        return 0

    def add_source(self, source: MediaSource):
        if self.sources:
            source.in_frame = self.sources[-1].out_frame + 1
        source.out_frame = source.in_frame + source.frame_count - 1
        self.sources.append(source)

    def remove_source(self, source_id: str):
        self.sources = [s for s in self.sources if s.id != source_id]
        self.recalculate_frames()

    def recalculate_frames(self):
        current = 0
        for src in self.sources:
            src.in_frame = current
            src.out_frame = current + src.frame_count - 1
            current = src.out_frame + 1

    def add_bookmark(self, bookmark: Bookmark):
        self.bookmarks.append(bookmark)

    def remove_bookmark(self, bookmark_id: str):
        self.bookmarks = [b for b in self.bookmarks if b.id != bookmark_id]

    def get_frame_metadata(self, frame: int) -> FrameMetadata:
        if frame not in self.frame_data:
            self.frame_data[frame] = FrameMetadata()
        return self.frame_data[frame]

    def set_frame_metadata(self, frame: int, metadata: FrameMetadata):
        self.frame_data[frame] = metadata

    def save(self, path: Optional[str] = None):
        if path:
            self.project_path = path

        if not self.project_path:
            raise ValueError("No project path set")

        data = {
            "version": self.VERSION,
            "name": self.name,
            "fps": self.fps,
            "sources": [s.to_dict() for s in self.sources],
            "bookmarks": [b.to_dict() for b in self.bookmarks],
            "frame_data": {str(k): v.to_dict() for k, v in self.frame_data.items()}
        }

        with open(self.project_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> 'Project':
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        project = cls(name=data.get('name', 'Untitled'), fps=data.get('fps', 24))
        project.project_path = path
        project.sources = [MediaSource.from_dict(s) for s in data.get('sources', [])]
        project.bookmarks = [Bookmark.from_dict(b) for b in data.get('bookmarks', [])]
        project.frame_data = {
            int(k): FrameMetadata.from_dict(v) 
            for k, v in data.get('frame_data', {}).items()
        }

        return project

    def new_project(self, name: str, project_path: str):
        self.name = name
        self.project_path = project_path
        self.sources = []
        self.bookmarks = []
        self.frame_data = {}
