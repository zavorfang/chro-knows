# KFPlayer - Lightweight Animation Review Player

## 1. Overview

**KFPlayer** is a PyQt6 desktop review tool for animators and editors who need fast frame-accurate playback, timeline bookmarks, export tools, per-shot contact-sheet grids, WAN-safe chunk preparation, and Gemma-powered hard-cut shot detection.

It supports:
- video files
- image sequences
- bookmark still export
- bookmark video export
- per-shot grid image export
- general MP4 export
- WAN 2.2-style chunk export
- Gemma 4 shot detection with timestamp output

## 2. Main Features

### 2.1 Review Workflow
- Load videos or image-sequence folders.
- Scrub frame-accurately.
- Use a dual-timeline layout:
  - overview bar for global navigation
  - thumbnail timeline for detailed scrubbing
- Pan and zoom the viewer.

### 2.2 Bookmarks
- Add bookmarks at the current frame.
- Remove bookmarks individually or clear all bookmarks.
- Hovering a bookmark marker on the timeline changes the main bookmark button into a remove action for that hovered bookmark.
- Bookmarks can be exported through one unified export dialog.

### 2.3 Export
All export actions now live under `File -> Export`.

Available export paths:
- frame / sequence export
- current / first / last frame image export
- bookmark export
- shot-grid export
- MP4 export
- WAN preparation export

Bookmark export is unified:
- `Image Sequence` mode exports bookmark stills.
- `Video` mode exports a stitched MP4 reel with configurable hold duration, FPS, quality, and speed preset.

### 2.4 Shot Grids

`File -> Export -> Shot Grids...` treats each bookmark as the start of a shot and writes a fully filled contact sheet for every shot.

- Sampling interval defaults to 4 frames, with 2/4/8/12/24 chips and a custom value.
- Grids snap to 3×3, 4×4 or 5×5 (square by default; compact rectangles optional) so no cell is left black.
- Long shots split into multiple equal grids instead of becoming unreadably dense.
- Balanced, Trim and Fill strategies control whether frames are dropped or added to complete a grid.
- The live shot table shows frames, length, samples, grid layout and real spacing; each shot can be excluded.
- Output options include PNG/JPEG/TIFF, 2048 px grids, gaps, burned frame numbers, per-shot subfolders, individual frames, a manifest and Smart Grid Splitter sidecars.
- Export runs in a worker thread and remembers its settings.

### 2.5 WAN Preparation
WAN preparation is designed for long clips that need WAN-safe chunk sizes.

Key rules:
- valid chunk lengths follow `(x * 4) + 1`
- requested sizes snap down to the nearest valid size
- only the final chunk may be padded
- overlap is optional
- short trailing chunks are rebalanced to avoid tiny tails

It can also generate contact-sheet grids and JSON metadata for selected chunk frames.

### 2.6 Gemma Shot Detection
The app includes a `Detect Shots with Gemma...` dialog for hard-cut detection.

Pipeline summary:
- split the selected range into **59-second chunks**
- analyze each chunk with **Gemma 4 only**
- run a traditional frame-difference cut scan locally
- snap Gemma’s internal boundaries to traditional cut candidates
- validate chunk seams and strong unmatched candidates with Gemma image checks
- output:
  - `*_gemma_shots.txt`
  - `*_gemma_shots.json`

The prompts are tuned for **true edit boundaries**, not framing changes within one take. Zooms, pans, tilts, dollies, reframing, focus changes, and subject movement should not create a new shot by themselves.

## 3. API Key Setup

Gemma detection uses the Google GenAI SDK.

The app loads a local `.env` file at startup and uses either:
- `GOOGLE_API_KEY`
- `GEMINI_API_KEY`

If the Detect Shots dialog API field is left blank, KFPlayer falls back to those environment values automatically.

The repo includes a dummy `.env` placeholder. Replace it with your real Google AI Studio key before using Gemma detection.

## 4. Reliability Notes

- Gemma upload, file-processing polling, and generation calls retry automatically on transient Google `500 INTERNAL` server errors.
- If Gemma is unavailable after retries, the app shows a clearer failure message instead of a raw exception.

## 5. Tech Stack

- Python 3.x
- PyQt6
- OpenCV
- imageio / imageio-ffmpeg
- Pillow
- numpy
- psutil
- google-genai

## 6. Key Files

- [main.py](main.py): app bootstrap and `.env` loading
- [ui_main.py](ui_main.py): UI, dialogs, exports, Gemma shot detection
- [shot_grid.py](shot_grid.py): pure shot-grid planning
- [shot_grid_render.py](shot_grid_render.py): frame readers and grid composition
- [shot_grid_export.py](shot_grid_export.py): shot-grid export, manifest and sidecars
- [shot_grid_dialog.py](shot_grid_dialog.py): shot-grid dialog and worker
- [grid_splitter.py](grid_splitter.py): Smart Grid Splitter
- [timeline.py](timeline.py): overview and thumbnail timeline widgets
- [gemma_shot_detection.py](gemma_shot_detection.py): pure shot-detection logic
- [wan_chunks.py](wan_chunks.py): WAN-safe chunk planning logic

## 7. Running

Use [run_kfplayer.bat](run_kfplayer.bat) on Windows, or run `main.py` from the project environment.
