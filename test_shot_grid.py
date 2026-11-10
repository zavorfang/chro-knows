import math
import unittest

from shot_grid import (
    DEFAULT_MAX_DIM,
    DEFAULT_MAX_RATIO,
    FitStrategy,
    Shot,
    allowed_cell_counts,
    choose_layout,
    plan_shot,
    samples_at_interval,
    select_frames,
    shots_from_bookmarks,
)


SQUARE_SIZES = [1, 4, 9, 16, 25]


def _plan_for_samples(samples, **kwargs):
    length = 4 * samples - 3
    return plan_shot(Shot(1, 0, length - 1), interval=4, **kwargs)


class SampleCountTests(unittest.TestCase):
    def test_samples_at_interval(self):
        cases = [
            (1, 4, 1),
            (4, 4, 1),
            (5, 4, 2),
            (100, 4, 25),
            (101, 4, 26),
            (700, 1, 700),
            (700, 24, 30),
        ]
        for length, interval, expected in cases:
            self.assertEqual(samples_at_interval(length, interval), expected)

    def test_bad_sample_input(self):
        with self.assertRaises(ValueError):
            samples_at_interval(0, 4)
        with self.assertRaises(ValueError):
            samples_at_interval(10, 0)


class LayoutTableTests(unittest.TestCase):
    def test_square_layout_by_sample_count(self):
        cases = [
            (1, 1, 1, 1),
            (2, 1, 2, 2),
            (5, 1, 2, 2),
            (6, 1, 3, 3),
            (11, 1, 3, 3),
            (12, 1, 4, 4),
            (19, 1, 4, 4),
            (20, 1, 5, 5),
            (31, 1, 5, 5),
            (32, 2, 4, 4),
            (39, 2, 4, 4),
            (40, 2, 5, 5),
            (62, 2, 5, 5),
            (63, 3, 5, 5),
            (93, 3, 5, 5),
            (94, 4, 5, 5),
            (125, 4, 5, 5),
            (126, 5, 5, 5),
        ]
        for samples, parts, rows, cols in cases:
            with self.subTest(samples=samples):
                plan = _plan_for_samples(samples)
                self.assertEqual(len(plan.parts), parts)
                self.assertEqual((plan.parts[0].rows, plan.parts[0].cols), (rows, cols))
                self.assertEqual(plan.empty_cells, 0)
                self.assertEqual(
                    len({(p.rows, p.cols) for p in plan.parts}), 1
                )


class WorkedExampleTests(unittest.TestCase):
    def _assert_plan(self, interval, length, parts, rows, cols, spacing):
        plan = plan_shot(Shot(1, 0, length - 1), interval=interval)
        self.assertEqual(len(plan.parts), parts)
        self.assertEqual((plan.parts[0].rows, plan.parts[0].cols), (rows, cols))
        self.assertEqual(plan.empty_cells, 0)
        if spacing is None:
            self.assertIsNone(plan.effective_interval)
        else:
            self.assertAlmostEqual(plan.effective_interval, spacing, places=2)
        return plan

    def test_worked_examples(self):
        cases = [
            (4, 1, 1, 1, 1, None),
            (4, 6, 1, 2, 2, 1.67),
            (4, 10, 1, 2, 2, 3.00),
            (4, 33, 1, 3, 3, 4.00),
            (4, 50, 1, 4, 4, 3.27),
            (4, 65, 1, 4, 4, 4.27),
            (4, 80, 1, 5, 5, 3.29),
            (4, 101, 1, 5, 5, 4.17),
            (4, 124, 1, 5, 5, 5.00),
            (4, 128, 2, 4, 4, 4.00),
            (4, 160, 2, 5, 5, 3.24),
            (4, 240, 2, 5, 5, 4.82),
            (4, 300, 3, 5, 5, 4.00),
            (4, 400, 4, 5, 5, 4.00),
            (12, 100, 1, 3, 3, 12.00),
            (12, 240, 1, 5, 5, 9.96),
            (12, 400, 2, 4, 4, 12.77),
        ]
        for interval, length, parts, rows, cols, spacing in cases:
            with self.subTest(interval=interval, length=length):
                self._assert_plan(
                    interval, length, parts, rows, cols, spacing
                )

    def test_65_frame_shot_drops_one_lattice_frame(self):
        plan = plan_shot(Shot(1, 0, 64), interval=4)
        self.assertEqual(
            plan.all_frames,
            (0, 4, 8, 12, 16, 20, 24, 28, 36, 40, 44, 48, 52, 56, 60, 64),
        )

    def test_50_frame_shot_spreads_padding_evenly(self):
        plan = plan_shot(Shot(1, 0, 49), interval=4)
        self.assertEqual(
            plan.all_frames,
            (0, 3, 7, 10, 13, 16, 20, 23, 26, 29, 33, 36, 39, 42, 46, 49),
        )

    def test_strategy_comparison(self):
        cases = [
            (65, 1, 4, 1, 4, 1, 5),
            (93, 1, 5, 1, 4, 1, 5),
            (101, 1, 5, 1, 5, 2, 4),
            (237, 2, 5, 2, 5, 3, 5),
        ]
        for length, bparts, brows, tparts, trows, fparts, frows in cases:
            with self.subTest(length=length):
                balanced = plan_shot(
                    Shot(1, 0, length - 1), interval=4,
                    strategy=FitStrategy.BALANCED,
                )
                trim = plan_shot(
                    Shot(1, 0, length - 1), interval=4,
                    strategy=FitStrategy.TRIM,
                )
                fill = plan_shot(
                    Shot(1, 0, length - 1), interval=4,
                    strategy=FitStrategy.FILL,
                )
                self.assertEqual((len(balanced.parts), balanced.parts[0].rows), (bparts, brows))
                self.assertEqual((len(trim.parts), trim.parts[0].rows), (tparts, trows))
                self.assertEqual((len(fill.parts), fill.parts[0].rows), (fparts, frows))
                self.assertLessEqual(trim.total_frames, samples_at_interval(length, 4))
                self.assertGreaterEqual(fill.total_frames, samples_at_interval(length, 4))

    def test_compact_rectangles(self):
        cases = [
            (5, 1, 1, 2, 4.00),
            (49, 1, 3, 4, 4.36),
            (85, 1, 4, 5, 4.42),
        ]
        for length, parts, rows, cols, spacing in cases:
            with self.subTest(length=length):
                plan = plan_shot(
                    Shot(1, 0, length - 1), interval=4,
                    rectangular=True,
                )
                self.assertEqual((len(plan.parts), plan.parts[0].rows, plan.parts[0].cols),
                                 (parts, rows, cols))
                self.assertAlmostEqual(plan.effective_interval, spacing, places=2)


class InvariantTests(unittest.TestCase):
    def test_planner_invariants(self):
        intervals = (1, 2, 3, 4, 6, 8, 12, 24)
        max_dims = (3, 4, 5)
        for length in range(1, 701):
            for interval in intervals:
                for max_dim in max_dims:
                    for rectangular in (False, True):
                        sizes = allowed_cell_counts(max_dim, rectangular)
                        for strategy in FitStrategy:
                            with self.subTest(
                                length=length, interval=interval,
                                max_dim=max_dim, rectangular=rectangular,
                                strategy=strategy,
                            ):
                                plan = plan_shot(
                                    Shot(1, 0, length - 1),
                                    interval=interval,
                                    max_dim=max_dim,
                                    rectangular=rectangular,
                                    strategy=strategy,
                                )
                                frames = plan.all_frames
                                n = plan.samples_at_interval

                                self.assertEqual(plan.empty_cells, 0)
                                self.assertEqual(len(frames), len(set(frames)))
                                self.assertEqual(frames, tuple(sorted(frames)))
                                self.assertTrue(all(0 <= f < length for f in frames))
                                self.assertLessEqual(plan.total_frames, length)
                                self.assertLessEqual(max_dim, DEFAULT_MAX_DIM)
                                self.assertEqual(
                                    len({(p.rows, p.cols) for p in plan.parts}), 1
                                )
                                for part in plan.parts:
                                    self.assertEqual(
                                        len(part.frames), part.rows * part.cols
                                    )
                                    self.assertLessEqual(
                                        max(part.rows, part.cols), max_dim
                                    )
                                    if not rectangular:
                                        self.assertEqual(part.rows, part.cols)

                                if n <= max_dim * max_dim:
                                    self.assertEqual(len(plan.parts), 1)

                                cap = max(sizes)
                                g_min = -(-n // cap)
                                if g_min == 1:
                                    grid_counts = [1]
                                else:
                                    grid_counts = range(g_min - 1, g_min + 3)
                                feasible = [
                                    (g, c)
                                    for g in grid_counts
                                    for c in sizes
                                    if g * c <= length
                                ]
                                if strategy is FitStrategy.TRIM:
                                    if any(g * c <= n for g, c in feasible):
                                        self.assertLessEqual(plan.total_frames, n)
                                elif strategy is FitStrategy.FILL:
                                    if any(g * c >= n for g, c in feasible):
                                        self.assertGreaterEqual(plan.total_frames, n)

    def test_frame_choice_rules(self):
        for length in range(1, 200):
            for interval in (1, 2, 3, 4, 6, 8, 12, 24):
                n = samples_at_interval(length, interval)
                shot = Shot(1, 0, length - 1)
                for total in (1, max(1, n - 1), n, min(length, n + 1), length):
                    if total < 1 or total > length:
                        continue
                    with self.subTest(length=length, interval=interval, total=total):
                        frames = select_frames(shot, interval, total)
                        self.assertEqual(len(frames), total)
                        self.assertEqual(len(set(frames)), total)
                        self.assertEqual(frames, tuple(sorted(frames)))
                        if total <= n:
                            for frame in frames:
                                self.assertEqual((frame - shot.start) % interval, 0)
                        if total > n and total > 1:
                            self.assertEqual(frames[0], shot.start)
                            self.assertEqual(frames[-1], shot.end)


class BookmarkShotTests(unittest.TestCase):
    def test_unsorted_and_duplicate_bookmarks(self):
        shots = shots_from_bookmarks([10, 0, 5, 5], 20)
        self.assertEqual(
            [(s.index, s.start, s.end) for s in shots],
            [(1, 0, 4), (2, 5, 9), (3, 10, 20)],
        )

    def test_out_of_range_and_empty_bookmarks(self):
        self.assertEqual(
            [(s.index, s.start, s.end) for s in shots_from_bookmarks([-1, 5, 30], 20)],
            [(1, 5, 20)],
        )
        self.assertEqual(shots_from_bookmarks([], 20), [])
        self.assertEqual(shots_from_bookmarks([30], 20), [])

    def test_one_bookmark(self):
        shots = shots_from_bookmarks([7], 20)
        self.assertEqual([(s.index, s.start, s.end) for s in shots], [(1, 7, 20)])

    def test_lead_in_is_optional(self):
        self.assertEqual(
            [(s.index, s.start, s.end) for s in shots_from_bookmarks([5, 10], 20)],
            [(1, 5, 9), (2, 10, 20)],
        )
        self.assertEqual(
            [(s.index, s.start, s.end)
             for s in shots_from_bookmarks([5, 10], 20, include_lead_in=True)],
            [(0, 0, 4), (1, 5, 9), (2, 10, 20)],
        )
        self.assertEqual(
            shots_from_bookmarks([0, 10], 20, include_lead_in=True)[0].index,
            1,
        )

    def test_range_clipping(self):
        shots = shots_from_bookmarks([0, 5, 10, 12, 20], 15, clip_start=8)
        self.assertEqual(
            [(s.index, s.start, s.end) for s in shots],
            [(1, 10, 11), (2, 12, 15)],
        )
        shots = shots_from_bookmarks(
            [0, 5, 10, 12, 20], 15, clip_start=8, include_lead_in=True
        )
        self.assertEqual(
            [(s.index, s.start, s.end) for s in shots],
            [(0, 8, 9), (1, 10, 11), (2, 12, 15)],
        )


class BadInputTests(unittest.TestCase):
    def test_interval_zero(self):
        with self.assertRaises(ValueError):
            plan_shot(Shot(1, 0, 10), interval=0)

    def test_zero_length_shot(self):
        with self.assertRaises(ValueError):
            plan_shot(Shot(1, 5, 4), interval=4)

    def test_select_frames_limits(self):
        shot = Shot(1, 0, 9)
        with self.assertRaises(ValueError):
            select_frames(shot, 4, 0)
        with self.assertRaises(ValueError):
            select_frames(shot, 4, 11)

    def test_bad_planner_options(self):
        with self.assertRaises(ValueError):
            allowed_cell_counts(0)
        with self.assertRaises(ValueError):
            choose_layout(10, 4, [1, 4], max_ratio=0.9)
        with self.assertRaises(ValueError):
            choose_layout(10, 4, [])


if __name__ == "__main__":
    unittest.main()
