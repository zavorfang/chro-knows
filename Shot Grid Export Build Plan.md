# Shot Grid Export: Build Plan

Nov 4, 2026 · @lord mo

## Goal and what to reuse

Add **File → Export → Shot Grids…** to KFPlayer: for every bookmarked shot it writes one grid image (or a few, for long shots) with every cell filled, using the frame interval you pick.

This plan was written from the README, `state.md`, the functional spec, `project.py`, `wan_chunks.py` and `grid_splitter.py`, then audited against the full `ui_main.py` before the build. The audit corrected three assumptions: there is no user-facing In/Out range editor in the main window (only timeline point attributes), WAN preparation has no fixed grid size to inherit, and the Qt `QPixmap` loader must not be used from the export worker.

- **Bookmarks**: `{frame, name, color}` entries with 0-based frames (the UI shows frame + 1). Gemma shot detection already adds shots as blue bookmarks, so detect → bookmark → shot grids needs no extra glue.
- **Export patterns**: the `File → Export` submenu and the unified bookmark export dialog (folder, prefix, PNG/JPEG/TIFF, JPEG quality). Copy its controls and use the filename helpers in `app_utils.py`.
- **Grid composing**: WAN preparation already builds contact-sheet JPEGs plus a JSON manifest. Find that composer in `ui_main.py` and extract it into a shared function instead of writing a second one.
- **Frame loading**: use the main window's frame loader for GIFs and image sequences; for video, read each shot's frames in ascending order from one capture (Phase 2). Do not copy `_load_video_frame` from `grid_splitter.py`; it reopens the video for every frame.
- **Repo conventions**: pure logic in its own module with a `test_*.py` beside it (like `wan_chunks.py`), dialogs may live in their own file (like `grid_splitter.py`), and `state.md` plus `kfplayer_functional_specification.md` are updated when a feature lands.

## Build status (Nov 4, 2026)

All six phases are implemented and covered by the test suite.

- **Planner**: `shot_grid.py` with validation, `test_shot_grid.py` (including a 100,800-combination invariant sweep).
- **Renderer and readers**: `shot_grid_render.py` with dedicated video/GIF/sequence readers, aspect-preserving cell sizing, row-major composition, gaps, optional frame labels, and the shared `compose_grid` used by WAN preparation.
- **Export pipeline**: `shot_grid_export.py` (Qt-free), including per-shot planning, image naming, individual frames, manifest, Smart Grid Splitter sidecars, cancellation, and per-shot read-error reporting.
- **Dialog and menu**: `shot_grid_dialog.py` (live shot table, settings, worker thread, progress and summary) wired to `File → Export → Shot Grids...` in `ui_main.py`.
- **Round trip**: `grid_splitter.py` now reads `grid_rows`, `grid_cols`, `grid_gap`, `cell_width`, and `cell_height`, auto-scales the overlay so one cell matches the source frame, and crops rectangular/gapped grids correctly.
- **Tests**: `test_shot_grid.py`, `test_shot_grid_render.py`, `test_shot_grid_export.py`, `test_shot_grid_dialog.py`, `test_grid_splitter.py`, plus the existing suite.

Synthetic verification (205-frame 32×24 sequence, bookmarks at frames 0/10/75, interval 4, 5×5 max):

- Shot 1 (10 frames, 3 samples) → one 2×2 grid.
- Shot 2 (65 frames, 17 samples) → one 4×4 grid with one lattice frame dropped.
- Shot 3 (130 frames, 33 samples) → two 4×4 grids.
- Four images total, zero empty cells, manifest and sidecars written, all cell colours matched the expected source frames.

Corrections made during the audit:

- The range control is **Whole clip** (default), **In/Out** when both timeline points exist, or **Custom range**. The plan originally promised an In/Out UI that the app does not have.
- The new grid's longest side defaults to **2048 px**. WAN preparation does not use a fixed grid size, so there was nothing to inherit.
- Rendering and export live in `shot_grid_render.py` and `shot_grid_export.py`, not only in the dialog, so the pipeline can be tested without Qt.
- The worker uses thread-safe OpenCV/Pillow readers. The main window's `QPixmap` loader is not called from a worker thread.
- Gaps and rectangular layouts are fully supported; the old square-only splitter assumptions were removed.

## Decisions on your open questions

Yes, allocate frames per shot dynamically: the interval sets the target density, then each shot snaps to a grid that is completely full.

- **Interval**: the default 4 means every 4th frame starting on the shot's first frame (0, 4, 8, …). Offer chips for 2, 4, 8, 12 and 24 plus a free field.
- **Trim or fill (your 17-frame question)**: snap to the nearest full grid, measured by ratio, so the spacing changes as little as possible. 17 samples becomes a 4×4 (one frame dropped, spacing about 7% wider); 20 to 25 become a 5×5 (20 is an exact tie and goes to the denser grid). When trimming, the kept frames stay on the every-4th pattern. When filling, the extra frames are spread evenly across the shot.
- **Past 25 samples**: a 5×5 absorbs a small overflow, so 26 to 31 samples stay in one grid with up to 6 samples thinned out. From 32 samples the shot splits into equal grids in time order: 2 grids from 32, 3 from 63, 4 from 94, 5 from 126 (interval 4, squares). The planner weighs one fewer grid and up to two extra grids, and keeps the fewest images that stay within the spacing limit.
- **Spacing limit**: by default the total frame count may differ from the interval's count by at most ×1.25 either way (0.8× to 1.25×). If nothing fits, it takes the closest.
- **Fit strategy dropdown**: Balanced (default, the behaviour above), Trim (never add frames) and Fill (never drop frames, so it splits as soon as a shot passes 25: 26 samples becomes two 4×4 grids). Trim and Fill are the two options you were weighing.
- **Squares by default, rectangles optional**: squares leave big gaps at the small end (a 2-sample shot becomes a 2×2 with frames 1.7 apart instead of 4). The optional Compact rectangles layouts (1×2, 1×3, 2×3, 3×4, 4×5) keep neighbouring sizes within 1.5× from 2 cells upward. Smart Grid Splitter reads the sidecar's rows and columns, so rectangular grids round-trip.
- **Tiny shots**: a grid never has more cells than the shot has frames. A 1-frame shot gives a 1×1 image; a 3-frame shot gives a 1×1 with squares or a 1×3 with rectangles.

## Grid-fit algorithm

The planner is a pure function of shot length, interval and a few options, so it can be built and tested with no UI. A verified reference implementation is in the appendix.

1. **Find the shots.** Take the unique bookmark frames inside the export range (whole clip, custom range, or In/Out when the timeline has both points). Each bookmark starts a shot that ends one frame before the next bookmark; the last shot ends at the range end. Frames before the first bookmark form an optional lead-in (shot 0), off by default.
2. **Count the samples.** For a shot of L frames and interval s, `n = (L − 1) // s + 1`, the frames at offsets 0, s, 2s, ….
3. **List the allowed grid sizes.** Squares up to the chosen maximum: 1, 4, 9, 16, 25. Compact rectangles add 2, 3, 6, 12 and 20 cells (1×2, 1×3, 2×3, 3×4, 4×5).
4. **List the layouts to consider.** If n fits one grid (n ≤ 25 with a 5×5 maximum), only one grid is considered and the shot is never split. Otherwise `g_min = ceil(n / 25)`, and every grid count from `g_min − 1` to `g_min + 2` is paired with every allowed size. Considering one grid fewer lets a nearly full grid absorb a small overflow. Drop any layout with more cells than the shot has frames.
5. **Score each layout** by its drift, `ln(total / n)`, where total is grids × cells per grid.
6. **Pick one by strategy.**
   - Balanced: among layouts within the ratio limit (default ×1.25 either way), take the fewest images, then the smallest drift, then the larger grid on an exact tie. If none is within the limit, take the smallest drift.
   - Trim: the closest total at or below n.
   - Fill: the fewest images with total at or above n, then the smallest drift.
7. **Choose the frames** for `total = grids × cells`. If total ≤ n, stay on the every-s pattern and thin it evenly (a single cell uses the middle sample). If total > n, spread the frames evenly over the whole shot, first and last frame included. Round half up with `floor(x + 0.5)`, not Python's `round()`, so results are identical everywhere.
8. **Cut into grids.** Split the frames into equal runs in time order and name them part 1 of g, 2 of g, and so on.

Guarantees the tests should lock in: no empty cell; frames strictly increasing and inside the shot; equal grid sizes within a shot; no split when n ≤ 25; Trim never adds a frame; Fill never drops a frame unless the shot is too short to supply more.

## Worked examples

These are real outputs of the reference code (squares, 5×5 maximum, Balanced, ×1.25 limit), so they can double as test expectations. Real spacing is the average gap between the chosen frames.

| Interval | Shot length | Samples | Result | Frames | Real spacing |
| --- | --- | --- | --- | --- | --- |
| 4 | 1 | 1 | 1×1 | 1 | – |
| 4 | 6 | 2 | 2×2 | 4 | 1.67 |
| 4 | 10 | 3 | 2×2 | 4 | 3.00 |
| 4 | 33 | 9 | 3×3 | 9 | 4.00 |
| 4 | 50 | 13 | 4×4 | 16 | 3.27 |
| 4 | 65 | 17 | 4×4 | 16 | 4.27 |
| 4 | 80 | 20 | 5×5 | 25 | 3.29 |
| 4 | 101 | 26 | 5×5 | 25 | 4.17 |
| 4 | 124 | 31 | 5×5 | 25 | 5.00 |
| 4 | 128 | 32 | 2 grids of 4×4 | 32 | 4.00 |
| 4 | 160 | 40 | 2 grids of 5×5 | 50 | 3.24 |
| 4 | 240 | 60 | 2 grids of 5×5 | 50 | 4.82 |
| 4 | 300 | 75 | 3 grids of 5×5 | 75 | 4.00 |
| 4 | 400 | 100 | 4 grids of 5×5 | 100 | 4.00 |
| 12 | 100 | 9 | 3×3 | 9 | 12.00 |
| 12 | 240 | 20 | 5×5 | 25 | 9.96 |
| 12 | 400 | 34 | 2 grids of 4×4 | 32 | 12.77 |

For the 65-frame shot, the frames are 0, 4, 8, 12, 16, 20, 24, 28, 36, 40, 44, 48, 52, 56, 60, 64: the every-4th pattern with frame 32 dropped. For the 50-frame shot (13 samples, padded to 16) they are spread evenly: 0, 3, 7, 10, 13, 16, 20, 23, 26, 29, 33, 36, 39, 42, 46, 49.

The same shots under each strategy:

| Shot length | Samples | Balanced | Trim | Fill |
| --- | --- | --- | --- | --- |
| 65 | 17 | 4×4 (16) | 4×4 (16) | 5×5 (25) |
| 93 | 24 | 5×5 (25) | 4×4 (16) | 5×5 (25) |
| 101 | 26 | 5×5 (25) | 5×5 (25) | 2 grids of 4×4 (32) |
| 237 | 60 | 2 grids of 5×5 (50) | 2 grids of 5×5 (50) | 3 grids of 5×5 (75) |

With Compact rectangles, 2 samples give a 1×2 at spacing 4.00, 13 give a 3×4 at 4.36 and 22 give a 4×5 at 4.42. Squares give 1.67 and 3.27 for the first two.

## Export dialog

One dialog, opened from **File → Export → Shot Grids…**, with a live per-shot preview so every grid decision is visible before anything is written.

**Sampling**

- **Every Nth frame**: spinner 1 to 120, default 4, with chips for 2, 4, 8, 12 and 24.
- **Max grid**: 3×3, 4×4 or 5×5 (default 5×5).
- **Layout**: Square (default) or Compact rectangles.
- **Fit**: Balanced (default), Trim or Fill. Under Balanced, an advanced field sets the max spacing change (×1.0 to ×2.0, default ×1.25).

**Shots**

- **Range**: whole clip (default), custom start/end, or In/Out when both timeline points exist. The table replans live when the range changes.
- **Shot table**, one row per shot, updated live as any option changes: a checkbox, shot number, bookmark name, first to last frame (as the UI shows them, frame + 1), length, samples, planned layout (for example `2 × 4×4`) and real spacing. Unchecking a row skips that shot. Double-clicking a row seeks the player to the shot's first frame.
- **Lead-in row**: frames before the first bookmark appear as an unchecked row, so nothing is exported by accident.
- **Summary line** under the table: for example `12 shots → 19 images, 0 empty cells`, plus a note for any shot too short to fill its grid at this interval.
- **No bookmarks**: Export is disabled and a hint reads "Add a bookmark at the start of each shot, or run Detect Shots first."

**Output**

- **Folder, filename prefix** (default: the source name), **format** PNG, JPEG or TIFF, and **JPEG quality**: copy these from the bookmark export dialog.
- **Grid size**: longest side 1536, 2048, 3072 or 4096 px, or Native. Default: 2048 px. Cells keep the video's aspect ratio.
- **Gap between cells**: 0 px by default; up to 64 px. The splitter now understands gaps, so this is no longer restricted to 0.
- **Burn in frame numbers**: off.
- **Subfolder per shot**: off. **Also save the individual frames**: off. **Write manifest JSON**: on. **Write Smart Grid Splitter sidecars**: on.

Export runs in a worker thread with a progress dialog ("Shot 7 of 12") and a Cancel button. Remember every setting in `~/.kfpro_lite_settings.json` under a `shot_grid` key, next to the existing settings.

## Outputs and Smart Grid Splitter

Each shot writes one image per part plus one manifest, in `{output folder}/{prefix}_shot_grids/`.

- **Image name**: `{prefix}_shot_{index:03d}_f{start+1:04d}-{end+1:04d}_grid{R}x{C}.{ext}`, with `_part{p}of{g}` added before the extension when a shot has several grids. Filenames use the UI's 1-based frame numbers, as bookmark exports do. Sanitise the parts with the helper in `app_utils.py`, and add a small naming helper there with a test in `test_app_utils.py`.
- **Cell order**: row by row from the top left, in time order. Part 1 holds the earliest frames.
- **Manifest** `{prefix}_shot_grids.json`: frames are 0-based absolute frame numbers, listed in cell order. Abbreviated example:

```json
{
  "source_name": "my_video",
  "fps": 24,
  "settings": { "interval": 4, "max_grid": 5, "layout": "square", "strategy": "balanced", "max_ratio": 1.25 },
  "shots": [
    {
      "shot_index": 1,
      "name": "Bookmark 1",
      "start_frame": 0,
      "end_frame": 100,
      "samples_at_interval": 26,
      "images": [
        { "part": 1, "file": "my_video_shot_001_f0001-0101_grid5x5.png", "rows": 5, "cols": 5, "frames": [0, 4, 8, 12] }
      ]
    }
  ]
}
```

**Round trip with Smart Grid Splitter (implemented).** Each image gets a sidecar JSON beside it. The sidecar keeps the legacy `grid_dim`, adds `grid_rows`/`grid_cols`/`grid_gap`/`cell_width`/`cell_height`, and includes one chunk with `chunk_index`, `video_start_frame_abs: 0`, `video_end_frame_abs: source end`, and `selected_frames_abs`. The user loads the full source video as the "video chunk"; the splitter's relative-frame maths then gives the right frames with no clip export. The splitter now supports rectangular and gapped grids, and auto-scales the overlay so one cell matches the source frame.

## Files and build phases

Build it in six small phases, planner first; each phase ends with something the agent can run and check.

| File | Action | Purpose |
| --- | --- | --- |
| `shot_grid.py` | new | The planner from the appendix; no Qt, no OpenCV |
| `test_shot_grid.py` | new | Planner tests and the invariant sweep |
| `shot_grid_render.py` | new | Thread-safe frame readers, cell sizing, grid composition, image writing |
| `test_shot_grid_render.py` | new | Renderer, gap, padding and write tests |
| `shot_grid_export.py` | new | Qt-free export pipeline, manifest and sidecars |
| `test_shot_grid_export.py` | new | End-to-end file, manifest, cancellation and error tests |
| `shot_grid_dialog.py` | new | Dialog, live table, settings and export worker |
| `test_shot_grid_dialog.py` | new | Dialog behaviour and main-window wiring |
| `ui_main.py` | change | Menu action, media description, default folder, settings persistence, WAN composer reuse |
| `app_utils.py`, `test_app_utils.py` | change | `build_shot_grid_filename` and its tests |
| `grid_splitter.py`, `test_grid_splitter.py` | change/new | Sidecar geometry, rectangular/gapped grids, auto scale |
| `state.md`, `kfplayer_functional_specification.md`, `README.md` | change | Document the feature |

- [x] **Phase 1, planner.** `shot_grid.py` and `test_shot_grid.py` pass, including all worked examples and 100,800 invariant combinations.
- [x] **Phase 2, renderer.** `shot_grid_render.py` reads frames in ascending order from one capture, composes row by row with one preallocated image, preserves aspect ratio, supports gaps and optional labels, and exposes `compose_grid` reused by WAN preparation.
- [x] **Phase 3, dialog and menu.** All controls, live table, custom/In-Out range, settings persistence, worker thread and cancel are wired.
- [x] **Phase 4, export and manifest.** Naming, subfolders, manifest, individual frames and burn-in labels are tested end to end.
- [x] **Phase 5, Smart Grid Splitter round trip.** Sidecar JSON per image; rows, cols, gaps and cell size are honoured by the splitter.
- [x] **Phase 6, docs.** `state.md`, the functional spec, the README and this plan are updated.

Working rules followed: the planner and export pipeline stay free of Qt; the WAN composer was extracted into `compose_grid` without changing its output; the test suite uses `unittest`; and existing export behaviour is covered by the original tests, which still pass.

## Tests and acceptance checks

The tests lock in the planner's guarantees first, then the files it writes.

**Planner (`test_shot_grid.py`, no UI)**

- `samples_at_interval`: (1, 4) → 1, (4, 4) → 1, (5, 4) → 2, (100, 4) → 25, (101, 4) → 26.
- Layout by sample count at interval 4 (Balanced, squares, 5×5 maximum; a shot of `4n − 3` frames gives n samples): n = 1 → 1×1; 2 to 5 → 2×2; 6 to 11 → 3×3; 12 to 19 → 4×4; 20 to 31 → 5×5; 32 to 39 → 2 grids of 4×4; 40 to 62 → 2 grids of 5×5; 63 to 93 → 3 grids of 5×5; 94 to 125 → 4 grids of 5×5; 126 → 5 grids of 5×5.
- Invariants over a sweep of shot lengths 1 to 700, intervals 1, 2, 3, 4, 6, 8, 12 and 24, max grid 3, 4 and 5, both layouts and all strategies: no empty cell; frames strictly increasing and inside the shot; equal grid sizes within a shot; no grid above the maximum; only squares unless rectangles were requested; no split when n fits one grid; total never above the shot length; Trim never adds a frame; Fill never drops one unless the shot is too short to supply more. The implementation passes all 100,800 combinations.
- Frame choice: when total ≤ n every frame is `start + k × interval`; when total > n the first and last frame are both included.
- `shots_from_bookmarks`: unsorted input, duplicates, out-of-range bookmarks ignored, one bookmark, none (empty list), lead-in as shot 0, last shot ending at the range end, In/Out clipping.
- Bad input: interval 0 and a zero-length shot raise `ValueError`.

**Files it writes**

- The naming helper, including sanitising.
- A synthetic clip of about 130 small frames with the frame number drawn into each one and 3 bookmarks. Export it and check: the number of images, each image's width is cols × cell width, the manifest frames equal the planner's frames, and cell k really shows the frame the manifest says.
- Cancel stops cleanly and leaves the finished files readable.
- A missing frame is reported against its shot while later shots still export.
- A UI test in the style of `test_ui_main.py`: the menu entry exists, is disabled with no media loaded, and the dialog's table has one row per shot.
- Dialog tests cover live replanning, row checkboxes, custom range, interval chips, settings round-trip and the main-window export hand-off.
- Splitter tests cover rectangular geometry, gaps, auto scale, and cropping a synthetic grid back to source resolution.

**Your manual check**: bookmark three shots of about 10, 65 and 130 frames, export at interval 4, and expect a 2×2, a 4×4 and two 4×4 images, none with an empty cell.

## Edge cases and later options

Most edge cases are already handled by the planner; the rest are about export behaviour.

- **Adjacent bookmarks** make 1-frame shots, which give 1×1 images. The table flags them so a stray bookmark is easy to spot and uncheck.
- **Missing or unreadable frames** (a gap in an image sequence, a failed seek): stop that shot with an error that names the frame, as the existing exports do, and keep the files already written. If a seek fails on a video, retry by reading forward from the previous frame.
- **Memory**: a 5×5 grid of 4K cells at Native size is 19200 × 10800 px, about 620 MB as 8-bit RGB. The default cap on the longest side avoids this; warn before exporting Native above roughly 100 megapixels.
- **Existing files**: follow whatever the bookmark export does today when a name already exists.
- **Cancel**: stop after the current image, keep what was written, and report how many images were saved.
- **GIF and image-sequence sources** work through the main window's frame loader, so the dialog needs no special cases.

Later options, not part of the first build:

- A thumbnail preview of the selected shot's grid inside the dialog.
- A per-shot interval override, set from the table.
- Choosing frames by motion or scene change instead of even spacing.
- Exporting each shot as its own clip alongside its grid.

## Appendix: reference implementation

This is the reference planner used to seed `shot_grid.py`. The shipped file adds input validation and docstrings and is covered by `test_shot_grid.py` (100,800 plan combinations, no failures). The renderer, export pipeline, dialog and splitter round trip are built and tested separately.

```python
"""Shot grid planning (pure logic, no Qt or OpenCV) so it can be unit-tested.

A "shot" runs from one bookmark to the frame before the next bookmark. For each
shot we decide how many grid images to make, how big each grid is, and which
frames go in each cell, so that no cell is ever left empty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

# rows, cols for every supported cell count. Square layouts are the default;
# the rectangular ones are only used when the caller opts in.
LAYOUTS: dict[int, tuple[int, int]] = {
    1: (1, 1),
    2: (1, 2),
    3: (1, 3),
    4: (2, 2),
    6: (2, 3),
    9: (3, 3),
    12: (3, 4),
    16: (4, 4),
    20: (4, 5),
    25: (5, 5),
}

DEFAULT_INTERVAL = 4
DEFAULT_MAX_DIM = 5        # 5x5 = 25 cells per image
DEFAULT_MAX_RATIO = 1.25   # total frames may differ from the interval's count by up to x1.25 either way
EXTRA_GRID_COUNTS = 2      # grid counts tried above the minimum when n > cap


class FitStrategy(str, Enum):
    BALANCED = "balanced"  # fewest images that stay within the ratio limit
    TRIM = "trim"          # never add frames: closest full layout at or below n
    FILL = "fill"          # never drop frames: fewest images that hold all n


@dataclass(frozen=True)
class Shot:
    index: int   # 1-based bookmark order; 0 = lead-in before the first bookmark
    start: int   # first frame, 0-based, inclusive
    end: int     # last frame, 0-based, inclusive

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class GridPart:
    part: int                 # 1-based
    rows: int
    cols: int
    frames: tuple[int, ...]   # absolute frame numbers, len == rows * cols


@dataclass(frozen=True)
class ShotGridPlan:
    shot: Shot
    interval: int
    samples_at_interval: int
    parts: tuple[GridPart, ...]

    @property
    def all_frames(self) -> tuple[int, ...]:
        return tuple(f for p in self.parts for f in p.frames)

    @property
    def total_frames(self) -> int:
        return len(self.all_frames)

    @property
    def empty_cells(self) -> int:
        return sum(p.rows * p.cols - len(p.frames) for p in self.parts)

    @property
    def effective_interval(self) -> float | None:
        frames = self.all_frames
        if len(frames) < 2:
            return None
        return (frames[-1] - frames[0]) / (len(frames) - 1)


def shots_from_bookmarks(
    bookmark_frames,
    clip_end: int,
    clip_start: int = 0,
    include_lead_in: bool = False,
) -> list[Shot]:
    """Each bookmark starts a shot that ends one frame before the next bookmark.

    The last shot ends at clip_end. Frames before the first bookmark are only
    returned (as shot 0) when include_lead_in is True.
    """
    starts = sorted({f for f in bookmark_frames if clip_start <= f <= clip_end})
    shots: list[Shot] = []
    if include_lead_in and starts and starts[0] > clip_start:
        shots.append(Shot(0, clip_start, starts[0] - 1))
    for i, s in enumerate(starts):
        e = starts[i + 1] - 1 if i + 1 < len(starts) else clip_end
        shots.append(Shot(i + 1, s, e))
    return shots


def samples_at_interval(length: int, interval: int) -> int:
    """Frames hit by 'every Nth frame' starting on the shot's first frame."""
    return (length - 1) // interval + 1


def _half_up(x: float) -> int:
    # Round half up (not Python's banker's round()) so results are identical on
    # every platform and .5 always goes to the later frame. It is monotonic, so
    # frames that are >= 1 apart before rounding stay distinct.
    return int(math.floor(x + 0.5))


def allowed_cell_counts(max_dim: int = DEFAULT_MAX_DIM, rectangular: bool = False) -> list[int]:
    return sorted(
        c
        for c, (r, k) in LAYOUTS.items()
        if max(r, k) <= max_dim and (rectangular or r == k)
    )


def choose_layout(
    length: int,
    interval: int,
    sizes: list[int],
    strategy: FitStrategy = FitStrategy.BALANCED,
    max_ratio: float = DEFAULT_MAX_RATIO,
) -> tuple[int, int]:
    """Return (grid_count, cells_per_grid) for a shot of `length` frames."""
    n = samples_at_interval(length, interval)
    cap = max(sizes)
    g_min = -(-n // cap)                  # fewest grids that hold every sample
    if g_min == 1:
        grid_counts = [1]                 # a shot that fits one grid is never split
    else:
        grid_counts = range(g_min - 1, g_min + 1 + EXTRA_GRID_COUNTS)

    # (grids, cells each, log of total/n). A grid never has more cells than the
    # shot has frames, so padding stops when the shot runs out of frames.
    options = [
        (g, c, math.log(g * c / n))
        for g in grid_counts
        for c in sizes
        if g * c <= length
    ]

    def dev(o):
        return round(abs(o[2]), 9)        # rounded so exact ties really tie

    if strategy is FitStrategy.TRIM:
        pool = [o for o in options if o[0] * o[1] <= n] or options
        g, c, _ = min(pool, key=lambda o: (dev(o), o[0], -o[1]))
    elif strategy is FitStrategy.FILL:
        pool = [o for o in options if o[0] * o[1] >= n] or options
        g, c, _ = min(pool, key=lambda o: (o[0], dev(o), -o[1]))
    else:
        limit = math.log(max_ratio) + 1e-9
        within = [o for o in options if abs(o[2]) <= limit]
        if within:
            g, c, _ = min(within, key=lambda o: (o[0], dev(o), -o[1]))
        else:
            g, c, _ = min(options, key=lambda o: (dev(o), o[0], -o[1]))
    return g, c


def select_frames(shot: Shot, interval: int, total: int) -> tuple[int, ...]:
    """Pick `total` distinct, evenly spread frames from the shot."""
    length = shot.length
    n = samples_at_interval(length, interval)
    if total <= n:
        # stay on the 'every Nth frame' lattice; thin it evenly if needed
        if total == 1:
            idx = [(n - 1) // 2]                     # middle sample
        else:
            idx = [_half_up(k * (n - 1) / (total - 1)) for k in range(total)]
        return tuple(shot.start + i * interval for i in idx)
    # need more frames than the interval gives: spread evenly over the shot
    return tuple(
        shot.start + _half_up(k * (length - 1) / (total - 1)) for k in range(total)
    )


def plan_shot(
    shot: Shot,
    interval: int = DEFAULT_INTERVAL,
    max_dim: int = DEFAULT_MAX_DIM,
    rectangular: bool = False,
    strategy: FitStrategy = FitStrategy.BALANCED,
    max_ratio: float = DEFAULT_MAX_RATIO,
) -> ShotGridPlan:
    if interval < 1:
        raise ValueError("interval must be >= 1")
    if shot.length < 1:
        raise ValueError("shot must contain at least one frame")
    sizes = allowed_cell_counts(max_dim, rectangular)
    g, cells = choose_layout(shot.length, interval, sizes, strategy, max_ratio)
    frames = select_frames(shot, interval, g * cells)
    rows, cols = LAYOUTS[cells]
    parts = tuple(
        GridPart(p + 1, rows, cols, frames[p * cells:(p + 1) * cells]) for p in range(g)
    )
    return ShotGridPlan(shot, interval, samples_at_interval(shot.length, interval), parts)


def plan_shots(shots, **kwargs) -> list[ShotGridPlan]:
    return [plan_shot(s, **kwargs) for s in shots]
```
