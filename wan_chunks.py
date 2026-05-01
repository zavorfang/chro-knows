from dataclasses import dataclass


WAN_CHUNK_SIZE = 93
WAN_OVERLAP_MIN = 4
WAN_OVERLAP_MAX = 32


@dataclass(frozen=True)
class WanChunk:
    start_frame: int
    end_frame: int
    source_length: int
    target_length: int

    @property
    def pad_count(self) -> int:
        return self.target_length - self.source_length


def snap_to_wan_ceil(n: int) -> int:
    if n <= 0:
        raise ValueError("WAN frame counts must be positive.")

    if (n - 1) % 4 == 0:
        return n

    return ((n - 1) // 4 + 1) * 4 + 1


def snap_to_wan_floor(n: int) -> int:
    if n <= 0:
        raise ValueError("WAN frame counts must be positive.")

    if n <= 1:
        return 1

    return ((n - 1) // 4) * 4 + 1


def normalize_wan_chunk_size(chunk_size: int) -> int:
    return snap_to_wan_floor(chunk_size)


def normalize_chunk_overlap(overlap: int, chunk_size: int) -> int:
    chunk_size = normalize_wan_chunk_size(chunk_size)
    if overlap <= 0:
        return 0

    max_overlap = min(WAN_OVERLAP_MAX, chunk_size - 1)
    if max_overlap <= 0:
        return 0

    if max_overlap < WAN_OVERLAP_MIN:
        return max_overlap

    return max(WAN_OVERLAP_MIN, min(overlap, max_overlap))


def choose_balanced_first_chunk_length(
    span: int, chunk_size: int, overlap: int = 0
) -> int:
    ideal = (span + overlap) // 2
    min_first = max(1, span - chunk_size + overlap)
    max_first = chunk_size

    rounded_up = snap_to_wan_ceil(ideal)
    if min_first <= rounded_up <= max_first:
        return rounded_up

    rounded_min = snap_to_wan_ceil(min_first)
    if rounded_min <= max_first:
        return rounded_min

    return snap_to_wan_floor(max_first)


def plan_wan_chunks(
    total_frames: int, chunk_size: int = WAN_CHUNK_SIZE, overlap: int = 0
) -> list[WanChunk]:
    if total_frames <= 0:
        return []

    if chunk_size <= 0:
        raise ValueError("Chunk size must be positive.")

    chunk_size = normalize_wan_chunk_size(chunk_size)
    overlap = normalize_chunk_overlap(overlap, chunk_size)
    chunks: list[WanChunk] = []
    start_frame = 0
    two_chunk_span = (chunk_size * 2) - overlap

    while True:
        span = total_frames - start_frame

        if span <= chunk_size:
            chunks.append(
                WanChunk(
                    start_frame=start_frame,
                    end_frame=total_frames - 1,
                    source_length=span,
                    target_length=snap_to_wan_ceil(span),
                )
            )
            break

        if span <= two_chunk_span:
            first_length = choose_balanced_first_chunk_length(span, chunk_size, overlap)
            second_start = start_frame + first_length - overlap
            second_length = total_frames - second_start

            chunks.append(
                WanChunk(
                    start_frame=start_frame,
                    end_frame=start_frame + first_length - 1,
                    source_length=first_length,
                    target_length=first_length,
                )
            )
            chunks.append(
                WanChunk(
                    start_frame=second_start,
                    end_frame=total_frames - 1,
                    source_length=second_length,
                    target_length=snap_to_wan_ceil(second_length),
                )
            )
            break

        chunks.append(
            WanChunk(
                start_frame=start_frame,
                end_frame=start_frame + chunk_size - 1,
                source_length=chunk_size,
                target_length=chunk_size,
            )
        )
        start_frame += chunk_size - overlap

    return chunks
