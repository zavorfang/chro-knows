import json
import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import numpy as np


SHOT_ANALYSIS_CHUNK_SECONDS = 59.0
JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "background",
    "close",
    "frame",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "shot",
    "shows",
    "the",
    "to",
    "view",
    "with",
}


@dataclass(frozen=True)
class AnalysisChunk:
    index: int
    start_frame: int
    end_frame: int
    fps: float

    @property
    def duration_seconds(self) -> float:
        return ((self.end_frame - self.start_frame) + 1) / max(self.fps, 1e-6)


@dataclass(frozen=True)
class TraditionalCutCandidate:
    frame: int
    score: float
    confidence: float
    kind: str


@dataclass
class GemmaShot:
    start_seconds: float
    description: str
    continues_from_previous: bool = False
    continues_to_next: bool = False
    confidence: float | None = None
    source: str = "chunk"


@dataclass
class ChunkShotAnalysis:
    chunk: AnalysisChunk
    shots: list[GemmaShot]
    first_shot_signature: str = ""
    last_shot_signature: str = ""
    raw_response: str = ""


@dataclass
class DetectedShot:
    start_frame: int
    description: str
    source: str = "chunk"
    confidence: float | None = None
    chunk_index: int | None = None
    continues_from_previous: bool = False
    continues_to_next: bool = False


def frame_to_seconds(frame: int, fps: float) -> float:
    return max(0.0, frame / max(fps, 1e-6))


def seconds_to_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours = total_ms // 3_600_000
    total_ms %= 3_600_000
    minutes = total_ms // 60_000
    total_ms %= 60_000
    secs = total_ms // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def frame_to_timestamp(frame: int, fps: float) -> str:
    return seconds_to_timestamp(frame_to_seconds(frame, fps))


def plan_shot_analysis_chunks(
    total_frames: int,
    fps: float,
    max_duration_seconds: float = SHOT_ANALYSIS_CHUNK_SECONDS,
) -> list[AnalysisChunk]:
    if total_frames <= 0:
        return []

    effective_fps = max(float(fps or 0), 1e-6)
    frames_per_chunk = max(1, int(math.floor(max_duration_seconds * effective_fps)))
    chunks: list[AnalysisChunk] = []
    start_frame = 0
    index = 0

    while start_frame < total_frames:
        end_frame = min(total_frames - 1, start_frame + frames_per_chunk - 1)
        chunks.append(
            AnalysisChunk(
                index=index,
                start_frame=start_frame,
                end_frame=end_frame,
                fps=effective_fps,
            )
        )
        index += 1
        start_frame = end_frame + 1

    return chunks


def extract_json_payload(text: str) -> Any:
    if not text or not str(text).strip():
        raise ValueError("Gemma returned an empty response.")

    source = str(text).strip()
    fence_match = JSON_FENCE_RE.search(source)
    if fence_match:
        source = fence_match.group(1).strip()

    starts = [idx for idx in (source.find("{"), source.find("[")) if idx != -1]
    if starts:
        start = min(starts)
        end_brace = source.rfind("}")
        end_bracket = source.rfind("]")
        end = max(end_brace, end_bracket)
        if end > start:
            source = source[start : end + 1]

    return json.loads(source)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default

    if re.fullmatch(r"\d{2}:\d{2}:\d{2}(?:\.\d+)?", text):
        hours, minutes, seconds = text.split(":")
        return (
            int(hours) * 3600
            + int(minutes) * 60
            + float(seconds)
        )

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else default


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


def _coerce_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    confidence = _coerce_float(value, default=0.0)
    return max(0.0, min(1.0, confidence))


def parse_chunk_shot_response(
    text: str,
    clip_duration_seconds: float,
) -> tuple[list[GemmaShot], str, str]:
    payload = extract_json_payload(text)
    if isinstance(payload, list):
        raw_shots = payload
        first_signature = ""
        last_signature = ""
    else:
        raw_shots = payload.get("shots", [])
        first_signature = str(payload.get("first_shot_signature", "") or "").strip()
        last_signature = str(payload.get("last_shot_signature", "") or "").strip()

    shots: list[GemmaShot] = []
    for raw in raw_shots:
        if not isinstance(raw, dict):
            continue

        description = str(
            raw.get("description")
            or raw.get("shot_description")
            or raw.get("summary")
            or ""
        ).strip()
        if not description:
            continue

        start_seconds = _coerce_float(
            raw.get("start_seconds", raw.get("time_seconds", raw.get("start_timecode"))),
            default=0.0,
        )
        start_seconds = max(0.0, min(float(clip_duration_seconds), start_seconds))
        shots.append(
            GemmaShot(
                start_seconds=start_seconds,
                description=description,
                continues_from_previous=_coerce_bool(
                    raw.get("continues_from_previous")
                ),
                continues_to_next=_coerce_bool(raw.get("continues_to_next")),
                confidence=_coerce_confidence(raw.get("confidence")),
            )
        )

    shots.sort(key=lambda shot: (shot.start_seconds, shot.description))
    deduped: list[GemmaShot] = []
    for shot in shots:
        if deduped and abs(deduped[-1].start_seconds - shot.start_seconds) < 1e-3:
            if len(shot.description) > len(deduped[-1].description):
                deduped[-1] = shot
            continue
        deduped.append(shot)

    return deduped, first_signature, last_signature


def detect_cut_candidates_from_scores(
    scores: list[float],
    start_frame: int,
    fps: float,
    min_gap_frames: int | None = None,
) -> list[TraditionalCutCandidate]:
    if not scores:
        return []

    values = np.asarray(scores, dtype=float)
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median))) * 1.4826
    mad = max(mad, 1e-6)

    base_threshold = median + (2.5 * mad)
    strong_threshold = max(median + (4.0 * mad), float(np.percentile(values, 97)))
    bridge_threshold = max(median + (1.5 * mad), base_threshold * 0.7)
    min_gap = max(3, min_gap_frames or int(round(max(float(fps or 0), 1.0) * 0.25)))

    candidates: list[TraditionalCutCandidate] = []
    index = 0
    total = len(values)
    while index < total:
        if values[index] < base_threshold:
            index += 1
            continue

        run_start = index
        peak_index = index
        peak_value = float(values[index])
        run_end = index

        while run_end + 1 < total and values[run_end + 1] >= bridge_threshold:
            run_end += 1
            if values[run_end] >= peak_value:
                peak_index = run_end
                peak_value = float(values[run_end])

        confidence_span = max(strong_threshold - base_threshold, 1e-6)
        confidence = 0.55 + ((peak_value - base_threshold) / confidence_span) * 0.45
        confidence = max(0.0, min(1.0, confidence))
        candidates.append(
            TraditionalCutCandidate(
                frame=start_frame + peak_index + 1,
                score=peak_value,
                confidence=confidence,
                kind="strong" if peak_value >= strong_threshold else "clear",
            )
        )
        index = run_end + 1

    merged: list[TraditionalCutCandidate] = []
    for candidate in candidates:
        if merged and candidate.frame - merged[-1].frame < min_gap:
            if candidate.score > merged[-1].score:
                merged[-1] = candidate
            continue
        merged.append(candidate)

    return merged


def find_nearest_candidate(
    target_frame: int,
    candidates: list[TraditionalCutCandidate],
    window_frames: int,
    after_frame: int | None = None,
) -> TraditionalCutCandidate | None:
    best: TraditionalCutCandidate | None = None
    best_distance: int | None = None

    for candidate in candidates:
        if after_frame is not None and candidate.frame <= after_frame:
            continue
        distance = abs(candidate.frame - target_frame)
        if distance > window_frames:
            continue
        if best is None:
            best = candidate
            best_distance = distance
            continue
        assert best_distance is not None
        if candidate.score > best.score or (
            math.isclose(candidate.score, best.score) and distance < best_distance
        ):
            best = candidate
            best_distance = distance

    return best


def match_chunk_shots_to_candidates(
    analysis: ChunkShotAnalysis,
    candidates: list[TraditionalCutCandidate],
    tolerance_seconds: float = 1.75,
    require_candidate_for_internal_cuts: bool = True,
) -> list[DetectedShot]:
    if not analysis.shots:
        return []

    tolerance_frames = max(2, int(round(analysis.chunk.fps * tolerance_seconds)))
    matched: list[DetectedShot] = []

    first_shot = analysis.shots[0]
    matched.append(
        DetectedShot(
            start_frame=analysis.chunk.start_frame,
            description=first_shot.description,
            source=first_shot.source,
            confidence=first_shot.confidence,
            chunk_index=analysis.chunk.index,
            continues_from_previous=first_shot.continues_from_previous,
            continues_to_next=first_shot.continues_to_next,
        )
    )

    last_start_frame = analysis.chunk.start_frame
    internal_candidates = [
        candidate
        for candidate in candidates
        if analysis.chunk.start_frame < candidate.frame <= analysis.chunk.end_frame
    ]

    for shot in analysis.shots[1:]:
        approx_frame = analysis.chunk.start_frame + int(
            round(shot.start_seconds * analysis.chunk.fps)
        )
        nearest = find_nearest_candidate(
            approx_frame,
            internal_candidates,
            tolerance_frames,
            after_frame=last_start_frame,
        )
        if nearest is None and require_candidate_for_internal_cuts:
            continue
        resolved_frame = nearest.frame if nearest else approx_frame
        if resolved_frame <= last_start_frame:
            continue

        matched.append(
            DetectedShot(
                start_frame=resolved_frame,
                description=shot.description,
                source=shot.source,
                confidence=shot.confidence if shot.confidence is not None else (
                    nearest.confidence if nearest else None
                ),
                chunk_index=analysis.chunk.index,
                continues_from_previous=shot.continues_from_previous,
                continues_to_next=shot.continues_to_next,
            )
        )
        last_start_frame = resolved_frame

    return matched


def normalize_description(text: str) -> str:
    tokens = [
        token
        for token in TOKEN_RE.findall((text or "").lower())
        if token not in STOPWORDS
    ]
    return " ".join(tokens)


def description_similarity(first: str, second: str) -> float:
    normalized_first = normalize_description(first)
    normalized_second = normalize_description(second)
    if not normalized_first or not normalized_second:
        return 0.0

    ratio = SequenceMatcher(None, normalized_first, normalized_second).ratio()
    first_tokens = set(normalized_first.split())
    second_tokens = set(normalized_second.split())
    union = first_tokens | second_tokens
    jaccard = (len(first_tokens & second_tokens) / len(union)) if union else 0.0
    return (ratio * 0.65) + (jaccard * 0.35)


def merge_shot_descriptions(primary: str, secondary: str) -> str:
    first = (primary or "").strip()
    second = (secondary or "").strip()
    if not first:
        return second
    if not second:
        return first
    if second.lower() in first.lower():
        return first
    if first.lower() in second.lower():
        return second
    return first if len(first) >= len(second) else second


def should_merge_boundary_duplicate(
    previous_shot: DetectedShot,
    next_shot: DetectedShot,
    boundary_same_shot: bool,
    seam_candidate: TraditionalCutCandidate | None = None,
) -> bool:
    similarity = description_similarity(previous_shot.description, next_shot.description)
    carry_score = 0.0
    if boundary_same_shot:
        carry_score += 0.55
    if similarity >= 0.72:
        carry_score += 0.25
    if previous_shot.continues_to_next:
        carry_score += 0.10
    if next_shot.continues_from_previous:
        carry_score += 0.10
    if seam_candidate is not None:
        carry_score -= seam_candidate.confidence * 0.35
    return carry_score >= 0.45


def finalize_shot_ranges(
    shots: list[DetectedShot],
    fps: float,
    clip_end_frame: int,
) -> list[dict[str, Any]]:
    if not shots:
        return []

    ordered = sorted(shots, key=lambda shot: (shot.start_frame, shot.description))
    collapsed: list[DetectedShot] = []
    for shot in ordered:
        if collapsed and shot.start_frame == collapsed[-1].start_frame:
            collapsed[-1].description = merge_shot_descriptions(
                collapsed[-1].description, shot.description
            )
            if shot.confidence is not None:
                collapsed[-1].confidence = max(
                    collapsed[-1].confidence or 0.0,
                    shot.confidence,
                )
            continue
        collapsed.append(shot)

    finalized: list[dict[str, Any]] = []
    for index, shot in enumerate(collapsed, start=1):
        next_start = (
            collapsed[index].start_frame - 1 if index < len(collapsed) else clip_end_frame
        )
        start_seconds = frame_to_seconds(shot.start_frame, fps)
        end_seconds = frame_to_seconds(next_start, fps)
        finalized.append(
            {
                "index": index,
                "start_frame": shot.start_frame,
                "end_frame": next_start,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "start_timestamp": seconds_to_timestamp(start_seconds),
                "end_timestamp": seconds_to_timestamp(end_seconds),
                "description": shot.description,
                "source": shot.source,
                "confidence": shot.confidence,
                "chunk_index": shot.chunk_index,
                "continues_from_previous": shot.continues_from_previous,
                "continues_to_next": shot.continues_to_next,
            }
        )

    return finalized
