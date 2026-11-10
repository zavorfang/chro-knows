"""Shot-grid export pipeline (no Qt).

The dialog and the tests both call the same functions here, so the preview and
the files on disk cannot drift apart.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable

from app_utils import (
    IMAGE_EXPORT_FORMATS,
    build_shot_grid_filename,
    sanitize_filename_part,
)
from shot_grid import (
    DEFAULT_INTERVAL,
    DEFAULT_MAX_DIM,
    DEFAULT_MAX_RATIO,
    FitStrategy,
    Shot,
    ShotGridPlan,
    plan_shot,
    shots_from_bookmarks,
)
from shot_grid_render import (
    DEFAULT_GRID_SIDE,
    FrameReadError,
    GridRenderOptions,
    ShotGridMedia,
    compute_cell_size,
    create_frame_reader,
    render_part,
    write_rgb_image,
)


ProgressCallback = Callable[[str, int, int], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class NamedShotPlan:
    shot: Shot
    plan: ShotGridPlan
    name: str


@dataclass(frozen=True)
class ShotGridExportOptions:
    output_folder: str
    prefix: str
    range_start: int = 0
    range_end: int = 0
    interval: int = DEFAULT_INTERVAL
    max_dim: int = DEFAULT_MAX_DIM
    rectangular: bool = False
    strategy: FitStrategy = FitStrategy.BALANCED
    max_ratio: float = DEFAULT_MAX_RATIO
    format_name: str = "PNG"
    jpeg_quality: int = 95
    grid_side: int | None = DEFAULT_GRID_SIDE
    gap: int = 0
    burn_frame_numbers: bool = False
    subfolder_per_shot: bool = False
    save_individual_frames: bool = False
    write_manifest: bool = True
    write_splitter_sidecars: bool = True
    include_shots: frozenset[int] | None = None

    @property
    def extension(self) -> str:
        return IMAGE_EXPORT_FORMATS[self.format_name]["extension"]

    @property
    def output_root(self) -> str:
        return os.path.join(
            self.output_folder,
            f"{sanitize_filename_part(self.prefix)}_shot_grids",
        )


@dataclass
class ShotGridExportResult:
    output_root: str
    manifest_path: str = ""
    image_paths: list[str] = field(default_factory=list)
    frame_paths: list[str] = field(default_factory=list)
    shot_count: int = 0
    image_count: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)


def _bookmark_name_map(bookmarks) -> dict[int, str]:
    names: dict[int, str] = {}
    for bookmark in bookmarks or []:
        if not isinstance(bookmark, dict):
            continue
        try:
            frame = int(bookmark.get("frame", -1))
        except (TypeError, ValueError):
            continue
        if frame < 0:
            continue
        name = str(bookmark.get("name") or "").strip()
        if frame not in names or (name and not names[frame]):
            names[frame] = name
    return names


def build_shot_plans(
    bookmarks,
    range_end: int,
    options: ShotGridExportOptions,
    range_start: int = 0,
    include_lead_in: bool = True,
) -> list[NamedShotPlan]:
    """Build plans for the range, in time order.

    The lead-in row is returned when it exists; callers decide whether to export
    it by checking its box. Frames before the first bookmark are never included
    silently.
    """
    if range_end < range_start:
        return []
    frames = []
    for bookmark in bookmarks or []:
        if not isinstance(bookmark, dict):
            continue
        try:
            frames.append(int(bookmark.get("frame", -1)))
        except (TypeError, ValueError):
            continue
    shots = shots_from_bookmarks(
        frames,
        clip_end=range_end,
        clip_start=range_start,
        include_lead_in=include_lead_in,
    )
    names = _bookmark_name_map(bookmarks)
    plans: list[NamedShotPlan] = []
    for shot in shots:
        if shot.length < 1:
            continue
        name = names.get(shot.start) or (
            "Lead-in" if shot.index == 0 else f"Shot {shot.index:03d}"
        )
        plan = plan_shot(
            shot,
            interval=options.interval,
            max_dim=options.max_dim,
            rectangular=options.rectangular,
            strategy=options.strategy,
            max_ratio=options.max_ratio,
        )
        plans.append(NamedShotPlan(shot, plan, name))
    return plans


def plan_summary(plans: Iterable[NamedShotPlan], included: set[int] | None = None) -> dict:
    selected = [p for p in plans if included is None or p.shot.index in included]
    image_count = sum(len(p.plan.parts) for p in selected)
    empty_cells = sum(p.plan.empty_cells for p in selected)
    short_shots = [
        p for p in selected
        if p.shot.length <= 1 or p.shot.length < p.plan.interval
    ]
    return {
        "shots": len(selected),
        "images": image_count,
        "empty_cells": empty_cells,
        "short_shots": short_shots,
    }


def _sidecar_path(image_path: str) -> str:
    return os.path.splitext(image_path)[0] + ".json"


def _write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)


def _save_individual_frame(
    frame_rgb,
    path: str,
    format_name: str,
    jpeg_quality: int,
):
    write_rgb_image(path, frame_rgb, format_name, jpeg_quality)


def export_shot_grids(
    media: ShotGridMedia,
    bookmarks,
    options: ShotGridExportOptions,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> ShotGridExportResult:
    """Export one grid image per part, plus the manifest and sidecars."""
    cancel_check = cancel_check or (lambda: False)
    progress_callback = progress_callback or (lambda _message, _done, _total: None)
    result = ShotGridExportResult(output_root=options.output_root)
    os.makedirs(result.output_root, exist_ok=True)

    plans = build_shot_plans(
        bookmarks,
        range_end=options.range_end,
        options=options,
        range_start=options.range_start,
        include_lead_in=True,
    )
    if options.include_shots is not None:
        plans = [p for p in plans if p.shot.index in options.include_shots]

    total_images = sum(len(p.plan.parts) for p in plans)
    done_images = 0
    manifest_shots: list[dict] = []

    render_options = GridRenderOptions(
        max_side=options.grid_side,
        gap=options.gap,
        burn_frame_numbers=options.burn_frame_numbers,
    )

    reader = None
    try:
        reader = create_frame_reader(media)
        for plan_index, named in enumerate(plans, start=1):
            if cancel_check():
                result.cancelled = True
                break

            shot = named.shot
            plan = named.plan
            shot_dir = result.output_root
            if options.subfolder_per_shot:
                shot_dir = os.path.join(result.output_root, f"shot_{shot.index:03d}")
            os.makedirs(shot_dir, exist_ok=True)

            shot_entry = {
                "shot_index": shot.index,
                "name": named.name,
                "start_frame": shot.start,
                "end_frame": shot.end,
                "length": shot.length,
                "samples_at_interval": plan.samples_at_interval,
                "parts": len(plan.parts),
                "images": [],
            }
            if options.save_individual_frames:
                shot_entry["frame_files"] = []

            try:
                cell_size = None
                for part in plan.parts:
                    if cancel_check():
                        result.cancelled = True
                        break
                    if cell_size is None:
                        cell_size = compute_cell_size(
                            part.rows,
                            part.cols,
                            reader.width,
                            reader.height,
                            options.grid_side,
                            options.gap,
                        )

                    def on_frame(frame_num, frame_rgb, _shot=shot, _part=part):
                        if not options.save_individual_frames:
                            return
                        frame_name = (
                            f"{sanitize_filename_part(options.prefix)}_"
                            f"shot_{_shot.index:03d}_f{frame_num + 1:04d}_frame"
                            f"{options.extension}"
                        )
                        frame_path = os.path.join(shot_dir, frame_name)
                        _save_individual_frame(
                            frame_rgb, frame_path, options.format_name,
                            options.jpeg_quality,
                        )
                        result.frame_paths.append(frame_path)
                        shot_entry["frame_files"].append(
                            os.path.relpath(frame_path, result.output_root).replace(
                                os.sep, "/"
                            )
                        )

                    image = render_part(
                        part,
                        reader,
                        render_options,
                        cell_size=cell_size,
                        frame_callback=on_frame,
                    )
                    filename = build_shot_grid_filename(
                        options.prefix,
                        shot.index,
                        shot.start,
                        shot.end,
                        part.rows,
                        part.cols,
                        options.extension,
                        part=part.part,
                        total_parts=len(plan.parts),
                    )
                    image_path = os.path.join(shot_dir, filename)
                    write_rgb_image(
                        image_path,
                        image,
                        options.format_name,
                        options.jpeg_quality,
                    )
                    result.image_paths.append(image_path)
                    done_images += 1

                    relative_file = os.path.relpath(
                        image_path, result.output_root
                    ).replace(os.sep, "/")
                    image_entry = {
                        "part": part.part,
                        "file": relative_file,
                        "rows": part.rows,
                        "cols": part.cols,
                        "cell_width": cell_size[0],
                        "cell_height": cell_size[1],
                        "gap": options.gap,
                        "frames": list(part.frames),
                    }
                    shot_entry["images"].append(image_entry)

                    if options.write_splitter_sidecars:
                        _write_json(
                            _sidecar_path(image_path),
                            {
                                "source_name": media.source_name,
                                "grid_dim": max(part.rows, part.cols),
                                "grid_rows": part.rows,
                                "grid_cols": part.cols,
                                "grid_gap": options.gap,
                                "cell_width": cell_size[0],
                                "cell_height": cell_size[1],
                                "image_file": os.path.basename(image_path),
                                "shot_index": shot.index,
                                "part": part.part,
                                "video_start_frame_abs": 0,
                                "video_end_frame_abs": media.total_frames - 1,
                                "chunks": [
                                    {
                                        "chunk_index": 0,
                                        "video_start_frame_abs": 0,
                                        "video_end_frame_abs": media.total_frames - 1,
                                        "selected_frames_abs": list(part.frames),
                                    }
                                ],
                            },
                        )

                    progress_callback(
                        f"Shot {plan_index} of {len(plans)}: "
                        f"part {part.part} of {len(plan.parts)}",
                        done_images,
                        total_images,
                    )
                    if result.cancelled:
                        break

                if shot_entry["images"]:
                    manifest_shots.append(shot_entry)
                    result.shot_count += 1
            except FrameReadError as exc:
                message = f"Shot {shot.index} ({named.name}): {exc}"
                result.errors.append(message)
                if shot_entry["images"]:
                    shot_entry["error"] = message
                    manifest_shots.append(shot_entry)
                    result.shot_count += 1

            if result.cancelled:
                break
    except Exception as exc:
        result.errors.append(str(exc))
    finally:
        if reader is not None:
            reader.close()

    result.image_count = len(result.image_paths)

    if options.write_manifest:
        manifest = {
            "source_name": media.source_name,
            "fps": media.fps,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "settings": {
                "interval": options.interval,
                "max_grid": options.max_dim,
                "layout": "rectangles" if options.rectangular else "square",
                "strategy": FitStrategy(options.strategy).value,
                "max_ratio": options.max_ratio,
                "format": options.format_name,
                "jpeg_quality": options.jpeg_quality,
                "grid_side": options.grid_side,
                "gap": options.gap,
                "burn_frame_numbers": options.burn_frame_numbers,
                "subfolder_per_shot": options.subfolder_per_shot,
                "save_individual_frames": options.save_individual_frames,
            },
            "range": {
                "start_frame": options.range_start,
                "end_frame": options.range_end,
            },
            "cancelled": result.cancelled,
            "shots": manifest_shots,
        }
        result.manifest_path = os.path.join(
            result.output_root,
            f"{sanitize_filename_part(options.prefix)}_shot_grids.json",
        )
        _write_json(result.manifest_path, manifest)

    return result
