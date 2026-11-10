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
    if length < 1:
        raise ValueError("length must be >= 1")
    if interval < 1:
        raise ValueError("interval must be >= 1")
    return (length - 1) // interval + 1


def _half_up(x: float) -> int:
    # Round half up (not Python's banker's round()) so results are identical on
    # every platform and .5 always goes to the later frame. It is monotonic, so
    # frames that are >= 1 apart before rounding stay distinct.
    return int(math.floor(x + 0.5))


def allowed_cell_counts(
    max_dim: int = DEFAULT_MAX_DIM, rectangular: bool = False
) -> list[int]:
    if max_dim < 1:
        raise ValueError("max_dim must be >= 1")
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
    if length < 1:
        raise ValueError("shot must contain at least one frame")
    if interval < 1:
        raise ValueError("interval must be >= 1")
    if not sizes:
        raise ValueError("at least one grid size is required")
    if max_ratio < 1.0:
        raise ValueError("max_ratio must be >= 1.0")
    strategy = FitStrategy(strategy)

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
    if not options:
        raise ValueError("no grid layout fits this shot")

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
    if length < 1:
        raise ValueError("shot must contain at least one frame")
    if interval < 1:
        raise ValueError("interval must be >= 1")
    if total < 1:
        raise ValueError("total must be >= 1")
    if total > length:
        raise ValueError("cannot select more frames than the shot contains")

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
