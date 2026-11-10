# KFPlayer Project State

This document is the definitive technical summary of the project's current implementation. It supersedes the higher-level goals in [README.md](README.md).

## 1. Project Summary

- **App Name**: `KFPlayer` (UI title: `Keyframe Pro Lite`).
- **Tech Stack**: Python 3.x, PyQt6, OpenCV (`cv2`), imageio, Pillow, numpy, psutil, Google GenAI SDK (`google-genai`) for Gemma integration.
- **Core Purpose**: A lightweight animation review tool for scrubbing video/image sequences, bookmarking, exporting stills and video, building per-shot contact-sheet grids, preparing WAN-safe chunks, and detecting hard-cut shot boundaries with Gemma 4 plus traditional cut analysis.

## 2. Current Major Features

### 2.1 Playback / Review
- Supports videos and image sequences.
- Dual timeline system:
  - `OverviewTimelineWidget`: thin full-length navigation bar.
  - `TimelineWidget`: scrollable thumbnail timeline.
- **Real-Time Playback Engine**:
  - Persistent OpenCV `VideoCapture` session: eliminates per-frame `open/set/read/release` overhead (reducing per-frame read time from ~50–100ms down to 1–2ms).
  - High-precision wall-clock synchronization via `time.perf_counter()`: keeps video playhead locked to real time regardless of decode load, preventing cumulative timer drift.
  - Variable playback speed (`0.25x`, `0.5x`, `1x`, `2x`) with immediate clock re-anchoring.
- **Integrated Audio Playback**:
  - Powered by `PyQt6.QtMultimedia` (`QMediaPlayer` + `QAudioOutput`).
  - Probes audio streams on load via `ffprobe`; automatically enables audio features when audio is present.
  - Toolbar mute button (`🔊`/`🔇`) with single-key shortcut (`M`), auto-disabled when source has no audio track.
  - Playback speed changes dynamically adjust `QMediaPlayer.setPlaybackRate()` for synchronized audio.
  - Seeks, jumps, and loop wrap-around remain sample-accurate.
  - Preferences dialog includes master audio toggle and volume slider.

### 2.2 Bookmarking
- Bookmarks are stored as frame-indexed entries with name/color metadata.
- **Fixed-size icon-only buttons**: The bookmark panel features fixed-size icon-only buttons (`+`, `−`, `🗑`) at 28x28px, eliminating text shifts and panel resizing jitter across adjacent panels.
  - `+` (Add): Adds a bookmark at the current frame (enabled when the current frame has no bookmark).
  - `−` (Remove): Removes the bookmark at the current frame (enabled when the current frame has a bookmark).
  - `🗑` (Clear All): Deletes all bookmarks after confirmation (enabled when bookmarks exist).
- **Timeline selection & drag editing**:
  - Bookmarks on both `TimelineWidget` and `OverviewTimelineWidget` are clickable and selectable, rendered with a crisp white highlight ring.
  - Hovering a bookmark switches the cursor to pointing hand cursor.
  - Dragging a selected bookmark moves its position smoothly along the timeline with ghost marker and active preview.
  - Dropping commits the new position, syncs across both timelines, jumps the playhead to the new frame, updates the bookmark list, and prevents collisions (snaps back if destination already has a bookmark).
  - **Granular arrow key nudge control**:
    - When a bookmark is selected on the timeline: `Left` or `Down` arrow moves the bookmark backward by 1 frame (-1); `Right` or `Up` arrow moves it forward by 1 frame (+1).
    - When a bookmark is selected in the Bookmark panel list: `Left` and `Right` arrow keys nudge it backward/forward by 1 frame.
    - Global shortcuts: `Alt+Left` and `Alt+Right` nudge the selected bookmark earlier/later from anywhere in the app; pressing `Up`/`Down` in the main window also nudges the selected bookmark by ±1 frame.
    - Pressing `Escape` deselects the bookmark.
    - Bound limits (`0..total_frames-1`) and collisions are enforced with status bar alerts.
  - Bidirectional sync: clicking a bookmark in the panel highlights it on the timeline; selecting/clicking a bookmark on the timeline highlights it in the panel and seeks the playhead.
  - Removed hover-to-update text coupling, ensuring completely stable panel layout and smooth UX.
- Right-click bookmark context menu supports exporting a single bookmark image, exporting bookmarks, deleting one bookmark, and deleting all bookmarks.

### 2.3 Export UI
- `File -> Export` is now a submenu that groups export actions instead of listing them flat in `File`.
- **Audio Preservation & Uniform Toggle**:
  - Every dialog that produces an MP4 (`Export MP4`, `Wan Preparation`, `MiniMax H3 Preparation`, and `Export Bookmarks Video`) features a uniform **"Include Audio"** checkbox.
  - Automatically enabled and checked if the source video contains an audio stream; disabled with an informative hint label if the source lacks audio or is an image sequence.
  - Sub-clip audio is extracted and muxed via FFmpeg (`-c:v copy -c:a aac -b:a 192k`). For padded chunks, audio is padded with silence (`apad`) to match the exact target video duration.
- Bookmark export is unified into a single dialog:
  - `Image Sequence` mode for still exports.
  - `Video` mode for stitched bookmark MP4 export.
- Bookmark video export reuses the existing H.264 writer and repeats each bookmarked frame for a user-configurable hold duration at a user-configurable export FPS.
- **Shot Grids** (`File -> Export -> Shot Grids...`) writes one fully filled grid image per bookmarked shot, or several equal grids for long shots:
  - Default sampling interval 4, with 2/4/8/12/24 chips and a 1–120 free field.
  - Max grid 3×3, 4×4 or 5×5, square by default; optional compact rectangles.
  - Fit strategies: Balanced (default), Trim (never add frames) and Fill (never drop frames).
  - Live shot table with per-shot checkboxes, frame range, length, samples, planned layout and real spacing; custom range and In/Out range when timeline points exist.
  - Long sides default to 2048 px; cells keep the source aspect ratio; optional gaps, burned frame numbers, per-shot subfolders, individual frames, manifest and splitter sidecars.
  - Export runs on a worker thread with progress and cancel; settings persist under `shot_grid`.

### 2.4 Wan Preparation
- The WAN preparation workflow prepares chunks conforming to $(4k + 1)$ frames.
- Requested chunk size snaps down to the nearest WAN-safe size (default 93).
- Only the final chunk may be padded by repeating the last valid frame.
- Overlap is optional and constrained to `4..32` frames.
- Tail balancing avoids tiny final trailer chunks.
- Grid generation supports dynamic `2x2` / `3x3` contact sheets with waste elimination.
- Includes uniform "Include Audio" checkbox for audio muxing with trailing silence padding.
- **Frame Review**: After chunking, `WanFrameReviewDialog` allows visual inspection and slider-based replacement of selected keyframes before final export.

### 2.5 MiniMax H3 Preparation
- Accessed via `File -> Export -> MiniMax H3 Preparation...`.
- Designed specifically for MiniMax H3 / Hailuo 03 model constraints.
- **Frame Structure Constraint**: Every chunk must land on a valid $(17k + 5)$ boundary for $k \ge 0$:
  `{5, 22, 39, 56, 73, 90, 107, 124, 141, 158, 175, 192, 209, 226, 243, ...}`.
- **Ceiling Snapping Formula**:
  $$\text{snap\_ceil}(n) = n + \left(5 - (n \bmod 17)\right) \bmod 17 \quad (\min 5)$$
- **Trailing-Frame Padding**: Any clip or chunk that falls short of a chunk boundary is padded by repeating the last frame of the video up to the target length.
- **Default Chunk Size**: 124 frames ($\approx 5.17$ seconds at 24 FPS).
- **Overlap**: Snapped to multiples of 17 (range 17 to 51 frames, default 17).
- **Interactive Keyframe Review**: Reuses the interactive visual review dialog before committing to disk.
- **Export Bundle**:
  - Dedicated subdirectories: `<prefix>_chunk_<idx:03d>/`.
  - Chunk MP4s: `<prefix>_minimax_h3_<idx:03d>_<target_len:03d>f_<start:04d>-<end:04d>.mp4`.
  - Individual keyframe JPEGs, 1 FPS keyframe MP4 preview, contact-sheet grids (`compose_grid`).
  - Metadata manifest: `<prefix>_minimax_h3_preparation.json`.
  - Audio muxing with silence padding matching the target chunk duration.
- Implementation lives in [minimax_chunks.py](minimax_chunks.py) and [ui_main.py](ui_main.py).

### 2.6 Smart Grid Splitter
- Accessed via `File -> Export -> Smart Grid Splitter...`.
- Takes a video chunk, JSON metadata, and a colorized grid image as input.
- A setup dialog lets the user pick the chunk to work with.
- The splitter viewport loads the video but restricts navigation to only the frames used to build the grid (from the JSON metadata).
- Reads both legacy square metadata (`grid_dim`) and shot-grid sidecars (`grid_rows`, `grid_cols`, `grid_gap`, `cell_width`, `cell_height`).
- The grid image is overlaid on the video frame and auto-positioned using cell-based offset calculation (`col = i % grid_cols`, `row = i // grid_cols`, offset by cell size plus gap).
- The overlay auto-scales so one grid cell matches the source frame; the scale slider still allows manual adjustment.
- Controls: opacity slider, scale slider (10–1000%), aspect-ratio lock toggle.
- The grid position can be manually adjusted by click-dragging. Manual nudge persists across forward/backward navigation.
- Export crops each grid cell, accounting for rectangular layouts, gaps and scale, and saves it aligned to the original video resolution.
- Implementation lives in [grid_splitter.py](grid_splitter.py).

## 3. Gemma Shot Detection

### 3.1 Goal
- Detect **hard-cut** shot boundaries, not camera-motion changes inside one continuous take.
- Avoid false positives from zooms, pans, tilts, dollies, reframing, rack focus, or subject movement.

### 3.2 High-Level Pipeline
- Entry point: `File -> Detect Shots with Gemma...`
- The selected range is split into **59-second chunks** to stay under the model’s practical video request limit.
- Each chunk is encoded to a temporary MP4 and analyzed by **Gemma 4 only** (`gemma-4-31b-it` or `gemma-4-26b-a4b-it`).
- A traditional dense cut scan runs locally across the selected frame range.
- Gemma’s chunk-level shot guesses are aligned to the nearest traditional cut candidates.
- Chunk seams are reconciled with Gemma image validation so split shots are not double-counted.
- Strong unmatched traditional cut candidates are re-checked with Gemma image validation and can be promoted to final shot boundaries.

### 3.3 Hard-Cut Rules
- Internal Gemma shot guesses are no longer trusted on their own.
- A Gemma-inferred internal shot boundary is kept only if it aligns closely with a traditional cut candidate.
- Validation prompts explicitly tell Gemma:
  - treat only real edits / hard cuts as boundaries
  - do not split a shot because framing changes continuously inside the same take

### 3.4 Outputs
- Writes:
  - `*_gemma_shots.txt`
  - `*_gemma_shots.json`
- Can optionally add detected shots as bookmarks.

### 3.5 API / Reliability
- Uses the Google GenAI SDK.
- Startup loads `.env` from the repo root.
- Blank API key field in the dialog falls back to:
  - `GOOGLE_API_KEY`
  - or `GEMINI_API_KEY`
- A dummy placeholder key in `.env` is intentionally rejected with a clear warning.
- Gemma upload, processing polling, and generation calls now retry automatically on transient Google `500 INTERNAL` errors with backoff.

## 4. Important Files

- [ui_main.py](ui_main.py): main window, dialogs, export flows, Gemma shot detection, bookmark controls.
- [shot_grid.py](shot_grid.py): pure shot-grid planner (fit strategies, layouts, frame selection).
- [shot_grid_render.py](shot_grid_render.py): thread-safe frame readers, cell sizing, contact-sheet composition and image writing.
- [shot_grid_export.py](shot_grid_export.py): Qt-free shot-grid export, manifest and sidecars.
- [shot_grid_dialog.py](shot_grid_dialog.py): shot-grid preview dialog, settings and worker thread.
- [gemma_shot_detection.py](gemma_shot_detection.py): pure shot-detection helpers, chunk planning, candidate matching, seam merge logic, timestamp formatting.
- [timeline.py](timeline.py): overview and thumbnail timelines, bookmark hover detection.
- [wan_chunks.py](wan_chunks.py): WAN-safe chunk math.
- [minimax_chunks.py](minimax_chunks.py): MiniMax H3 $(17k + 5)$ chunk math and trailing-frame padding logic.
- [app_utils.py](app_utils.py): filename helpers, recent-file helpers, export naming utilities, audio stream probing and FFmpeg audio muxing.
- [grid_splitter.py](grid_splitter.py): Smart Grid Splitter dialog, viewport compositing, cell-based position calculation, and split export.
- [main.py](main.py): app bootstrap and `.env` loading.

## 5. Implementation Details

- Uses OpenCV for decoding / frame comparison and imageio for MP4 writing.
- Persistent OpenCV VideoCapture session for high-speed sequential playback (~1–2ms per frame).
- Real-time AV playback engine with `time.perf_counter()` clock-sync and `PyQt6.QtMultimedia` audio backend.
- Shot detection contact sheets are rendered with Pillow and sent to Gemma as images for validation.
- Project save/load supports both folder-based sources and direct video sources.
- Bookmark video export and regular MP4 export share the same H.264 writer path.
- Memory monitoring is displayed in the status bar via `psutil`.

## 6. Tests

The test suite contains 130 passing tests:

- [test_minimax_chunks.py](test_minimax_chunks.py):
  - MiniMax $(17k + 5)$ ceiling and floor snapping
  - boundary conditions and minimum 5 frames
  - single-chunk, two-chunk, and multi-chunk planning
  - overlap normalization and stride alignment
  - trailing-frame padding verification
- [test_minimax_export.py](test_minimax_export.py):
  - MiniMax preparation directory creation, chunk videos, keyframe stills, 1 FPS previews, and JSON manifest
  - dialog defaults and audio toggle validation
- [test_audio_export.py](test_audio_export.py):
  - audio stream probe edge cases
  - toolbar mute button toggle and icon state
  - playback rate synchronization on speed changes
  - uniform "Include Audio" export checkbox and hint text validation
- [test_wan_chunks.py](test_wan_chunks.py):
  - WAN snapping
  - overlap normalization
  - short clip padding
  - balanced final chunks
- [test_app_utils.py](test_app_utils.py):
  - export filename helpers
  - shot-grid filename helper
  - recent file normalization
- [test_shot_grid.py](test_shot_grid.py):
  - sample counts and layout table
  - worked examples and strategy comparisons
  - frame-choice rules
  - 100,800-combination invariant sweep
- [test_shot_grid_render.py](test_shot_grid_render.py):
  - cell sizing for landscape/portrait/native
  - row-major rendering, gaps, padding
  - image write round trip
- [test_shot_grid_export.py](test_shot_grid_export.py):
  - image/manifest/sidecar output
  - individual frames and subfolders
  - cancellation and missing-frame handling
  - range clipping
- [test_shot_grid_dialog.py](test_shot_grid_dialog.py):
  - live table, row checkboxes and custom range
  - interval/layout/settings flow
  - main-window media description and export hand-off
- [test_grid_splitter.py](test_grid_splitter.py):
  - rectangular sidecar geometry, gaps and auto scale
  - split export/crop correctness
- [test_gemma_shot_detection.py](test_gemma_shot_detection.py):
  - 59-second chunk planning
  - JSON response parsing
  - cut candidate extraction
  - candidate alignment
  - seam-merge behavior
  - final timestamp formatting
