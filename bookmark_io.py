"""Bookmark location/timestamp export and cross-clip import (no Qt)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import io
import json
import math
import os
import re
from typing import Any, Iterable

from gemma_shot_detection import frame_to_timestamp, seconds_to_timestamp


BOOKMARK_EXPORT_FORMAT_VERSION = "1.0"
BOOKMARK_EXPORT_SCHEMA_ID = "kfplayer_bookmarks"
DEFAULT_BOOKMARK_COLOR = "#ff6b35"
SHOT_BOOKMARK_COLOR = "#00a8ff"
BOOKMARK_IMPORT_FILTER = (
    "Bookmark Files (*.json *.csv *.kfp_basic);;"
    "JSON Files (*.json);;"
    "CSV Files (*.csv);;"
    "KFPlayer Project (*.kfp_basic);;"
    "All Files (*)"
)

CSV_FIELDNAMES = (
    "frame",
    "frame_1based",
    "timestamp",
    "timecode",
    "seconds",
    "fps",
    "name",
    "color",
)

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")
_NUMERIC_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_TIMECODE_RE = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2})[:;](\d{1,3})$")
_HMS_RE = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")
_MS_RE = re.compile(r"^(\d+):(\d{1,2}(?:\.\d+)?)$")


class PositionMode(str, Enum):
    FRAME = "frame"
    TIMESTAMP = "timestamp"


class OutOfRangePolicy(str, Enum):
    SKIP = "skip"
    CLAMP = "clamp"


class CollisionPolicy(str, Enum):
    KEEP_EXISTING = "keep_existing"
    OVERWRITE = "overwrite"
    REPLACE_ALL = "replace_all"


class StartAnchorMode(str, Enum):
    ORIGINAL = "original"
    FIRST_BOOKMARK = "first_bookmark"
    CLIP_START = "clip_start"


@dataclass(frozen=True)
class BookmarkRecord:
    frame: int | None
    seconds: float | None
    timestamp: str
    timecode: str
    fps: float | None
    name: str
    color: str = DEFAULT_BOOKMARK_COLOR


@dataclass(frozen=True)
class BookmarkImportDocument:
    bookmarks: list[BookmarkRecord]
    source_name: str = ""
    source_fps: float | None = None
    source_total_frames: int | None = None
    detected_format: str = "json"


@dataclass(frozen=True)
class ImportPreviewItem:
    record: BookmarkRecord
    target_frame: int | None
    target_timestamp: str
    status: str
    reason: str


@dataclass(frozen=True)
class BookmarkImportPlan:
    items: list[ImportPreviewItem]
    final_bookmarks: list[dict[str, Any]]
    imported_count: int
    overwritten_count: int
    clamped_count: int
    skipped_count: int


def normalize_fps(fps: Any, default: float = 24.0) -> float:
    """Return a positive finite FPS value, falling back to default."""
    try:
        value = float(fps)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value) or value <= 0:
        return default
    return value


def _try_parse_fps(fps: Any) -> float | None:
    try:
        value = float(fps)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _try_parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value)) if math.isfinite(value) else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            parsed = float(text)
        except ValueError:
            return None
        return int(round(parsed)) if math.isfinite(parsed) else None


def _try_parse_nonneg_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def normalize_bookmark_color(color: Any, default: str = DEFAULT_BOOKMARK_COLOR) -> str:
    text = str(color or "").strip()
    if _HEX_COLOR_RE.fullmatch(text):
        return text
    return default


def frame_to_timecode(frame: int, fps: float) -> str:
    """Format a 0-based frame index as SMPTE-style HH:MM:SS:FF."""
    nominal_fps = max(1, int(round(normalize_fps(fps))))
    safe_frame = max(0, int(frame))
    total_seconds = safe_frame // nominal_fps
    ff = safe_frame % nominal_fps
    hh = total_seconds // 3600
    mm = (total_seconds % 3600) // 60
    ss = total_seconds % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def parse_timestamp_to_seconds(value: Any, fallback_fps: float | None = None) -> float | None:
    """Parse numeric seconds, HH:MM:SS.mmm, MM:SS.mmm, or HH:MM:SS:FF into seconds."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        return num if math.isfinite(num) and num >= 0 else None

    text = str(value).strip()
    if not text:
        return None

    if _NUMERIC_RE.fullmatch(text):
        num = float(text)
        return num if math.isfinite(num) and num >= 0 else None

    normalized = text.replace(",", ".")

    tc_match = _TIMECODE_RE.fullmatch(normalized)
    if tc_match:
        h, m, s, ff = (int(group) for group in tc_match.groups())
        fps_tc = normalize_fps(fallback_fps)
        return (h * 3600) + (m * 60) + s + (ff / fps_tc)

    hms_match = _HMS_RE.fullmatch(normalized)
    if hms_match:
        h = int(hms_match.group(1))
        m = int(hms_match.group(2))
        s = float(hms_match.group(3))
        return (h * 3600) + (m * 60) + s

    ms_match = _MS_RE.fullmatch(normalized)
    if ms_match:
        m = int(ms_match.group(1))
        s = float(ms_match.group(2))
        return (m * 60) + s

    return None


def _normalize_export_bookmarks(
    bookmarks: Iterable[dict[str, Any]],
    fps: float,
) -> list[dict[str, Any]]:
    safe_fps = normalize_fps(fps)
    entries: list[dict[str, Any]] = []
    for raw in bookmarks or []:
        if not isinstance(raw, dict):
            continue
        frame = _try_parse_int(raw.get("frame"))
        if frame is None or frame < 0:
            continue
        raw_name = str(raw.get("name") or "").strip()
        entries.append(
            {
                "frame": frame,
                "raw_name": raw_name,
                "color": normalize_bookmark_color(raw.get("color")),
            }
        )

    entries.sort(key=lambda item: (item["frame"], item["raw_name"]))
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        frame = entry["frame"]
        seconds = round(frame / safe_fps, 6)
        normalized.append(
            {
                "frame": frame,
                "frame_1based": frame + 1,
                "seconds": seconds,
                "timestamp": frame_to_timestamp(frame, safe_fps),
                "timecode": frame_to_timecode(frame, safe_fps),
                "name": entry["raw_name"] or f"Bookmark {index}",
                "color": entry["color"],
            }
        )
    return normalized


def build_bookmark_export_payload(
    bookmarks: Iterable[dict[str, Any]],
    fps: float,
    source_name: str = "",
    total_frames: int = 0,
) -> dict[str, Any]:
    """Build the canonical JSON export payload for bookmarks."""
    safe_fps = normalize_fps(fps)
    return {
        "format": BOOKMARK_EXPORT_SCHEMA_ID,
        "version": BOOKMARK_EXPORT_FORMAT_VERSION,
        "source_name": str(source_name or ""),
        "fps": round(safe_fps, 6),
        "total_frames": max(0, _try_parse_int(total_frames) or 0),
        "exported_utc": datetime.now(timezone.utc).isoformat(),
        "bookmarks": _normalize_export_bookmarks(bookmarks, safe_fps),
    }


def export_bookmarks_json(
    filepath: str,
    bookmarks: Iterable[dict[str, Any]],
    fps: float,
    source_name: str = "",
    total_frames: int = 0,
) -> str:
    """Write bookmarks with frame locations and timestamps to a JSON file."""
    payload = build_bookmark_export_payload(
        bookmarks,
        fps=fps,
        source_name=source_name,
        total_frames=total_frames,
    )
    parent = os.path.dirname(filepath)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return filepath


def export_bookmarks_csv(
    filepath: str,
    bookmarks: Iterable[dict[str, Any]],
    fps: float,
    source_name: str = "",
    total_frames: int = 0,
) -> str:
    """Write bookmarks with frame locations and timestamps to a CSV file."""
    del source_name, total_frames  # flat CSV rows carry per-row fps directly
    safe_fps = round(normalize_fps(fps), 6)
    rows = _normalize_export_bookmarks(bookmarks, safe_fps)
    parent = os.path.dirname(filepath)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(filepath, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "fps": safe_fps})
    return filepath


def export_bookmarks_file(
    filepath: str,
    bookmarks: Iterable[dict[str, Any]],
    fps: float,
    format_name: str | None = None,
    source_name: str = "",
    total_frames: int = 0,
) -> str:
    """Export bookmarks as JSON or CSV based on format_name or file extension."""
    resolved_format = (format_name or "").strip().lower()
    if resolved_format not in {"json", "csv"}:
        ext = os.path.splitext(filepath)[1].lower()
        resolved_format = "csv" if ext == ".csv" else "json"

    if resolved_format == "csv":
        return export_bookmarks_csv(
            filepath,
            bookmarks,
            fps=fps,
            source_name=source_name,
            total_frames=total_frames,
        )
    return export_bookmarks_json(
        filepath,
        bookmarks,
        fps=fps,
        source_name=source_name,
        total_frames=total_frames,
    )


def _record_from_mapping(
    mapping: dict[str, Any],
    index: int,
    default_fps: float | None = None,
    default_color: str = DEFAULT_BOOKMARK_COLOR,
) -> BookmarkRecord | None:
    row_fps = _try_parse_fps(mapping.get("fps")) or default_fps

    frame = _try_parse_int(mapping.get("frame"))
    if frame is None:
        frame = _try_parse_int(mapping.get("start_frame"))
    if frame is None:
        frame = _try_parse_int(mapping.get("frame_0based"))
    if frame is None:
        frame_1based = _try_parse_int(mapping.get("frame_1based"))
        if frame_1based is None:
            frame_1based = _try_parse_int(mapping.get("frame_number"))
        if frame_1based is not None:
            frame = frame_1based - 1
    if frame is not None and frame < 0:
        frame = None

    seconds = _try_parse_nonneg_float(mapping.get("seconds"))
    if seconds is None:
        seconds = _try_parse_nonneg_float(mapping.get("start_seconds"))
    if seconds is None:
        seconds = parse_timestamp_to_seconds(mapping.get("time"), fallback_fps=row_fps)

    timestamp_raw = str(
        mapping.get("timestamp") or mapping.get("start_timestamp") or ""
    ).strip()
    timecode_raw = str(mapping.get("timecode") or "").strip()

    if seconds is None and timestamp_raw:
        seconds = parse_timestamp_to_seconds(timestamp_raw, fallback_fps=row_fps)
    if seconds is None and timecode_raw:
        seconds = parse_timestamp_to_seconds(timecode_raw, fallback_fps=row_fps)
    if seconds is None and frame is not None and row_fps is not None:
        seconds = frame / row_fps

    if frame is None and seconds is None:
        return None

    timestamp = timestamp_raw or (
        seconds_to_timestamp(seconds) if seconds is not None else ""
    )
    timecode = timecode_raw or (
        frame_to_timecode(frame, row_fps)
        if frame is not None and row_fps is not None
        else ""
    )

    name = str(
        mapping.get("name")
        or mapping.get("label")
        or mapping.get("description")
        or mapping.get("title")
        or ""
    ).strip()
    if not name:
        shot_idx = _try_parse_int(mapping.get("index"))
        name = f"Shot {shot_idx:03d}" if shot_idx is not None else f"Bookmark {index}"

    color = normalize_bookmark_color(mapping.get("color"), default=default_color)
    return BookmarkRecord(
        frame=frame,
        seconds=seconds,
        timestamp=timestamp,
        timecode=timecode,
        fps=row_fps,
        name=name,
        color=color,
    )


def _load_bookmarks_from_json(raw_text: str) -> BookmarkImportDocument:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON bookmark file: {exc}") from exc

    source_name = ""
    source_fps: float | None = None
    source_total_frames: int | None = None
    detected_format = "json"
    default_color = DEFAULT_BOOKMARK_COLOR

    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict):
        source_name = str(data.get("source_name") or data.get("name") or "")
        settings = data.get("settings")
        if isinstance(settings, dict) and source_fps is None:
            source_fps = _try_parse_fps(settings.get("fps"))
        source_fps = _try_parse_fps(data.get("fps")) or source_fps
        source_total_frames = _try_parse_int(data.get("total_frames"))

        if isinstance(data.get("bookmarks"), list):
            raw_items = data["bookmarks"]
            if "timeline" in data and "sources" in data and data.get("format") != BOOKMARK_EXPORT_SCHEMA_ID:
                detected_format = "kfp_basic"
        elif isinstance(data.get("shots"), list):
            raw_items = data["shots"]
            detected_format = "gemma_shots"
            default_color = SHOT_BOOKMARK_COLOR
        else:
            raise ValueError(
                "Unsupported JSON file: expected a 'bookmarks' or 'shots' list."
            )
    else:
        raise ValueError("Unsupported JSON file: expected an object or array.")

    records: list[BookmarkRecord] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        record = _record_from_mapping(
            item,
            index=index,
            default_fps=source_fps,
            default_color=default_color,
        )
        if record is not None:
            records.append(record)

    return BookmarkImportDocument(
        bookmarks=records,
        source_name=source_name,
        source_fps=source_fps,
        source_total_frames=source_total_frames,
        detected_format=detected_format,
    )


def _load_bookmarks_from_csv(raw_text: str) -> BookmarkImportDocument:
    reader = csv.DictReader(io.StringIO(raw_text))
    if not reader.fieldnames:
        raise ValueError("CSV file has no header row.")

    records: list[BookmarkRecord] = []
    inferred_fps: float | None = None

    for index, raw_row in enumerate(reader, start=1):
        if not raw_row:
            continue
        lowered = {
            str(key).strip().lower(): (value.strip() if isinstance(value, str) else value)
            for key, value in raw_row.items()
            if key is not None
        }
        if not any(val not in (None, "") for val in lowered.values()):
            continue

        row_fps = _try_parse_fps(lowered.get("fps"))
        if inferred_fps is None and row_fps is not None:
            inferred_fps = row_fps

        record = _record_from_mapping(
            lowered,
            index=index,
            default_fps=row_fps,
        )
        if record is not None:
            records.append(record)

    return BookmarkImportDocument(
        bookmarks=records,
        source_fps=inferred_fps,
        detected_format="csv",
    )


def load_bookmarks_file(filepath: str) -> BookmarkImportDocument:
    """Load bookmark locations/timestamps from JSON, CSV, or .kfp_basic files."""
    with open(filepath, "r", encoding="utf-8-sig") as handle:
        raw_text = handle.read()

    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".csv":
        return _load_bookmarks_from_csv(raw_text)
    if ext in {".json", ".kfp_basic"}:
        return _load_bookmarks_from_json(raw_text)

    stripped = raw_text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _load_bookmarks_from_json(raw_text)
    return _load_bookmarks_from_csv(raw_text)


def recommend_position_mode(
    document: BookmarkImportDocument,
    target_fps: float,
) -> PositionMode:
    """Pick TIMESTAMP when FPS differs or frames are absent, else FRAME."""
    safe_target_fps = normalize_fps(target_fps)
    has_any_time = any(bm.seconds is not None or bm.timestamp for bm in document.bookmarks)
    has_missing_frame = any(bm.frame is None for bm in document.bookmarks)

    if has_missing_frame and has_any_time:
        return PositionMode.TIMESTAMP
    if (
        document.source_fps is not None
        and abs(document.source_fps - safe_target_fps) > 0.05
        and has_any_time
    ):
        return PositionMode.TIMESTAMP
    return PositionMode.FRAME


def _resolve_record_seconds(
    record: BookmarkRecord,
    document: BookmarkImportDocument,
    target_fps: float,
) -> float | None:
    seconds = record.seconds
    if seconds is None and record.timestamp:
        seconds = parse_timestamp_to_seconds(
            record.timestamp,
            fallback_fps=record.fps or document.source_fps or target_fps,
        )
    if seconds is None and record.timecode:
        seconds = parse_timestamp_to_seconds(
            record.timecode,
            fallback_fps=record.fps or document.source_fps or target_fps,
        )
    if seconds is None and record.frame is not None:
        src_fps = record.fps or document.source_fps or target_fps
        seconds = record.frame / normalize_fps(src_fps, default=target_fps)
    return seconds


def _resolve_base_position(
    record: BookmarkRecord,
    document: BookmarkImportDocument,
    target_fps: float,
    position_mode: PositionMode,
) -> tuple[int | None, float | None]:
    """Return (base_frame, base_seconds) for a record under position_mode."""
    seconds = _resolve_record_seconds(record, document, target_fps)
    if position_mode == PositionMode.FRAME:
        if record.frame is not None:
            return record.frame, seconds
        if seconds is not None:
            return int(round(seconds * target_fps)), seconds
        return None, None
    return (int(round(seconds * target_fps)) if seconds is not None else None), seconds


def plan_bookmark_import(
    document: BookmarkImportDocument,
    existing_bookmarks: Iterable[dict[str, Any]],
    target_total_frames: int,
    target_fps: float,
    position_mode: PositionMode = PositionMode.FRAME,
    out_of_range: OutOfRangePolicy = OutOfRangePolicy.SKIP,
    collision_policy: CollisionPolicy = CollisionPolicy.KEEP_EXISTING,
    start_frame: int | None = None,
    start_anchor: StartAnchorMode = StartAnchorMode.FIRST_BOOKMARK,
) -> BookmarkImportPlan:
    """Resolve imported bookmarks against a target clip without mutating inputs."""
    safe_target_fps = normalize_fps(target_fps)
    max_frame = target_total_frames - 1

    working_by_frame: dict[int, dict[str, Any]] = {}
    if collision_policy != CollisionPolicy.REPLACE_ALL:
        for bm in existing_bookmarks or []:
            if not isinstance(bm, dict):
                continue
            frame = _try_parse_int(bm.get("frame"))
            if frame is not None and frame >= 0:
                working_by_frame[frame] = dict(bm)

    existing_frames = set(working_by_frame.keys())
    imported_seen_frames: set[int] = set()

    base_positions = [
        _resolve_base_position(record, document, safe_target_fps, position_mode)
        for record in document.bookmarks
    ]
    apply_shift = start_frame is not None and start_anchor != StartAnchorMode.ORIGINAL
    anchor_target = int(start_frame) if apply_shift else 0
    earliest_frame = 0
    earliest_seconds = 0.0
    if apply_shift and start_anchor == StartAnchorMode.FIRST_BOOKMARK:
        if position_mode == PositionMode.FRAME:
            valid_frames = [f for f, _ in base_positions if f is not None]
            if valid_frames:
                earliest_frame = min(valid_frames)
        else:
            valid_seconds = [s for _, s in base_positions if s is not None]
            if valid_seconds:
                earliest_seconds = min(valid_seconds)

    items: list[ImportPreviewItem] = []
    imported_count = 0
    overwritten_count = 0
    clamped_count = 0
    skipped_count = 0

    for record, (base_frame, base_seconds) in zip(document.bookmarks, base_positions):
        if target_total_frames <= 0:
            skipped_count += 1
            items.append(
                ImportPreviewItem(
                    record=record,
                    target_frame=None,
                    target_timestamp="",
                    status="skip_out_of_range",
                    reason="Target clip has no frames",
                )
            )
            continue

        if position_mode == PositionMode.FRAME:
            if base_frame is None:
                resolved = None
            elif apply_shift:
                resolved = anchor_target + (base_frame - earliest_frame)
            else:
                resolved = base_frame
        else:
            if base_seconds is None:
                resolved = None
            elif apply_shift:
                resolved = anchor_target + int(
                    round((base_seconds - earliest_seconds) * safe_target_fps)
                )
            else:
                resolved = int(round(base_seconds * safe_target_fps))

        if resolved is None:
            skipped_count += 1
            items.append(
                ImportPreviewItem(
                    record=record,
                    target_frame=None,
                    target_timestamp="",
                    status="skip_unresolvable",
                    reason="No frame or timestamp available",
                )
            )
            continue

        was_clamped = False
        if resolved < 0 or resolved > max_frame:
            if out_of_range == OutOfRangePolicy.SKIP:
                skipped_count += 1
                items.append(
                    ImportPreviewItem(
                        record=record,
                        target_frame=resolved,
                        target_timestamp=frame_to_timestamp(max(0, resolved), safe_target_fps),
                        status="skip_out_of_range",
                        reason=f"Frame {resolved + 1} is outside 1..{target_total_frames}",
                    )
                )
                continue
            resolved = max(0, min(max_frame, resolved))
            was_clamped = True

        target_ts = frame_to_timestamp(resolved, safe_target_fps)

        if resolved in imported_seen_frames:
            skipped_count += 1
            items.append(
                ImportPreviewItem(
                    record=record,
                    target_frame=resolved,
                    target_timestamp=target_ts,
                    status="skip_duplicate",
                    reason=f"Another imported bookmark already maps to frame {resolved + 1}",
                )
            )
            continue

        new_entry = {
            "frame": resolved,
            "name": record.name,
            "color": record.color,
        }

        if resolved in existing_frames:
            if collision_policy == CollisionPolicy.KEEP_EXISTING:
                skipped_count += 1
                items.append(
                    ImportPreviewItem(
                        record=record,
                        target_frame=resolved,
                        target_timestamp=target_ts,
                        status="skip_existing",
                        reason=f"Frame {resolved + 1} already has a bookmark",
                    )
                )
                continue
            working_by_frame[resolved] = new_entry
            imported_seen_frames.add(resolved)
            overwritten_count += 1
            if was_clamped:
                clamped_count += 1
            items.append(
                ImportPreviewItem(
                    record=record,
                    target_frame=resolved,
                    target_timestamp=target_ts,
                    status="overwrite",
                    reason=(
                        f"Clamped to frame {resolved + 1} (overwrites existing)"
                        if was_clamped
                        else f"Overwrites existing bookmark at frame {resolved + 1}"
                    ),
                )
            )
            continue

        working_by_frame[resolved] = new_entry
        imported_seen_frames.add(resolved)
        imported_count += 1
        if was_clamped:
            clamped_count += 1
            items.append(
                ImportPreviewItem(
                    record=record,
                    target_frame=resolved,
                    target_timestamp=target_ts,
                    status="clamped",
                    reason=f"Clamped to frame {resolved + 1}",
                )
            )
        else:
            items.append(
                ImportPreviewItem(
                    record=record,
                    target_frame=resolved,
                    target_timestamp=target_ts,
                    status="import",
                    reason=f"Maps to frame {resolved + 1}",
                )
            )

    final_bookmarks = sorted(
        working_by_frame.values(),
        key=lambda bm: (bm["frame"], bm.get("name", "")),
    )

    return BookmarkImportPlan(
        items=items,
        final_bookmarks=final_bookmarks,
        imported_count=imported_count,
        overwritten_count=overwritten_count,
        clamped_count=clamped_count,
        skipped_count=skipped_count,
    )
