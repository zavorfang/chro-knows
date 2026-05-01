# KFPlayer Agent Handoff

This file is a compact transfer document for a new agent taking over work on KFPlayer.
It is intentionally shorter and more current than `SPEC.md`, and it includes recent export work that is not yet reflected in the original spec.

## 1. Project Summary

- App name: `KFPlayer` / window title currently says `Keyframe Pro Lite`
- Type: desktop animation review player built with `PyQt6`
- Primary use: load a video or image sequence, scrub frame-accurately, review, bookmark, and export
- Main recent feature area: WAN 2.2-friendly chunked MP4 export for videos

## 2. Current App Capabilities

### Review / Playback

- Load folders of image sequences
- Load video files including common containers and GIFs
- Frame-accurate scrubbing
- Play / pause, jump to ends, loop
- Zoom and pan in the viewer
- Timeline thumbnails and overview timeline
- Bookmark list with click-to-jump and delete

### Export

- Standard MP4 export with:
  - start/end frame range
  - quality slider mapped to H.264 CRF
  - speed preset (`ultrafast`, `fast`, `medium`, `slow`)
- WAN 2.2 chunk export with:
  - user-entered chunk size
  - chunk size snapped down to WAN-safe `(x * 4) + 1`
  - optional overlap between chunks
  - balanced final two chunks to avoid very tiny tail clips
  - only the final chunk is padded by repeating its last frame

## 3. Architecture Map

### Important Files

- [ui_main.py](/E:/programming/llm/ui_main.py)
  Main window, dialogs, video loading, standard MP4 export, WAN export flow
- [wan_chunks.py](/E:/programming/llm/wan_chunks.py)
  Pure chunk-planning logic for WAN export
- [test_wan_chunks.py](/E:/programming/llm/test_wan_chunks.py)
  Unit tests for WAN chunk math
- [viewer.py](/E:/programming/llm/viewer.py)
  Viewer widget for image display, zoom, pan
- [timeline.py](/E:/programming/llm/timeline.py)
  Thumbnail and overview timeline widgets
- [project.py](/E:/programming/llm/project.py)
  Project state container and save/load logic
- [SPEC.md](/E:/programming/llm/SPEC.md)
  Original higher-level product spec, now partially outdated

### Export Entry Points

- Standard MP4 export dialog:
  [ui_main.py](/E:/programming/llm/ui_main.py:1089)
- WAN export dialog:
  [ui_main.py](/E:/programming/llm/ui_main.py:1133)
- Shared MP4 writer:
  [ui_main.py](/E:/programming/llm/ui_main.py:1179)
- WAN export executor:
  [ui_main.py](/E:/programming/llm/ui_main.py:1255)
- WAN export dialog class:
  [ui_main.py](/E:/programming/llm/ui_main.py:1610)

## 4. WAN Chunking Rules

These are the current intended rules implemented in code:

### WAN Length Rules

- Valid WAN-safe lengths follow `(x * 4) + 1`
- Example valid lengths: `1, 5, 9, 13, ... 85, 89, 93`
- User-selected chunk size is snapped down to the nearest WAN-safe value
- Example: `88 -> 85`

### Planning Rules

- If total remaining span is `<= chunk_size`, it becomes the final chunk
- Final chunk target length is rounded up to the next WAN-safe value
- Only the final chunk is padded
- If the remaining span fits inside a 2-chunk window, the planner balances the last two chunks instead of leaving a tiny trailer
- The first of those last two chunks is rounded up from the halfway split to a WAN-safe length when possible

### Overlap Rules

- Overlap is optional
- Current supported overlap range is `4..32`
- Overlap is modeled by moving the next chunk backward so it shares frames with the previous chunk
- In plain terms: overlap happens at the start of a later chunk and at the end of the earlier chunk on the timeline
- Overlap changes stride, so chunk count and final distribution may change

## 5. Example Behaviors

- `chunk size 88` becomes `85`
- A short clip like `10` frames becomes one chunk padded to `13`
- A clip that would otherwise end as `85, 85, 85, 5` should now rebalance the last two chunks instead of leaving a `5`-frame trailer
- For `258` frames at chunk size `85`, current expected raw chunk lengths are:
  - `85, 85, 45, 43`
- The WAN target lengths for that case are:
  - `85, 85, 45, 45`
- With overlap enabled, the chunk starts shift backward and the distribution changes

## 6. Current WAN Chunking Code

The chunk planner lives in [wan_chunks.py](/E:/programming/llm/wan_chunks.py) and currently exposes:

- `snap_to_wan_ceil(n)`
- `snap_to_wan_floor(n)`
- `normalize_wan_chunk_size(chunk_size)`
- `normalize_chunk_overlap(overlap, chunk_size)`
- `choose_balanced_first_chunk_length(span, chunk_size, overlap=0)`
- `plan_wan_chunks(total_frames, chunk_size=WAN_CHUNK_SIZE, overlap=0)`

Data model:

- `WanChunk.start_frame`
- `WanChunk.end_frame`
- `WanChunk.source_length`
- `WanChunk.target_length`
- `WanChunk.pad_count`

## 7. Current UI for WAN Export

The WAN export dialog currently includes:

- output folder
- filename prefix
- chunk size spinbox
- overlap toggle
- overlap amount spinbox
- quality slider
- speed preset
- preview text showing planned chunk lengths

The preview is meant to show:

- number of WAN-safe clips
- WAN-safe target lengths
- raw source lengths
- whether overlap is enabled
- whether trailing padding is needed

## 8. Known Gaps / Risks

- `SPEC.md` does not yet describe the WAN export feature and is now outdated in that area
- The app is still mostly single-file in `ui_main.py`, so export logic is functional but not yet separated into cleaner modules
- Recent WAN planning behavior should be treated as the current source of truth, not the older thread summaries
- If future work changes overlap semantics, both the planner and preview text must stay aligned

## 9. Test Coverage

Tests currently exist in [test_wan_chunks.py](/E:/programming/llm/test_wan_chunks.py) for:

- WAN ceil and floor snapping
- chunk size normalization
- overlap normalization
- short clip padding
- balanced final two chunks
- final-chunk-only padding
- overlap-aware planning

Representative test cases currently include:

- `88 -> 85`
- `100` frames with requested chunk size `88`
- `186` frames at default `93`
- `258` frames at `85`
- `258` frames at `85` with overlap `8`

## 10. Suggested Next Steps

If a new agent is continuing feature work, the highest-value next tasks are likely:

1. Update [SPEC.md](/E:/programming/llm/SPEC.md) so it reflects the WAN export feature and current export UX.
2. Manually verify the WAN export dialog behavior against the planner examples in real app runs.
3. Consider moving WAN export code out of [ui_main.py](/E:/programming/llm/ui_main.py) into a dedicated exporter module if the feature grows further.
4. If overlap semantics evolve, update both [wan_chunks.py](/E:/programming/llm/wan_chunks.py) and [test_wan_chunks.py](/E:/programming/llm/test_wan_chunks.py) together.

## 11. Short Takeover Note

If you are a new agent, start with:

1. Read [AGENT_HANDOFF.md](/E:/programming/llm/AGENT_HANDOFF.md)
2. Skim [SPEC.md](/E:/programming/llm/SPEC.md) for baseline product intent
3. Read [wan_chunks.py](/E:/programming/llm/wan_chunks.py) and [test_wan_chunks.py](/E:/programming/llm/test_wan_chunks.py) for current export math
4. Inspect [ui_main.py](/E:/programming/llm/ui_main.py) around the WAN export dialog and export methods before making changes
