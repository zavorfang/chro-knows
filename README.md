# KFPlayer - Lightweight Animation Review Player

## 1. Project Overview

**Project Name**: KFPlayer  
**Type**: Desktop Application (Animation Review Tool)  
**Core Feature**: A minimal, fast animation review player for animators. Load videos and image sequences, scrub with frame accuracy, set bookmarks, export compressed MP4 clips, and export WAN 2.2-friendly chunked MP4s.  
**Target Users**: Animators and reviewers who need a lightweight, high-performance alternative to bloated media players.

## 2. UI/UX Specification

### 2.1 Window Layout

The application uses a vertical `QSplitter` to allow user-adjustable scaling of the main work area and the timeline.

```
┌─────────────────────────────────────────────────────────┐
│ Menu Bar (File, View, Playback, Help)                   │
├─────────────────────────────────────────────────────────┤
│ Tool Bar: [📂][|<][<][Play][>][>|] [Loop] [1x ▼] [Name] │
├─────────────────────────────────────────────────────────┤
│                                         │               │
│                                         │  Bookmarks    │
│            VIEWER (Top 90%)             │    Panel      │
│     (Pan/Zoomable Video Display)        │               │
│                                         │               │
├─────────────────────────────────────────┴───────────────┤
│ Overview Timeline (Nav Bar - Full Width Navigation)     │
├─────────────────────────────────────────────────────────┤
│ Timeline Playhead Handler (Vertical Splitter Separator) │
├─────────────────────────────────────────────────────────┤
│ Thumbnail Timeline (Bottom 10% - Scrollable)            │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Visual Design

**Color Palette**:
- Background Dark: `#1A1A1A`
- Panel Background: `#222222`
- Accent Blue: `#00A8FF`
- Text Primary: `#E0E0E0`
- Timeline Playhead: `#00FF88` (Green)
- Bookmarks: `#FF6B35` (Orange)

**UI Enhancements**:
- **Modern Styling**: Rounded corners (4px radius) on buttons, inputs, and panels.
- **Glassmorphism Influences**: Subtle hover states and border highlights.
- **Tooltips**: Descriptive tooltips on all toolbar buttons including keyboard shortcuts.
- **Styled Scrollbars**: Thin, rounded, dark scrollbars for a premium feel.

### 2.3 Components

**Viewer**:
- Pan: Left-Click + Drag (Fixed and fully functional)
- Zoom: Scroll Wheel
- Fit to Window: `F` key

**Overview Timeline**:
- **Global Navigation**: A thin bar representing the entire clip length.
- **Instant Seek**: Click or drag to jump to any percentage of the video instantly.
- **Bookmark Markers**: Visual indicators of all bookmarks across the full duration.

**Thumbnail Timeline**:
- **Dynamic Thumbnails**: Thumbnails scale vertically to fill the entire height of the timeline panel.
- **Auto-Scrolling**: The timeline automatically follows the playhead during playback and scrubbing.

**Bookmarks Panel**:
- Jump: Click any bookmark in the list to jump to that frame.
- **Delete**: Right-click a bookmark in the list to remove it.

## 3. Functional Specification

### 3.1 Core Features

**Source Loading**:
- **Drag and Drop**: Drag folders, videos, or images directly onto the app.
- **Dynamic Title**: Window title and toolbar label update to show the loaded file/folder name.

**Export**:
- **MP4 Export**: H.264 export with integrated Quality and Speed control.
- **Compression**: User-selectable Quality (1-10) mapping to FFMPEG CRF.
- **Performance**: Speed Presets (**ultrafast**, **fast**, **medium**, **slow**) to optimize encoding time.
- **WAN 2.2 Chunk Export**: Export long videos as multiple MP4 chunks tailored to WAN-safe frame counts.
- **Chunk Controls**: User-selectable chunk size with WAN-safe snapping and optional chunk overlap.
- **Tail Handling**: Rebalance the last two chunks to avoid extremely short trailer clips, and only pad the final chunk when required.

## 4. Technical Implementation

**Core Technologies**:
- **Framework**: PyQt6
- **Video Decoding**: OpenCV (cv2) for frame-accurate playback and thumbnail extraction.
- **Video Encoding**: `imageio` with `imageio-ffmpeg` plugin for high-performance H.264 export with custom presets.
- **Image Processing**: Pillow (PIL) and NumPy for matrix manipulation and format conversion.
- **System Monitoring**: `psutil` for real-time memory tracking in the status bar.

**Architecture**:
- **Main Window**: `MainWindow` (ui_main.py) - Central coordinator.
- **Viewer**: `ViewerWidget` (viewer.py) - Custom widget for hardware-accelerated QPixmap rendering with Pan/Zoom support.
- **Overview Timeline**: `OverviewTimelineWidget` (timeline.py) - Thin global navigation control.
- **Thumbnail Timeline**: `TimelineWidget` (timeline.py) - Scrollable detail scrub bar.
- **Project Data**: `Project` (project.py) - JSON-backed state management.
- **WAN Chunk Planner**: `wan_chunks.py` - Pure planning logic for WAN-safe chunk sizing, overlap normalization, and final-tail balancing.

### 4.2 Encoding Parameters
- **Codec**: `libx264` (H.264) via FFMPEG backend.
- **Compression**: User-selectable CRF (Constant Rate Factor) ranging from 15 (High Quality) to 35 (Small Size).
- **Speed Presets**: FFMPEG presets (**ultrafast**, **fast**, **medium**, **slow**) to balance encoding time and file efficiency.

### 4.3 WAN Export Rules
- **WAN-Safe Frame Counts**: Valid WAN lengths follow the pattern `(x * 4) + 1`.
- **Chunk Size Snapping**: User-entered chunk sizes are snapped down to the nearest WAN-safe value.
- **Example**: `88` snaps to `85`.
- **Short Clips**: If a clip is shorter than one chunk, export a single chunk and pad only the final frame count up to the next WAN-safe length.
- **Final Two Chunks**: If the remaining span fits inside a two-chunk window, rebalance those last two chunks instead of leaving a tiny final trailer.
- **Padding Rule**: Only the final chunk may be padded, using repetition of the last frame within the user's selected range. Padding never reads frames beyond the selected end frame.
- **Overlap**: Optional overlap is supported between chunks. Overlap is applied by moving the next chunk backward so it shares frames with the end of the previous chunk.
- **Overlap Range**: Current supported overlap range is `4` to `32` frames.

### 4.4 Current WAN Export UI
- **Entry Point**: File menu action for WAN 2.2 chunk export.
- **Controls**:
  - output folder
  - filename prefix
  - chunk size input
  - overlap toggle and overlap amount
  - quality slider
  - speed preset
- **Preview**: The dialog previews planned WAN-safe chunk lengths, raw source chunk lengths, overlap state, and whether final padding is required.

## 5. Acceptance Criteria

1. ✅ **Dynamic UI**: Timeline at the bottom, adjustable via splitter, with vertically scaling thumbnails.
2. ✅ **Navigation**: Both detailed (thumbnail) and global (overview) timelines synced.
3. ✅ **Performance**: Export speed control (ultrafast) significantly reduces wait times.
4. ✅ **Compatibility**: MP4 exports are small and highly compatible across OS and node-based software.
5. ✅ **UX**: Drag-and-drop support for all media types, tooltips on all buttons, and dynamic window titles.
6. ✅ **Stability**: No more memory-padding crashes during export (reshape handling fixed).
7. ✅ **Quality**: Viewer pan and zoom work flawlessly and preserve aspect ratio.
8. ✅ **WAN Export**: Long videos can be exported as WAN-safe MP4 chunks with controllable chunk size.
9. ✅ **Tail Quality**: WAN chunking avoids unusably short tail clips by rebalancing the final two chunks.
10. ✅ **Padding Integrity**: Only the final WAN chunk is padded, preserving continuity in intermediate chunks.
11. ✅ **Overlap Control**: WAN export supports optional overlap between chunks with preview feedback.

## 6. Deployment
- **Executable**: `run_kfplayer.bat` provides a convenient launcher for Windows environments, activating the virtual environment and running the player without a persistent console window.
