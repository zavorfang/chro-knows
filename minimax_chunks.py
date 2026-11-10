from dataclasses import dataclass


MINIMAX_MIN_FRAMES = 5
MINIMAX_STRIDE = 17
MINIMAX_DEFAULT_CHUNK = 124  # 17 * 7 + 5 ≈ 5.17s at 24fps
MINIMAX_OVERLAP_MIN = 17
MINIMAX_OVERLAP_MAX = 51  # 3 strides


@dataclass(frozen=True)
class MinimaxChunk:
    start_frame: int
    end_frame: int
    source_length: int
    target_length: int  # always (17k + 5)

    @property
    def pad_count(self) -> int:
        return self.target_length - self.source_length


def snap_to_minimax_ceil(n: int) -> int:
    """Round *up* to the nearest valid MiniMax H3 frame count (17k + 5)."""
    if n <= 0:
        raise ValueError("MiniMax frame counts must be positive.")

    if n <= MINIMAX_MIN_FRAMES:
        return MINIMAX_MIN_FRAMES

    remainder = (n - MINIMAX_MIN_FRAMES) % MINIMAX_STRIDE
    if remainder == 0:
        return n
    return n + (MINIMAX_STRIDE - remainder)


def snap_to_minimax_floor(n: int) -> int:
    """Round *down* to the nearest valid MiniMax H3 frame count (17k + 5)."""
    if n <= 0:
        raise ValueError("MiniMax frame counts must be positive.")

    if n < MINIMAX_MIN_FRAMES:
        return MINIMAX_MIN_FRAMES

    return n - ((n - MINIMAX_MIN_FRAMES) % MINIMAX_STRIDE)


def normalize_minimax_chunk_size(chunk_size: int) -> int:
    """Snap a requested chunk size down to the nearest MiniMax-safe value."""
    return snap_to_minimax_floor(chunk_size)


def normalize_minimax_overlap(overlap: int, chunk_size: int) -> int:
    """Clamp and validate overlap for MiniMax chunks."""
    chunk_size = normalize_minimax_chunk_size(chunk_size)
    if overlap <= 0:
        return 0

    max_overlap = min(MINIMAX_OVERLAP_MAX, chunk_size - MINIMAX_MIN_FRAMES)
    if max_overlap < MINIMAX_OVERLAP_MIN:
        return 0

    clamped = max(MINIMAX_OVERLAP_MIN, min(overlap, max_overlap))
    # Snap overlap to nearest stride multiple for clean alignment
    return (clamped // MINIMAX_STRIDE) * MINIMAX_STRIDE or MINIMAX_STRIDE


def choose_balanced_first_chunk_length(
    span: int, chunk_size: int, overlap: int = 0
) -> int:
    """Pick a balanced first-chunk length when splitting into exactly two chunks."""
    ideal = (span + overlap) // 2
    min_first = max(MINIMAX_MIN_FRAMES, span - chunk_size + overlap)
    max_first = chunk_size

    rounded_up = snap_to_minimax_ceil(ideal)
    if min_first <= rounded_up <= max_first:
        return rounded_up

    rounded_min = snap_to_minimax_ceil(min_first)
    if rounded_min <= max_first:
        return rounded_min

    return snap_to_minimax_floor(max_first)


def plan_minimax_chunks(
    total_frames: int,
    chunk_size: int = MINIMAX_DEFAULT_CHUNK,
    overlap: int = 0,
) -> list[MinimaxChunk]:
    """Plan MiniMax H3-safe chunks for a frame span.

    Each chunk's target_length is snapped to (17k + 5).
    Only the final chunk may be padded.
    """
    if total_frames <= 0:
        return []

    if chunk_size <= 0:
        raise ValueError("Chunk size must be positive.")

    chunk_size = normalize_minimax_chunk_size(chunk_size)
    overlap = normalize_minimax_overlap(overlap, chunk_size)
    chunks: list[MinimaxChunk] = []
    start_frame = 0
    two_chunk_span = (chunk_size * 2) - overlap

    while True:
        span = total_frames - start_frame

        if span <= chunk_size:
            chunks.append(
                MinimaxChunk(
                    start_frame=start_frame,
                    end_frame=total_frames - 1,
                    source_length=span,
                    target_length=snap_to_minimax_ceil(span),
                )
            )
            break

        if span <= two_chunk_span:
            first_length = choose_balanced_first_chunk_length(
                span, chunk_size, overlap
            )
            second_start = start_frame + first_length - overlap
            second_length = total_frames - second_start

            chunks.append(
                MinimaxChunk(
                    start_frame=start_frame,
                    end_frame=start_frame + first_length - 1,
                    source_length=first_length,
                    target_length=first_length,
                )
            )
            chunks.append(
                MinimaxChunk(
                    start_frame=second_start,
                    end_frame=total_frames - 1,
                    source_length=second_length,
                    target_length=snap_to_minimax_ceil(second_length),
                )
            )
            break

        chunks.append(
            MinimaxChunk(
                start_frame=start_frame,
                end_frame=start_frame + chunk_size - 1,
                source_length=chunk_size,
                target_length=chunk_size,
            )
        )
        start_frame += chunk_size - overlap

    return chunks
