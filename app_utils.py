import json
import os
import re
import shutil
import subprocess
import tempfile


RECENT_FILES_LIMIT = 20

IMAGE_EXPORT_FORMATS = {
    "PNG": {
        "extension": ".png",
        "extensions": (".png",),
        "qt_format": "PNG",
    },
    "JPEG": {
        "extension": ".jpg",
        "extensions": (".jpg", ".jpeg"),
        "qt_format": "JPG",
    },
    "TIFF": {
        "extension": ".tif",
        "extensions": (".tif", ".tiff"),
        "qt_format": "TIFF",
    },
}

IMAGE_EXPORT_FILTER = (
    "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;TIFF Image (*.tif *.tiff)"
)

RECENT_FILE_KIND_LABELS = {
    "video": "Video",
    "folder": "Sequence Folder",
    "project": "Project",
}


def sanitize_filename_part(text):
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", str(text or "")).strip()
    return cleaned or "export"


def ensure_extension(path, extension):
    root, current_extension = os.path.splitext(path)
    if current_extension.lower() == extension.lower():
        return path
    return root + extension


def normalize_image_format(path="", selected_filter=""):
    extension = os.path.splitext(path)[1].lower()
    for format_name, config in IMAGE_EXPORT_FORMATS.items():
        if extension in config["extensions"]:
            return format_name

    selected_filter = (selected_filter or "").upper()
    for format_name in IMAGE_EXPORT_FORMATS:
        if format_name in selected_filter:
            return format_name

    return "PNG"


def normalize_recent_files(entries, limit=RECENT_FILES_LIMIT):
    normalized = []
    seen = set()

    for entry in entries or []:
        if not isinstance(entry, dict):
            continue

        path = entry.get("path")
        kind = entry.get("kind", "video")
        if not isinstance(path, str) or not path.strip():
            continue

        path = os.path.normpath(path)
        dedupe_key = (path.lower(), kind)
        if dedupe_key in seen:
            continue

        normalized.append({"path": path, "kind": kind})
        seen.add(dedupe_key)

        if len(normalized) >= limit:
            break

    return normalized


def push_recent_file(entries, path, kind, limit=RECENT_FILES_LIMIT):
    path = os.path.normpath(path)
    fresh_entry = {"path": path, "kind": kind}

    merged = [fresh_entry]
    for entry in normalize_recent_files(entries, limit * 2):
        if entry["path"].lower() == path.lower() and entry["kind"] == kind:
            continue
        merged.append(entry)

    return normalize_recent_files(merged, limit)


def build_recent_file_label(entry):
    path = entry.get("path", "")
    kind = entry.get("kind", "video")
    trimmed = path.rstrip("\\/")
    name = os.path.basename(trimmed) or trimmed or path
    kind_label = RECENT_FILE_KIND_LABELS.get(kind, "File")
    return f"{name} ({kind_label})"


def build_frame_export_filename(source_name, frame_num, label, extension):
    source_name = sanitize_filename_part(source_name)
    label = sanitize_filename_part(label)
    return f"{source_name}_{label}_f{frame_num + 1:04d}{extension}"


def build_bookmark_export_filename(prefix, bookmark_index, frame_num, bookmark_name, extension):
    prefix = sanitize_filename_part(prefix)
    bookmark_name = sanitize_filename_part(bookmark_name or f"bookmark_{bookmark_index:03d}")
    return (
        f"{prefix}_bookmark_{bookmark_index:03d}_"
        f"f{frame_num + 1:04d}_{bookmark_name}{extension}"
    )


def build_bookmark_video_export_filename(prefix, extension):
    prefix = sanitize_filename_part(prefix)
    return f"{prefix}_bookmarks{extension}"


def build_shot_grid_filename(
    prefix,
    shot_index,
    start_frame,
    end_frame,
    rows,
    cols,
    extension,
    part=None,
    total_parts=None,
):
    prefix = sanitize_filename_part(prefix)
    filename = (
        f"{prefix}_shot_{shot_index:03d}_"
        f"f{start_frame + 1:04d}-{end_frame + 1:04d}_grid{rows}x{cols}"
    )
    if part is not None and total_parts and total_parts > 1:
        filename += f"_part{part}of{total_parts}"
    return filename + extension



def _find_ffprobe():
    """Return the path to ffprobe, or None."""
    return shutil.which("ffprobe")


def _find_ffmpeg():
    """Return the path to ffmpeg, or None."""
    return shutil.which("ffmpeg")


def probe_audio_stream(video_path):
    """Return audio stream info dict or None if no audio track exists.

    Returns: {"codec": "aac", "sample_rate": 48000, "channels": 2, "duration": 12.5}
    or None.
    """
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return None

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-select_streams", "a:0",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams:
            return None

        stream = streams[0]
        return {
            "codec": stream.get("codec_name", "unknown"),
            "sample_rate": int(stream.get("sample_rate", 0)),
            "channels": int(stream.get("channels", 0)),
            "duration": float(stream.get("duration", 0)),
        }
    except Exception:
        return None


def mux_audio_into_mp4(
    video_only_path,
    source_media_path,
    output_path,
    start_frame,
    end_frame,
    fps,
    pad_frames=0,
):
    """Extract audio sub-clip from source, pad with silence if needed,
    mux with the video-only file, write to output_path.

    Uses system ffmpeg via subprocess.
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")

    start_time = start_frame / fps
    source_duration = (end_frame - start_frame + 1) / fps
    target_duration = source_duration + (pad_frames / fps)

    # Use a temp file to avoid overwriting the input if output_path == video_only_path
    fd, temp_output = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)

    try:
        cmd = [
            ffmpeg,
            "-y",
            "-i", video_only_path,
            "-ss", f"{start_time:.6f}",
            "-t", f"{source_duration:.6f}",
            "-i", source_media_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
        ]

        if pad_frames > 0:
            cmd.extend([
                "-filter_complex",
                f"[1:a]apad=whole_dur={target_duration:.6f}[a]",
                "-map", "0:v:0",
                "-map", "[a]",
            ])
        else:
            cmd.extend([
                "-map", "0:v:0",
                "-map", "1:a:0",
            ])

        cmd.extend(["-shortest", temp_output])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg mux failed (exit {result.returncode}): {result.stderr[-500:]}"
            )

        # Move temp to final destination
        shutil.move(temp_output, output_path)

    finally:
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except OSError:
                pass
