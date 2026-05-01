import os
import re


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
