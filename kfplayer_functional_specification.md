# KFPlayer — Clean Room Functional Specification

> **Purpose**: This document describes *what* KFPlayer does — its observable features, UI behaviors, data formats, and business rules — without revealing *how* it is implemented. An independent development team should be able to build a functionally equivalent application from this specification alone.

---

## 1. Application Identity

| Property | Value |
|---|---|
| **Product Name** | KFPlayer |
| **UI Window Title** | `Keyframe Pro Lite` |
| **Version** | 1.0 |
| **Platform** | Windows desktop (also runs on any OS supporting the required runtime) |
| **Purpose** | Lightweight animation review tool for animators and editors |

---

## 2. Technology Requirements

The application requires these runtime capabilities. An independent implementation may use any stack that provides equivalent functionality.

| Capability | Purpose |
|---|---|
| Desktop GUI framework with dark theme | Main application window, dialogs, widgets |
| Video decoding (MP4, AVI, MOV, MKV, WebM, WMV) | Video file playback and frame extraction |
| Animated GIF decoding | GIF playback with correct frame count |
| Image format reading (EXR, PNG, JPG, JPEG, TIFF, TIF, DPX, TGA, BMP) | Image sequence loading |
| Image format writing (PNG, JPEG, TIFF) | Image export |
| H.264 MP4 encoding | Video export with configurable CRF and preset |
| Image histogram comparison and edge detection | Traditional cut candidate scanning |
| Google GenAI SDK | Gemma/Gemini AI integration for shot detection |
| Process memory monitoring | Status bar memory display |
| `.env` file loading | API key configuration at startup |

### 2.1 Runtime Dependencies

| Package | Minimum Version |
|---|---|
| PyQt6 | ≥ 6.0 |
| opencv-python | ≥ 4.5 |
| Pillow | ≥ 9.0 |
| numpy | ≥ 1.20 |
| psutil | ≥ 5.8.0 |
| imageio | ≥ 2.30.0 |
| imageio-ffmpeg | ≥ 0.4.0 |
| google-genai | ≥ 1.0.0 |

---

## 3. Application Bootstrap

### 3.1 Startup Sequence

1. Set the working directory to the location of the application entry point.
2. Load a `.env` file from the working directory. The parser:
   - Skips empty lines and lines starting with `#`.
   - Splits on the first `=` character.
   - Strips surrounding single or double quotes from values.
   - Sets each key-value pair as an environment variable.
3. Enable high-DPI passthrough scaling.
4. Set the application style to "Fusion".
5. Apply a dark theme stylesheet to all widgets.
6. Show the main window.

### 3.2 Visual Theme

The entire application uses a dark color scheme:

| Element | Color |
|---|---|
| Background | `#1a1a1a` |
| Text | `#e0e0e0` |
| Accent / Hover | `#00a8ff` (bright blue) |
| Accent Pressed | `#00a8ff` with white text |
| Bookmarks | `#ff6b35` (orange) |
| Playhead | `#00ff88` (green) |
| Status bar | `#1e1e1e` background, `#888` text |

Font family: `'Segoe UI', sans-serif`.

---

## 4. Main Window Layout

### 4.1 Window Properties

- **Default size**: 1280 × 720
- **Minimum size**: 640 × 480
- **Title format**: `Keyframe Pro Lite` (no media loaded) or `KFPlayer — {source_name}` (media loaded)

### 4.2 Layout Structure

```
┌──────────────────────────────────────────────────┐
│ Menu Bar                                         │
├──────────────────────────────────────────────────┤
│ Toolbar                                          │
├───────────────────────────────────┬──────────────┤
│                                   │  Bookmarks   │
│         Viewer (4:1 ratio)        │  Panel       │
│                                   │  (1:4 ratio) │
├───────────────────────────────────┴──────────────┤
│ Overview Timeline (thin bar, full width)         │
│ Thumbnail Timeline (scrollable, with thumbnails) │
├──────────────────────────────────────────────────┤
│ Status Bar                                       │
└──────────────────────────────────────────────────┘
```

The viewer area and bookmark panel are in a horizontal splitter (4:1 default ratio). The top section and timeline section are in a vertical splitter (9:1 default ratio).

### 4.3 Drag and Drop

The central widget accepts file drops:

| Drop Type | Behavior |
|---|---|
| Directory | Load it as an image sequence folder |
| Video file (`.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`, `.wmv`, `.gif`) | Load it as a video |
| Image file (`.png`, `.jpg`, `.jpeg`, `.tga`, `.bmp`, `.tiff`, `.tif`, `.exr`, `.dpx`) | Load its parent folder as an image sequence |

---

## 5. Media Loading

### 5.1 Video Files

**Supported formats**: MP4, AVI, MOV, MKV, WebM, WMV, GIF.

**Open methods**:
- Menu: `File → Open Video File...` (shortcut: `Ctrl+Shift+V`)
- Drag and drop a video file onto the window
- Recent Files menu

**Loading behavior**:
1. Clear all existing state (frame cache, thumbnails, bookmarks, timelines).
2. Read video properties: frame count, FPS, width, height.
3. For GIF files: use image-based decoding to get the correct frame count and duration-based FPS.
4. Set the project FPS to the video's FPS (rounded to integer, minimum 24).
5. Store video resolution for display.
6. Update the window title to `KFPlayer — {filename}`.
7. Show a toolbar label with the filename.
8. Add to recent files list.
9. Begin generating thumbnails in a background thread (sampling ~50 evenly spaced frames).
10. Display a status bar message: `Loaded video: {filename} - {frame_count} frames at {fps} fps`.

### 5.2 Image Sequences

**Supported image formats**: EXR, PNG, JPG, JPEG, TIFF, TIF, DPX, TGA, BMP.

**Open methods**:
- Toolbar: `📂 Open` button
- Menu: `File → Open Folder...` (shortcut: `Ctrl+O`)
- Drag and drop a folder

**Sequence detection rules**:
- Recursively scan the folder for image files with supported extensions.
- Match filenames against the pattern: `{base_name}{separator}{frame_number}.{extension}` where separator is `.` or `_`.
- Group files by base name.
- Only sequences with more than 1 file are valid.
- Return sequences sorted by file count (largest first).
- The largest sequence is used as the primary source.

**Loading behavior**:
1. Clear all existing state.
2. Load the largest detected sequence.
3. Read resolution from the first frame image.
4. Update timelines and generate thumbnails (background thread, ~50 samples).
5. Update window title and add to recent files.
6. If no sequences found: show warning dialog "No image sequences found in the selected folder."

### 5.3 Frame Loading and Caching

- Frames are loaded on demand and cached in an LRU dictionary.
- Cache capacity is calculated as: `(cache_size_mb × 1024 × 1024) / (1920 × 1080 × 4)` frames.
- When the cache exceeds capacity, the oldest entry is evicted.
- Video frames: decoded by seeking to the target frame number.
- GIF frames: decoded by seeking to the target frame and converting to RGB.
- Image sequence frames: loaded from disk, converted to RGB if needed.

---

## 6. Playback Controls

### 6.1 Toolbar Controls

| Control | Icon | Shortcut | Behavior |
|---|---|---|---|
| Jump to Start | `\|◀` | `Home` | Seek to frame 0 |
| Previous Frame | `◀` | `Left Arrow` | Seek to current frame − 1 |
| Play/Pause | `▶` / `❚❚` | `Space` | Toggle playback |
| Next Frame | `▶` | `Right Arrow` | Seek to current frame + 1 |
| Jump to End | `▶\|` | `End` | Seek to last frame |
| Loop Toggle | `🔁` | — | Toggle loop playback (checkable button) |
| Speed | Dropdown | — | `0.25x`, `0.5x`, `1x`, `2x` |

### 6.2 Playback Behavior

- Timer interval: `1000 / (FPS × playback_speed)` milliseconds.
- On each tick: advance one frame, update display, update timelines.
- At end of frames:
  - If loop enabled: wrap to frame 0.
  - If loop disabled: stop playback, reset button to `▶`.
- Changing speed while playing: restart the timer with the new interval.

### 6.3 Frame Display

The toolbar shows:
- **Frame counter**: `Frame: {current + 1} / {total} [{width}×{height}]` (resolution shown when available)
- **Timecode**: `HH:MM:SS:FF` format (frames within current second as the last component)
- **FPS label**: `{fps} FPS`
- **Source name**: filename or folder name (italic, gray)

---

## 7. Viewer Widget

### 7.1 Display

- Black background (`#000000`).
- Image is scaled to fit the widget while maintaining aspect ratio (using smooth transformation).
- Image is centered in the widget.

### 7.2 Pan and Zoom

| Input | Action |
|---|---|
| Left-click drag | Pan the image |
| Middle-click drag | Pan the image |
| Scroll wheel up | Zoom in (multiply by 1.2, max 4.0×) |
| Scroll wheel down | Zoom out (divide by 1.2, min 0.25×) |
| Menu: `View → Fit to Window` (`F`) | Reset zoom to 1.0× and pan to origin |
| Menu: `View → Zoom In` (`Ctrl+=`) | Zoom in |
| Menu: `View → Zoom Out` (`Ctrl+-`) | Zoom out |

Pan values are divided by current zoom level to maintain consistent drag speed.

### 7.3 Context Menu (Right-Click on Viewer)

| Action | Condition |
|---|---|
| Copy Frame to Clipboard | Enabled when a frame is displayed |
| Export Current Frame... | Enabled when media is loaded |
| Export First Frame... | Enabled when media is loaded |
| Export Last Frame... | Enabled when media is loaded |
| Export Bookmarks... | Enabled when bookmarks exist |

---

## 8. Timeline System

### 8.1 Overview Timeline (Thin Bar)

- **Height**: Fixed at 28px.
- **Full width**: Represents the entire clip length.
- **Visual elements**:
  - Rounded dark background bar (`#323237`).
  - Blue tinted progress region up to the playhead (`#00a8ff` at 50/255 opacity).
  - Bookmark markers: orange (`#ff6b35`) 3px-wide rounded rectangles.
  - Playhead: green (`#00ff88`) 6px-wide rounded rectangle.
- **Interaction**: Click or drag to seek. Cursor shows pointing hand.
- **Bookmark hover**: Hovering within 4px of a bookmark marker emits a hover signal.

### 8.2 Thumbnail Timeline (Scrollable)

- **Height**: 120px min, 200px max.
- **Scrollable**: Horizontal scroll area, always-on horizontal scrollbar.
- **Visual elements**:
  - Thumbnails rendered behind the timeline at their respective frame positions.
  - Frame number markers every 10 frames along the bottom.
  - In/out point markers: yellow semi-transparent rectangles.
  - Bookmark markers: orange circles (8px diameter) at the top.
  - Playhead: green line with triangle pointer at top.
- **Interaction**:
  - Click or drag to seek to a frame.
  - `Ctrl+Scroll`: Change thumbnail zoom level (32–128px, adjusting frame width accordingly).
  - Bookmark hover: Hovering within 6px of a bookmark marker.
- **Auto-scroll**: The viewport scrolls to keep the playhead visible with 100px margin.

### 8.3 Bookmark Hover Behavior

When hovering over a bookmark marker on either timeline:
- The bookmark frame number is reported to the main window.
- The main bookmark button text changes from `+ Add Bookmark` to `- Remove Bookmark` with a tooltip showing the hovered bookmark's frame.
- Clicking the button in this state removes the hovered bookmark.
- When the mouse leaves the bookmark area, the button reverts to showing the state for the current frame.

---

## 9. Bookmark System

### 9.1 Bookmark Data Structure

Each bookmark is a dictionary:
```
{
  "frame": <integer>,       // 0-indexed frame number
  "name": <string>,         // display name, e.g., "Bookmark 3"
  "color": <string>         // hex color, default "#ff6b35"
}
```

### 9.2 Adding Bookmarks

- **Default name**: `Bookmark {count + 1}`.
- **Default color**: `#ff6b35` (orange).
- Duplicate bookmarks on the same frame are silently ignored (no second bookmark added).
- The bookmark is added to: the bookmark list, the thumbnail timeline, and the overview timeline.

### 9.3 Bookmark Panel

- Located in the right sidebar.
- Shows a sorted list of bookmarks: `Frame {frame + 1}: {name}`.
- Each item is colored with the bookmark's color.
- Clicking a bookmark item seeks to that frame.

### 9.4 Bookmark Button Behavior

The main bookmark button (`+ Add Bookmark` / `- Remove Bookmark`) is contextual:

| State | Button Text | Action |
|---|---|---|
| Hovering a bookmark on timeline | `- Remove Bookmark` | Remove the hovered bookmark |
| Current frame has a bookmark | `- Remove Bookmark` | Remove the current frame's bookmark |
| Current frame has no bookmark | `+ Add Bookmark` | Add a bookmark at the current frame |

### 9.5 Clear Bookmarks Button

- Shows `Clear Bookmarks`.
- Disabled when no bookmarks exist.
- Clicking shows a confirmation dialog: "Delete all bookmarks from this clip?"
- On confirm: clears all bookmarks, timelines, and the bookmark list.

### 9.6 Bookmark Context Menu (Right-Click in Bookmark List)

| Action | Behavior |
|---|---|
| Export Bookmark Image... | Export the selected bookmark's frame as an image |
| Export Bookmarks... | Open the unified bookmark export dialog |
| Delete All Bookmarks | Clear all bookmarks (with confirmation) |
| Delete Bookmark | Delete the clicked bookmark |

---

## 10. Project Save/Load

### 10.1 Project File Format

- **Extension**: `.kfp_basic`
- **Format**: JSON
- **Schema**:

```json
{
  "version": "1.0",
  "is_video": true,                    // present for video-based projects
  "video_path": "/path/to/video.mp4",  // present for video-based projects
  "sources": [                         // present for folder-based projects
    {
      "path": "relative/path",
      "absolute": "/absolute/path",
      "start": 0,
      "end": 999
    }
  ],
  "timeline": {
    "current": 42,
    "inPoint": 0,
    "outPoint": 999
  },
  "bookmarks": [
    { "frame": 10, "name": "Bookmark 1", "color": "#ff6b35" }
  ],
  "view": {
    "panX": 0.0,
    "panY": 0.0,
    "zoom": 1.0
  },
  "settings": {
    "fps": 24,
    "loop": false
  }
}
```

### 10.2 Save Behavior

- Menu: `File → Save Project` (`Ctrl+S`)
- Opens a save dialog with filter `Keyframe Pro Project (*.kfp_basic)`.
- Appends `.kfp_basic` extension if not present.
- Saves the current state including bookmarks, view position, and settings.

### 10.3 Load Behavior

- Menu: `File → Load Project...` (`Ctrl+Shift+O`)
- If `is_video` is true: loads the video from `video_path`.
- Otherwise: loads the folder from the first source's absolute path.
- Restores bookmarks, timeline position, view state, FPS, and loop setting.
- If the source file/folder is missing: shows a warning dialog.

### 10.4 Auto-Save

- When enabled: saves to `{project_folder}/.kfpro_autosave.kfp_basic` every 2 minutes.
- Only fires if the project has a folder and at least one bookmark.

---

## 11. Recent Files

### 11.1 Storage

- Persisted in the settings file at `~/.kfpro_lite_settings.json`.
- Maximum 20 entries.
- Each entry: `{ "path": "...", "kind": "video" | "folder" | "project" }`.

### 11.2 Deduplication

- Normalized by `os.path.normpath()`.
- Deduplicated by case-insensitive path + kind pair.

### 11.3 Menu Display

- Menu: `File → Recent Files`.
- Label format: `{basename} ({kind_label})` where kind labels are:
  - `video` → `Video`
  - `folder` → `Sequence Folder`
  - `project` → `Project`
- Tooltip: full path.
- Bottom action: `Clear History`.
- When clicking a missing file: shows warning and removes from list.

---

## 12. Preferences

- Menu: accessed via `⚙` button in toolbar.
- Dialog: `Preferences`, 300×280px, modal.

| Setting | Range | Default | Notes |
|---|---|---|---|
| Cache Size | 100–2000 MB | 500 MB | Frame cache memory limit |
| Default FPS | 12–60 | 24 | Used for image sequences |
| Export Folder | Path | `~/Videos/KFPlayer` | Default export destination |
| Audio Scrub | Checkbox | Off | (Setting stored but not actively used) |
| Scrub Sensitivity | 1–10 | 5 | (Setting stored but not actively used) |
| Auto-save (2 min) | Checkbox | On | Saves project every 2 minutes |

### 12.1 Settings Persistence

Stored as JSON at `~/.kfpro_lite_settings.json`:
```json
{
  "cache_size": 500,
  "default_fps": 24,
  "export_folder": "",
  "audio_scrub": false,
  "scrub_sensitivity": 5,
  "auto_save": true,
  "recent_files": []
}
```

---

## 13. Export System

### 13.1 Export Menu Structure

```
File → Export →
  ├── Frame / Sequence...        (Ctrl+P)
  ├── Current Frame Image...
  ├── First Frame Image...
  ├── Last Frame Image...
  ├── Bookmarks...
  ├── MP4...
  ├── Wan Preparation...
  └── Smart Grid Splitter...
```

### 13.2 Image Export Formats

| Format | Extension(s) | Quality Control |
|---|---|---|
| PNG | `.png` | Compression level 1 |
| JPEG | `.jpg`, `.jpeg` | Quality 80–100 (default 95) |
| TIFF | `.tif`, `.tiff` | — |

Format is detected from the file extension first, then the file dialog filter, defaulting to PNG.

### 13.3 Export Filename Conventions

| Export Type | Pattern |
|---|---|
| Single frame | `{source_name}_{label}_f{frame+1:04d}{extension}` |
| Bookmark image | `{prefix}_bookmark_{index:03d}_f{frame+1:04d}_{bookmark_name}{extension}` |
| Bookmark video | `{prefix}_bookmarks.mp4` |

Characters `< > : " / \ | ? *` in filename parts are replaced with `_`.

### 13.4 Frame Image Export

**Single frame exports** (Current / First / Last frame):
1. Show a save dialog pre-populated with the suggested filename.
2. Detect format from extension or dialog filter.
3. Ensure the extension matches the format.
4. Show a progress dialog while saving.
5. For image sequences: if the source file format matches the export format, copy the source file directly (fast path).
6. Otherwise: load the frame, convert to the target format, and write.

### 13.5 Bookmark Export (Unified Dialog)

**Dialog**: `Export Bookmarks`, modal, min width 420px.

Two modes, selected by a dropdown:

#### Image Sequence Mode
- **Output folder**: Directory picker.
- **Filename prefix**: Defaults to the loaded source name.
- **Format**: PNG / JPEG / TIFF dropdown.
- **JPEG Quality**: Slider 80–100 (shown only when JPEG selected).
- Exports each bookmark as an individual image file, sorted by frame number.

#### Video Mode
- **Output file**: File path with save dialog (MP4).
- **Hold per bookmark**: 1–9999 frames (how many times to repeat each bookmark frame).
- **Export FPS**: 1–120 fps.
- **Video compression**: Quality slider 1–10 (maps to CRF values).
- **Speed preset**: ultrafast / fast / medium / slow.
- **Duration hint**: Shows estimated reel length: `{hold_frames} frame(s) at {fps} fps. Estimated reel length: {duration:.2f} seconds.`
- Bookmarks are stitched in timeline order (sorted by frame number).
- Each bookmark frame is repeated for the configured hold duration.

### 13.6 MP4 Export

**Dialog**: `Export to MP4`, modal, min width 350px.

| Field | Range | Default |
|---|---|---|
| Start Frame | 0 to total−1 | 0 |
| End Frame | 0 to total−1 | total−1 |
| Compression | 1–10 | 5 |
| Speed | ultrafast/fast/medium/slow | fast |

**Quality mapping**: CRF = `35 − ((quality − 1) × (20 / 9))`. Quality 1 ≈ CRF 35 (small file), Quality 10 ≈ CRF 13 (near lossless).

**Encoding**: H.264 codec, libx264, no macro block size constraint.

**Progress**: Shows a dialog with a progress bar tracking frames exported.

### 13.7 Frame/Sequence Export Dialog

**Dialog**: `Export`, modal, 400×350px.

- Export type: `Single Frame` or `Image Sequence` (via buttons).
- Format: PNG / JPEG / TIFF.
- JPEG Quality: slider 1–100.
- Output folder with browse button.
- Filename pattern (e.g., `frame_####.png` where `####` is replaced with the 4-digit frame number).
- Resize options: Full / Half / Quarter.
- Single frame exports the current frame.
- Sequence export is marked as "coming soon".

---

## 14. WAN Preparation

### 14.1 Purpose

Prepare long clips for WAN 2.2-style chunk processing by splitting them into WAN-safe sizes, generating contact-sheet grids, and writing JSON metadata.

### 14.2 WAN-Safe Chunk Rules

A WAN-safe frame count must satisfy the formula: `(x × 4) + 1` where `x ≥ 0`.

Valid lengths: 1, 5, 9, 13, 17, 21, 25, 29, ..., 89, 93, ...

#### Snapping
- **Snap down (floor)**: Given `n`, compute `((n − 1) // 4) × 4 + 1`. Special case: `n ≤ 1` → 1.
- **Snap up (ceil)**: Given `n`, compute `((n − 1) // 4 + 1) × 4 + 1` if `n` is not already valid.

#### Default chunk size
- Default WAN chunk size: **93 frames**.
- The requested chunk size is always snapped down to the nearest WAN-safe value before use.

### 14.3 Overlap

- Overlap range: **4–32 frames** (when chunk size allows).
- If `max_overlap < 4`: overlap is set to `max_overlap` (which may be less than 4).
- If overlap is 0 or negative: disabled.
- `max_overlap = min(32, chunk_size − 1)`.

### 14.4 Chunk Planning Algorithm

Given `total_frames`, `chunk_size`, and `overlap`:

1. If `total_frames ≤ chunk_size`: one chunk, padded to next WAN-safe length.
2. If `total_frames ≤ 2 × chunk_size − overlap` (fits in two chunks): balance the split.
   - Compute `ideal = (span + overlap) / 2`.
   - Try snapping `ideal` up; if it fits, use it. Otherwise, snap the minimum up. Otherwise, snap the maximum down.
   - Second chunk gets the remainder, padded to WAN-safe.
3. Otherwise: emit full-size chunks with stride `chunk_size − overlap`, then recursively handle the tail.

#### Key invariants
- Only the **final chunk** may be padded (by repeating its last frame).
- Tail balancing avoids tiny trailing chunks by splitting the remaining frames between two balanced chunks.

### 14.5 WAN Preparation Dialog

**Dialog**: `Wan Preparation`, modal, min width 400px.

| Field | Range | Default |
|---|---|---|
| Output Folder | Path | Default export folder |
| Filename Prefix | Text | Source name |
| Start Frame | 0 to total−1 | 0 |
| End Frame | 0 to total−1 | total−1 |
| Grid Size | Auto(Dynamic) / 2×2 / 3×3 | Auto |
| Grid Mode | One grid per chunk (checkbox) | Off |
| Chunk Size | 1–10000 | 93 |
| Overlap | Enable checkbox + 4–32 spinner | 8, disabled |
| Compression | 1–10 | 5 |
| Speed | ultrafast/fast/medium/slow | fast |

**Live preview**: As you adjust chunk size, overlap, and frame range, the dialog dynamically shows:
- Number of resulting chunks and their target lengths.
- Source chunk lengths (with padding notation: `{source}→{target}`).
- Whether overlap is active and its value.
- Whether trailing padding is needed.

### 14.6 Grid Generation Rules

**Auto grid sizing**: The system tries to find `k` frames per chunk and a grid dimension (`2×2` or `3×3`) that minimizes wasted (black) grid cells:
1. Try `k` from 3 to 5, with dimensions from the preference or `[3, 2]`.
2. Find the smallest `k` where `num_chunks × k` is divisible by `dim²`.
3. If no perfect fit: pick the dimension with least waste.
4. Special cases: 1 chunk → 4 frames in 2×2; 3 chunks → 3 frames in 3×3.

**Per-chunk grid mode**: Each chunk gets its own grid with exactly `dim²` frames.

**Frame distribution**: Extra frames are distributed round-robin across chunks to eliminate black squares in grids.

**Frame selection**: For `k` frames from a chunk spanning `[abs_start, abs_end]`:
- If span is 0: all frames are `abs_start`.
- Otherwise: evenly space `k` frames: `abs_start + i × span // (k − 1)` for `i` in `[0, k)`.

### 14.7 Frame Review Dialog

**Before export**, a `WanFrameReviewDialog` shows all auto-selected grid frames grouped by chunk:

- **Layout**: Scrollable area with chunk headers and thumbnail rows.
- **Thumbnail size**: 160×160px.
- **Interaction**: Click any thumbnail to open a `WanFramePickerDialog`.
  - The picker shows a large preview with a scrub slider constrained to the chunk's frame range.
  - The user can pick any replacement frame from that chunk.
  - On accept: the replacement frame is stored and the thumbnail updates.
- **Buttons**: `Cancel` (abort) or `Accept && Export` (proceed with the reviewed selections).

### 14.8 WAN Export Outputs

For each chunk, a dedicated subdirectory is created: `{prefix}_chunk_{index:03d}/`

**Per chunk**:
- `{prefix}_wan22_{index:03d}_{target_length:03d}f_{abs_start:04d}-{abs_end:04d}.mp4` — The chunk video (padded to WAN-safe length by repeating the last frame).
- `{prefix}_chunk_{index:03d}_frame_{i+1:02d}_f{frame:04d}.jpg` — Each selected keyframe as a JPEG (quality 95).
- `{prefix}_chunk_{index:03d}_1fps.mp4` — A 1fps video containing only the reviewed keyframes.

**Grid images**: Contact sheet grids as JPEG (quality 95):
- Per-chunk mode: `{prefix}_chunk_{index:03d}_grid_{dim}x{dim}.jpg` (inside chunk directory).
- Combined mode: `{prefix}_grid_{dim}x{dim}_{grid_index:03d}.jpg` (in output root).

**Metadata JSON**: `{prefix}_wan_preparation.json`:
```json
{
  "chunk 1": [0, 23, 46, 69],     // relative frame indices per chunk
  "chunk 2": [...],
  "start_frame": 0,
  "end_frame": 500,
  "total_frames_processed": 501,
  "chunk_size": 93,
  "overlap": 0,
  "num_chunks": 6,
  "k_frames_per_chunk": 3,
  "grid_dim": 3,
  "output_grids": ["grid_3x3_000.jpg", ...],
  "chunks": [
    {
      "chunk_index": 0,
      "chunk_data": {
        "start_frame": 0,
        "end_frame": 92,
        "source_length": 93,
        "target_length": 93
      },
      "video_start_frame_abs": 0,
      "video_end_frame_abs": 92,
      "selected_frames_abs": [0, 31, 62]
    }
  ]
}
```

---

## 15. Smart Grid Splitter

### 15.1 Purpose

Take a video chunk, JSON metadata, and a colorized grid image. Overlay the grid on the video to verify alignment, then export each grid cell cropped to the original video resolution.

### 15.2 Setup Dialog

**Dialog**: `Smart Grid Splitter – Setup`, modal, min width 520px.

| Field | Filter |
|---|---|
| Video Chunk | `*.mp4 *.avi *.mov *.mkv` |
| JSON Metadata | `*.json` |
| Grid Image | `*.jpg *.jpeg *.png *.bmp` |
| Select Chunk | Populated from JSON chunks |
| Output Folder | Default: same as grid image |

Chunk selector shows: `Chunk {index + 1} (frames {start}–{end})`.

### 15.3 Splitter Viewport

- **Dark background**: `#0a0a14`.
- **Video frame**: Fit to viewport maintaining aspect ratio.
- **Grid overlay**: Drawn on top with configurable opacity and scale.
- **Cell boundaries**: Dashed yellow lines at cell boundaries.

**Grid position calculation**: For cell `i` (0-indexed, row-major) in an N×N grid:
```
col = i % N
row = i // N
offset_x = -col × frame_width
offset_y = -row × frame_height
```

**Manual nudge**: Click-drag shifts the grid. The nudge is stored per-frame and persists when navigating between frames.

### 15.4 Controls

| Control | Range | Default |
|---|---|---|
| Navigation | ◀ Prev / Next ▶ | First frame |
| Opacity | 0–100% (slider + spinbox) | 50% |
| Scale | 10–300% (slider + spinbox) | 100% |
| Lock Aspect | Checkbox | On |
| Reset Position | Button | Resets nudge to (0,0) |

Navigation is limited to only the frames used to build the grid (from JSON metadata).

### 15.5 Export

Clicking "Export Split Images":
1. For each selected frame, calculate the crop region in the grid image.
2. Account for scale and per-frame nudge.
3. Crop the cell region and resize to original video frame dimensions.
4. Save as PNG: `{grid_basename}_split_{i:03d}_f{frame_rel:04d}.png`.
5. Show progress dialog then success message.

---

## 16. Gemma/Gemini Shot Detection

### 16.1 Purpose

Detect hard-cut shot boundaries using a hybrid pipeline combining AI video analysis and traditional frame-difference scoring.

### 16.2 Shot Detection Dialog

**Dialog**: `Detect Shots`, modal, min width 460px.

| Field | Notes |
|---|---|
| Output Folder | Directory for output files |
| Filename Prefix | Default: `{source_name}_shots` |
| Google API Key | Password field, optional (falls back to env vars) |
| Model | Gemini 3 Flash / Gemini 3.1 Flash-Lite / Gemma 4 31B / Gemma 4 26B |
| Start Frame | 0 to total−1 |
| End Frame | 0 to total−1 |
| Add detected shots as bookmarks | Checkbox, default on |
| Clear existing bookmarks first | Checkbox, default off (disabled when above is off) |

**Live preview**: Shows how many chunks the frame range will produce.

### 16.3 API Key Resolution

Priority order:
1. Key entered in the dialog.
2. `GOOGLE_API_KEY` environment variable.
3. `GEMINI_API_KEY` environment variable.

**Dummy key detection**: The following values are recognized as dummy placeholders and rejected with a clear warning:
- Empty string
- `AIzaSyDUMMY_REPLACE_ME`
- `your-google-ai-studio-key-here`
- `replace-with-your-google-ai-studio-key`
- `dummy-gemini-key`

### 16.4 Hybrid Pipeline

The detection runs as a modal progress dialog with these stages:

#### Stage 1: Traditional Cut Scanning (~5–20%)
1. Iterate all frames in the range at reduced resolution (max 256px longest side).
2. For each consecutive frame pair, compute a composite score from:
   - **Histogram difference** (Bhattacharyya distance on HSV 8×8×8 histogram) — weight 52%
   - **Grayscale pixel difference** (mean absolute difference) — weight 25%
   - **Edge difference** (Canny edge map comparison) — weight 13%
   - **Luminance jump** (absolute grayscale mean difference) — weight 10%
3. From the score series, detect peak candidates using statistical thresholding:
   - Base threshold: `median + 2.5 × MAD` (MAD = Median Absolute Deviation, scaled ×1.4826).
   - Strong threshold: `max(median + 4.0 × MAD, 97th percentile)`.
   - Bridge threshold: `max(median + 1.5 × MAD, base × 0.7)`.
   - Minimum gap: `max(3, round(FPS × 0.25))` frames.
4. Peaks in runs above the bridge threshold are collapsed to the strongest peak.
5. Confidence: `0.55 + ((peak − base) / (strong − base)) × 0.45`, clamped to [0, 1].

#### Stage 2: AI Chunk Analysis (~20–70%)
1. Split the frame range into **59-second chunks** (no overlap).
2. For each chunk:
   a. Encode a temporary MP4 at max 960px resolution, CRF 26, ultrafast preset.
   b. Upload to Google GenAI.
   c. Poll for processing completion (up to 180 iterations, 2-second intervals).
   d. Send analysis prompt to the selected model with high thinking level.
   e. Parse the JSON response.
   f. Delete the uploaded file.

**AI analysis prompt** asks the model to:
- Return JSON with `first_shot_signature`, `last_shot_signature`, and a `shots` array.
- Each shot has: `start_seconds`, `description`, `continues_from_previous`, `continues_to_next`, `confidence`.
- Only mark real edit boundaries/hard cuts as new shots.
- Do NOT create shots for: zooms, pans, tilts, dollies, handheld drift, reframing, rack focus, or subject movement.

#### Stage 3: Candidate Alignment (~70–72%)
For each AI-detected shot within a chunk (except the first):
- Find the nearest traditional cut candidate within a tolerance window of **1.75 seconds**.
- If a matching candidate is found: snap the shot boundary to the candidate's frame.
- If no matching candidate is found and `require_candidate_for_internal_cuts` is true: **drop the AI shot** (it was likely a false positive from camera movement).

#### Stage 4: Seam Reconciliation (~72–84%)
At each chunk boundary:
1. Build a contact sheet with before/after frame pairs at the seam.
2. Send to AI for validation: "Is this a real shot boundary?"
3. For each seam, compute a "carry score" to decide merge vs. keep:
   - `+0.55` if AI says same shot.
   - `+0.25` if description similarity ≥ 0.72.
   - `+0.10` if previous shot's `continues_to_next` flag is set.
   - `+0.10` if next shot's `continues_from_previous` flag is set.
   - `−0.35 × seam_candidate_confidence` (penalizes strong traditional cuts).
   - **Merge if carry score ≥ 0.45**.
4. If merging: combine descriptions (prefer longer or more specific), keep the higher confidence.

**Description similarity**: Computed as a weighted blend of:
- SequenceMatcher ratio (65%) after normalizing to lowercase tokens with stopwords removed.
- Jaccard index of token sets (35%).

#### Stage 5: Missed Cut Promotion (~84–94%)
1. Find traditional candidates with confidence ≥ 0.82 that weren't matched to any AI shot.
2. Build contact sheets for these candidates (batches of 8).
3. Send to AI for validation.
4. If AI confirms a cut: create a new shot entry with source `candidate_validation`.

#### Stage 6: Finalization (~94–100%)
1. Merge all shots (from chunk analysis + promoted candidates).
2. Sort by start frame.
3. Collapse shots at the same frame (prefer longer description, keep higher confidence).
4. Compute end frames: each shot ends one frame before the next shot starts (last shot ends at clip end).
5. Format timestamps as `HH:MM:SS.mmm`.

### 16.5 Retry and Error Handling

- All Google API calls retry automatically on transient errors.
- **Retryable errors**: `ServerError`, `TimeoutError`, HTTP 500 status codes, or error messages containing "500".
- Retry strategy: exponential backoff starting at 2 seconds, up to 4 attempts.
- Status messages update during retries to inform the user.
- If all retries fail: show error in the progress dialog.

### 16.6 AI Validation Prompt (Contact Sheet)

Used for both seam reconciliation and missed-cut promotion:
- Contact sheet image with before/after frame pairs arranged in rows.
- Tile size: 320×180px, padded to fit.
- AI is asked to return JSON with `is_shot_boundary`, `new_shot_description`, and `confidence` per candidate.
- Rules: only mark true for actual edits, not for camera movement within one continuous take.

### 16.7 Output Files

**Text file** (`{prefix}_gemma_shots.txt`):
```
001  00:00:00.000  Opening wide shot.
002  00:00:02.000  Close-up on actor.
003  00:00:05.000  Reaction shot.
```

**JSON file** (`{prefix}_gemma_shots.json`):
```json
{
  "source_name": "my_video",
  "model": "gemma-4-31b-it",
  "fps": 24,
  "start_frame": 0,
  "end_frame": 3599,
  "shots": [
    {
      "index": 1,
      "start_frame": 0,
      "end_frame": 47,
      "start_seconds": 0.0,
      "end_seconds": 1.958,
      "start_timestamp": "00:00:00.000",
      "end_timestamp": "00:00:01.958",
      "description": "Opening wide shot.",
      "source": "chunk",
      "confidence": 0.81,
      "chunk_index": 0,
      "continues_from_previous": false,
      "continues_to_next": false
    }
  ],
  "chunks": [
    {
      "chunk_index": 0,
      "start_frame": 0,
      "end_frame": 1415,
      "start_timestamp": "00:00:00.000",
      "end_timestamp": "00:00:58.958",
      "duration_seconds": 59.0,
      "first_shot_signature": "wide skyline",
      "last_shot_signature": "close-up on actor",
      "shots": [...]
    }
  ],
  "traditional_candidates": [
    {
      "frame": 48,
      "timestamp": "00:00:02.000",
      "score": 0.95,
      "confidence": 0.88,
      "kind": "strong"
    }
  ]
}
```

### 16.8 Bookmark Integration

When "Add detected shots as bookmarks" is enabled:
- Each finalized shot is added as a bookmark.
- Color: `#00a8ff` (blue, distinct from manual bookmarks).
- Name format: `Shot {index:03d} {timestamp} {description[:48]}...`
- Duplicate frames are skipped.
- If "Clear existing bookmarks first" is checked: all existing bookmarks are removed first.

---

## 17. Annotation Layer (Inactive)

The application contains an annotation layer system that supports:
- Freehand drawing tool.
- Per-frame stroke storage (frame number → list of strokes).
- Configurable brush color (default `#ff6b35`), size (default 3), and tool type.
- Stroke rendering on the viewer.
- Visibility toggle.
- JSON export/import of stroke data.

> **Note**: This feature exists in the codebase but does not appear to be actively wired into the UI.

---

## 18. Status Bar

- Updates every 2 seconds.
- Shows current process memory usage in MB.
- If memory exceeds 2048 MB: shows a warning message.

---

## 19. Keyboard Shortcuts Summary

| Shortcut | Action |
|---|---|
| `Ctrl+O` | Open Folder |
| `Ctrl+Shift+V` | Open Video File |
| `Ctrl+S` | Save Project |
| `Ctrl+Shift+O` | Load Project |
| `Ctrl+P` | Frame/Sequence Export |
| `Ctrl+Shift+G` | Detect Shots |
| `Space` | Play/Pause |
| `Left Arrow` | Previous Frame |
| `Right Arrow` | Next Frame |
| `Home` | Jump to Start |
| `End` | Jump to End |
| `F` | Fit to Window |
| `Ctrl+=` | Zoom In |
| `Ctrl+-` | Zoom Out |
| `Ctrl+Q` | Exit |
| `Ctrl+Scroll` (on timeline) | Zoom timeline thumbnails |

---

## 20. Build/Distribution

The application can be packaged as a standalone Windows executable:
- Entry point: the main bootstrap script.
- Name: `KFPlayer`.
- Console: disabled (windowed mode).
- Excludes: torch, torchvision, transformers, gradio, pandas, matplotlib, jupyter.
- Includes: imageio FFmpeg data files, Google GenAI submodules.

---

## 21. Edge Cases and Special Behaviors

| Scenario | Behavior |
|---|---|
| No media loaded, try to export | Shows "No project loaded." warning |
| No bookmarks, try to export bookmarks | Shows "No bookmarks available to export." warning |
| Video file can't be opened | Shows error dialog with filepath |
| GIF with 0 duration | FPS defaults to 24 |
| Frame load failure during export | Raises an error, caught by export dialog |
| Start frame > end frame in export | Shows "Start frame must be before end frame." warning |
| Chunk size of 0 in WAN planning | Raises ValueError |
| Overlap value exceeding chunk size | Clamped to `chunk_size − 1` |
| Single frame clip in WAN planning | Returns one chunk padded to length 1 |
| Empty frames (total_frames = 0) in WAN planning | Returns empty list |
| Google API retries exhausted | Shows error with last exception details |
| Google file processing timeout | After 180 polls (6 minutes), raises TimeoutError |
| Empty Gemma response | Raises ValueError "Gemma returned an empty response." |
| Gemma response with no shots | Creates a single "Unspecified continuing shot." entry |
| Duplicate AI shots at same timestamp | Keeps the one with the longer description |
| Missing `.env` file | Silently skipped |
| Invalid JSON in `.env` | Lines without `=` are skipped |
| Export folder doesn't exist | Created automatically with `makedirs` |
| Window close | Stops play timer, stops auto-save timer, saves settings |

---

*This specification describes KFPlayer version 1.0 as of the analysis date. It covers all user-facing features, observable behaviors, data formats, and business rules without describing internal implementation details.*
