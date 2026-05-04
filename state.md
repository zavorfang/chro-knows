# KFPlayer Project State

This document is the definitive technical summary of the project's current implementation. It supersedes the high-level goals in [README.md](README.md).

## 1. Project Summary

- **App Name**: `KFPlayer` (UI title: `Keyframe Pro Lite`).
- **Tech Stack**: Python 3.x, PyQt6, OpenCV (`cv2`), `imageio`, `numpy`.
- **Core Purpose**: A lightweight, high-performance animation review tool for scrubbing video/image sequences, bookmarking, and specialized "Wan" preparation.

## 2. The "Wan Preparation" Feature (Core Logic)

The most complex part of the app is the **Wan Preparation** tool. It prepares video chunks and visual grid sheets for machine learning or animation review workflows.

### 2.1 Chunking Rules (`wan_chunks.py`)
- **WAN-Safe Lengths**: All chunks must have a frame count following `(x * 4) + 1` (e.g., 1, 5, 9, 13, 85, 89, 93).
- **Snapping**: User-requested chunk sizes are snapped **down** to the nearest safe value.
- **Tail Handling**: If the final few frames would create a "tiny" trailer, the logic rebalances the last two chunks to ensure both are substantial.
- **Padding**: Only the **final chunk** in an export is padded (by repeating the last frame within the selected range) to reach a WAN-safe length. Intermediate chunks are never padded. The frame range is clamped to the user's selected end frame — padding never reads frames beyond the selected shot boundary.
- **Overlap Rules**: Overlap is optional (current range 4..32). It is modeled by moving the next chunk backward so it shares frames with the previous chunk (i.e., overlap happens at the start of a later chunk and at the end of the earlier chunk). Overlap changes the stride, meaning chunk counts and final distribution may change.

### 2.2 Example Behaviors
- **Snapping**: `chunk size 88` becomes `85`.
- **Short Clips**: A `10`-frame clip becomes one chunk padded to `13`.
- **Tail Balancing**: A clip that would end as `85, 85, 85, 5` rebalances the last two chunks instead of leaving a tiny trailer.
- **258 Frames @ 85**: Raw lengths: `85, 85, 45, 43` -> Target lengths: `85, 85, 45, 45`.

### 2.3 Intelligent Grid Generation
- **Grid Sizes**: Supports `2x2` (4 slots) and `3x3` (9 slots).
- **Frame Selection**: Extracts `3` to `5` frames per chunk by default (First, Middle(s), Last).
- **Waste Elimination**: The algorithm dynamically calculates "missing" frames to ensure no black squares appear in the grid. It injects extra middle frames into earlier chunks until the grid is perfectly filled.
- **"One Grid Per Chunk" Mode**: A toggle that forces a 1:1 ratio. In this mode, exactly `cap` (4 or 9) frames are extracted per chunk so each chunk gets its own full grid image.

### 2.3 Metadata Export (JSON)
- **Priority**: The JSON output is structured to put the most important info (`chunk 1`, `chunk 2`, etc.) at the top.
- **Normalized Frames**: Frame indices for each chunk are **normalized to 0** (relative to the chunk start).
- **Contents**: Includes absolute start/end frames, grid dimensions, and full chunking data.

## 3. Architecture Map

### Critical Files
- [ui_main.py](ui_main.py): The "Hub". Contains the main window, all Dialog classes, and the heavy-lifting `prepare_wan` method.
- [wan_chunks.py](wan_chunks.py): Pure mathematical logic for planning WAN-safe chunks.
- [timeline.py](timeline.py): Manages the dual-timeline system.
- [viewer.py](viewer.py): Handles rendering, Pan, and Zoom.
- [project.py](project.py): State management for loaded media and bookmarks.

## 4. Workflows & Rules for Agents

### 4.1 UI Conventions
- Use `QFormLayout` for dialogs to maintain a clean, consistent look.
- Use `QProgressBar` and `QApplication.processEvents()` during long exports.
- Quality sliders map to **CRF**: 10 is near-lossless, 35 is highly compressed.

### 4.2 Data Integrity
- **Filenames**: Sanitize prefixes using `sanitize_filename_part`.
- **JSON**: Dump metadata with `indent=4`. Use `asdict` for dataclasses.
- **Coordinates**: Ensure overlays account for the viewer's transformation matrix.

### 4.3 Adding New Features
1. **Math First**: Update `wan_chunks.py` and `test_wan_chunks.py`.
2. **Dialog Second**: Create a new `QDialog` class in `ui_main.py`.
3. **Integration**: Add trigger method in `ViewerWidget`.

## 5. Known Implementation Details
- Uses **OpenCV** for reading, **imageio** for writing.
- Memory monitoring via `psutil`.
- Grid images are **95% quality JPEGs**.

## 6. Test Coverage
Tests in [test_wan_chunks.py](test_wan_chunks.py) cover:
- WAN ceil/floor snapping and normalization.
- Short clip padding and final-chunk-only padding.
- Balanced final two chunks and overlap-aware planning.

**Representative cases**: `88 -> 85`, `100f @ 88`, `186f @ 93`, `258f @ 85` (with and without overlap).
