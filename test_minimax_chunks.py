import unittest

from minimax_chunks import (
    MINIMAX_DEFAULT_CHUNK,
    MINIMAX_MIN_FRAMES,
    MINIMAX_OVERLAP_MAX,
    MINIMAX_OVERLAP_MIN,
    MINIMAX_STRIDE,
    MinimaxChunk,
    choose_balanced_first_chunk_length,
    normalize_minimax_chunk_size,
    normalize_minimax_overlap,
    plan_minimax_chunks,
    snap_to_minimax_ceil,
    snap_to_minimax_floor,
)


class TestSnapToMinimaxCeil(unittest.TestCase):
    def test_exact_values_unchanged(self):
        """Values already on a (17k+5) boundary pass through."""
        for k in range(10):
            val = 17 * k + 5
            self.assertEqual(snap_to_minimax_ceil(val), val)

    def test_rounds_up(self):
        self.assertEqual(snap_to_minimax_ceil(6), 22)
        self.assertEqual(snap_to_minimax_ceil(10), 22)
        self.assertEqual(snap_to_minimax_ceil(21), 22)
        self.assertEqual(snap_to_minimax_ceil(23), 39)
        self.assertEqual(snap_to_minimax_ceil(38), 39)
        self.assertEqual(snap_to_minimax_ceil(40), 56)

    def test_small_values_snap_to_minimum(self):
        for n in range(1, 6):
            self.assertEqual(snap_to_minimax_ceil(n), 5)

    def test_raises_on_zero_or_negative(self):
        with self.assertRaises(ValueError):
            snap_to_minimax_ceil(0)
        with self.assertRaises(ValueError):
            snap_to_minimax_ceil(-1)


class TestSnapToMinimaxFloor(unittest.TestCase):
    def test_exact_values_unchanged(self):
        for k in range(10):
            val = 17 * k + 5
            self.assertEqual(snap_to_minimax_floor(val), val)

    def test_rounds_down(self):
        self.assertEqual(snap_to_minimax_floor(6), 5)
        self.assertEqual(snap_to_minimax_floor(21), 5)
        self.assertEqual(snap_to_minimax_floor(23), 22)
        self.assertEqual(snap_to_minimax_floor(38), 22)
        self.assertEqual(snap_to_minimax_floor(40), 39)

    def test_small_values_snap_to_minimum(self):
        for n in range(1, 6):
            self.assertEqual(snap_to_minimax_floor(n), 5)

    def test_raises_on_zero_or_negative(self):
        with self.assertRaises(ValueError):
            snap_to_minimax_floor(0)
        with self.assertRaises(ValueError):
            snap_to_minimax_floor(-1)


class TestNormalizeChunkSize(unittest.TestCase):
    def test_snaps_down(self):
        self.assertEqual(normalize_minimax_chunk_size(124), 124)
        self.assertEqual(normalize_minimax_chunk_size(130), 124)
        self.assertEqual(normalize_minimax_chunk_size(140), 124)
        self.assertEqual(normalize_minimax_chunk_size(141), 141)

    def test_default_chunk_is_valid(self):
        self.assertEqual(
            normalize_minimax_chunk_size(MINIMAX_DEFAULT_CHUNK),
            MINIMAX_DEFAULT_CHUNK,
        )
        # Verify it satisfies (17k + 5)
        self.assertEqual((MINIMAX_DEFAULT_CHUNK - 5) % 17, 0)


class TestNormalizeOverlap(unittest.TestCase):
    def test_zero_overlap(self):
        self.assertEqual(normalize_minimax_overlap(0, 124), 0)
        self.assertEqual(normalize_minimax_overlap(-5, 124), 0)

    def test_snaps_to_stride_multiple(self):
        self.assertEqual(normalize_minimax_overlap(17, 124), 17)
        self.assertEqual(normalize_minimax_overlap(20, 124), 17)
        self.assertEqual(normalize_minimax_overlap(34, 124), 34)
        self.assertEqual(normalize_minimax_overlap(40, 124), 34)
        self.assertEqual(normalize_minimax_overlap(51, 124), 51)

    def test_clamps_to_max(self):
        self.assertEqual(normalize_minimax_overlap(100, 124), MINIMAX_OVERLAP_MAX)

    def test_minimum_enforced(self):
        result = normalize_minimax_overlap(5, 124)
        self.assertEqual(result, MINIMAX_STRIDE)


class TestPlanMinimaxChunksSingleChunk(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(plan_minimax_chunks(0), [])

    def test_tiny_clip(self):
        chunks = plan_minimax_chunks(3)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].source_length, 3)
        self.assertEqual(chunks[0].target_length, 5)
        self.assertEqual(chunks[0].pad_count, 2)

    def test_exact_boundary(self):
        chunks = plan_minimax_chunks(22)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].target_length, 22)
        self.assertEqual(chunks[0].pad_count, 0)

    def test_just_above_boundary(self):
        chunks = plan_minimax_chunks(23)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].target_length, 39)
        self.assertEqual(chunks[0].pad_count, 16)

    def test_fits_in_one_chunk(self):
        chunks = plan_minimax_chunks(100, chunk_size=124)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].source_length, 100)
        self.assertEqual(chunks[0].target_length, 107)  # 17*6+5

    def test_exact_chunk_size(self):
        chunks = plan_minimax_chunks(124, chunk_size=124)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].target_length, 124)
        self.assertEqual(chunks[0].pad_count, 0)


class TestPlanMinimaxChunksTwoChunks(unittest.TestCase):
    def test_two_chunk_split(self):
        # 200 frames with chunk_size=124 → must split into 2
        chunks = plan_minimax_chunks(200, chunk_size=124)
        self.assertEqual(len(chunks), 2)
        # Both target lengths must be valid (17k+5)
        for c in chunks:
            self.assertEqual((c.target_length - 5) % 17, 0)
        # Entire span must be covered
        self.assertEqual(chunks[0].start_frame, 0)
        self.assertEqual(chunks[1].end_frame, 199)

    def test_balanced_split(self):
        """Two chunks should be roughly balanced."""
        chunks = plan_minimax_chunks(200, chunk_size=124)
        ratio = chunks[0].source_length / chunks[1].source_length
        self.assertGreater(ratio, 0.5)
        self.assertLess(ratio, 2.0)


class TestPlanMinimaxChunksMultiChunk(unittest.TestCase):
    def test_three_chunks(self):
        chunks = plan_minimax_chunks(300, chunk_size=124)
        self.assertGreaterEqual(len(chunks), 2)
        # All target lengths valid
        for c in chunks:
            self.assertEqual((c.target_length - 5) % 17, 0)
        # Only the last chunk may be padded
        for c in chunks[:-1]:
            self.assertEqual(c.pad_count, 0)

    def test_many_chunks(self):
        chunks = plan_minimax_chunks(1000, chunk_size=124)
        self.assertGreaterEqual(len(chunks), 7)
        for c in chunks:
            self.assertEqual((c.target_length - 5) % 17, 0)
        for c in chunks[:-1]:
            self.assertEqual(c.pad_count, 0)


class TestPlanMinimaxChunksWithOverlap(unittest.TestCase):
    def test_overlap_creates_overlapping_ranges(self):
        chunks = plan_minimax_chunks(300, chunk_size=124, overlap=17)
        self.assertGreaterEqual(len(chunks), 2)
        for i in range(len(chunks) - 1):
            # Each consecutive pair should overlap
            self.assertGreater(chunks[i].end_frame, chunks[i + 1].start_frame - 1)

    def test_all_targets_valid_with_overlap(self):
        chunks = plan_minimax_chunks(500, chunk_size=124, overlap=34)
        for c in chunks:
            self.assertEqual((c.target_length - 5) % 17, 0)


class TestPlanMinimaxChunksPadding(unittest.TestCase):
    def test_only_last_chunk_padded(self):
        """Interior chunks must never be padded."""
        for total in [150, 250, 350, 450, 550, 999]:
            chunks = plan_minimax_chunks(total, chunk_size=124)
            for c in chunks[:-1]:
                self.assertEqual(
                    c.pad_count, 0,
                    f"total={total}: interior chunk has padding {c}",
                )

    def test_padding_uses_last_frame(self):
        """Padding count should never exceed one stride minus 1."""
        for total in range(1, 300):
            chunks = plan_minimax_chunks(total, chunk_size=124)
            last = chunks[-1]
            self.assertLess(last.pad_count, MINIMAX_STRIDE)
            self.assertGreaterEqual(last.pad_count, 0)


class TestPlanMinimaxChunksContiguity(unittest.TestCase):
    def test_full_coverage_no_overlap(self):
        """All source frames should be covered exactly once with no overlap."""
        total = 500
        chunks = plan_minimax_chunks(total, chunk_size=124, overlap=0)
        covered = set()
        for c in chunks:
            for f in range(c.start_frame, c.end_frame + 1):
                covered.add(f)
        self.assertEqual(covered, set(range(total)))

    def test_full_coverage_with_overlap(self):
        """All source frames should be covered (overlaps allowed)."""
        total = 500
        chunks = plan_minimax_chunks(total, chunk_size=124, overlap=17)
        covered = set()
        for c in chunks:
            for f in range(c.start_frame, c.end_frame + 1):
                covered.add(f)
        self.assertEqual(covered, set(range(total)))


class TestChooseBalancedFirstChunkLength(unittest.TestCase):
    def test_result_is_valid(self):
        for span in range(10, 250):
            result = choose_balanced_first_chunk_length(span, 124)
            self.assertEqual((result - 5) % 17, 0)

    def test_does_not_exceed_chunk_size(self):
        for span in range(10, 250):
            result = choose_balanced_first_chunk_length(span, 124)
            self.assertLessEqual(result, 124)


class TestMinimaxChunkDataclass(unittest.TestCase):
    def test_pad_count(self):
        c = MinimaxChunk(start_frame=0, end_frame=14, source_length=15, target_length=22)
        self.assertEqual(c.pad_count, 7)

    def test_no_padding(self):
        c = MinimaxChunk(start_frame=0, end_frame=21, source_length=22, target_length=22)
        self.assertEqual(c.pad_count, 0)

    def test_frozen(self):
        c = MinimaxChunk(start_frame=0, end_frame=4, source_length=5, target_length=5)
        with self.assertRaises(AttributeError):
            c.start_frame = 10


if __name__ == "__main__":
    unittest.main()
