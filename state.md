# KFPlayer Project State

This document is the definitive technical summary of the project's current implementation. It supersedes the higher-level goals in [README.md](README.md).

## 1. Project Summary

- **App Name**: `KFPlayer` (UI title: `Keyframe Pro Lite`).
- **Tech Stack**: Python 3.x, PyQt6, OpenCV (`cv2`), imageio, Pillow, numpy, psutil, Google GenAI SDK (`google-genai`) for Gemma integration.
- **Core Purpose**: A lightweight animation review tool for scrubbing video/image sequences, bookmarking, exporting stills and video, preparing WAN-safe chunks, and detecting hard-cut shot boundaries with Gemma 4 plus traditional cut analysis.

## 2. Current Major Features

### 2.1 Playback / Review
- Supports videos and image sequences.
- Dual timeline system:
  - `OverviewTimelineWidget`: thin full-length navigation bar.
  - `TimelineWidget`: scrollable thumbnail timeline.
- Frame-accurate seeking, pan/zoom viewer, looping, playback speed control.

### 2.2 Bookmarking
- Bookmarks are stored as frame-indexed entries with name/color metadata.
- The bookmark panel now includes:
  - `+ Add Bookmark` / `- Remove Bookmark` contextual button.
  - `Clear Bookmarks` button for deleting all bookmarks at once.
- Hovering a bookmark marker on either timeline changes the main bookmark button into a remove action for that hovered bookmark.
- Right-click bookmark context menu supports exporting a single bookmark image, exporting bookmarks, deleting one bookmark, and deleting all bookmarks.

### 2.3 Export UI
- `File -> Export` is now a submenu that groups export actions instead of listing them flat in `File`.
- Bookmark export is unified into a single dialog:
  - `Image Sequence` mode for still exports.
  - `Video` mode for stitched bookmark MP4 export.
- Bookmark video export reuses the existing H.264 writer and repeats each bookmarked frame for a user-configurable hold duration at a user-configurable export FPS.

### 2.4 Wan Preparation
- The WAN preparation workflow remains the most mature export pipeline.
- All chunks must follow `(x * 4) + 1`.
- Requested chunk size snaps down to the nearest WAN-safe size.
- Only the final chunk may be padded.
- Overlap is optional and currently constrained to `4..32` frames.
- Tail balancing avoids tiny final trailer chunks.
- Grid generation supports:
  - dynamic `2x2` / `3x3`
  - waste elimination
  - one-grid-per-chunk mode
- **Frame Review**: After chunking, a `WanFrameReviewDialog` shows all auto-selected grid frames grouped by chunk. The user can accept or click any thumbnail to open a `WanFramePickerDialog` slider to pick a replacement frame from that chunk's range. Export only proceeds after explicit approval.

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
- [gemma_shot_detection.py](gemma_shot_detection.py): pure shot-detection helpers, chunk planning, candidate matching, seam merge logic, timestamp formatting.
- [timeline.py](timeline.py): overview and thumbnail timelines, bookmark hover detection.
- [wan_chunks.py](wan_chunks.py): WAN-safe chunk math.
- [app_utils.py](app_utils.py): filename helpers, recent-file helpers, export naming utilities.
- [main.py](main.py): app bootstrap and `.env` loading.

## 5. Implementation Details

- Uses OpenCV for decoding / frame comparison and imageio for MP4 writing.
- Shot detection contact sheets are rendered with Pillow and sent to Gemma as images for validation.
- Project save/load supports both folder-based sources and direct video sources.
- Bookmark video export and regular MP4 export share the same H.264 writer path.
- Memory monitoring is displayed in the status bar via `psutil`.

## 6. Tests

- [test_wan_chunks.py](test_wan_chunks.py):
  - WAN snapping
  - overlap normalization
  - short clip padding
  - balanced final chunks
- [test_app_utils.py](test_app_utils.py):
  - export filename helpers
  - recent file normalization
- [test_gemma_shot_detection.py](test_gemma_shot_detection.py):
  - 59-second chunk planning
  - JSON response parsing
  - cut candidate extraction
  - candidate alignment
  - seam-merge behavior
  - final timestamp formatting
