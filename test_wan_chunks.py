import unittest

from wan_chunks import (
    WAN_CHUNK_SIZE,
    choose_balanced_first_chunk_length,
    normalize_chunk_overlap,
    normalize_wan_chunk_size,
    plan_wan_chunks,
    snap_to_wan_ceil,
    snap_to_wan_floor,
)


class WanChunkTests(unittest.TestCase):
    def test_snap_to_wan_ceil(self):
        self.assertEqual(snap_to_wan_ceil(10), 13)
        self.assertEqual(snap_to_wan_ceil(13), 13)
        self.assertEqual(snap_to_wan_ceil(WAN_CHUNK_SIZE), WAN_CHUNK_SIZE)

    def test_snap_to_wan_floor(self):
        self.assertEqual(snap_to_wan_floor(88), 85)
        self.assertEqual(snap_to_wan_floor(85), 85)
        self.assertEqual(normalize_wan_chunk_size(WAN_CHUNK_SIZE), WAN_CHUNK_SIZE)

    def test_overlap_is_clamped_to_supported_range(self):
        self.assertEqual(normalize_chunk_overlap(0, 85), 0)
        self.assertEqual(normalize_chunk_overlap(2, 85), 4)
        self.assertEqual(normalize_chunk_overlap(40, 85), 32)
        self.assertEqual(normalize_chunk_overlap(8, 5), 4)

    def test_short_clip_pads_to_next_valid_length(self):
        chunks = plan_wan_chunks(10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].source_length, 10)
        self.assertEqual(chunks[0].target_length, 13)
        self.assertEqual(chunks[0].pad_count, 3)

    def test_balanced_first_chunk_prefers_rounded_up_half(self):
        self.assertEqual(choose_balanced_first_chunk_length(88, 85), 45)
        self.assertEqual(choose_balanced_first_chunk_length(115, 85), 57)

    def test_requested_chunk_size_snaps_down_before_planning(self):
        chunks = plan_wan_chunks(100, 88)
        self.assertEqual([chunk.source_length for chunk in chunks], [53, 47])
        self.assertEqual([chunk.target_length for chunk in chunks], [53, 49])

    def test_exact_two_chunks_stays_as_two_full_chunks(self):
        chunks = plan_wan_chunks(186)
        self.assertEqual([chunk.source_length for chunk in chunks], [93, 93])
        self.assertEqual([chunk.target_length for chunk in chunks], [93, 93])

    def test_last_two_chunks_are_rebalanced_to_avoid_tiny_trailer(self):
        chunks = plan_wan_chunks(258, 85)
        self.assertEqual([chunk.source_length for chunk in chunks], [85, 85, 45, 43])
        self.assertEqual([chunk.target_length for chunk in chunks], [85, 85, 45, 45])
        self.assertEqual([chunk.pad_count for chunk in chunks], [0, 0, 0, 2])

    def test_only_final_chunk_is_padded_after_rebalancing(self):
        chunks = plan_wan_chunks(200, 85)
        self.assertEqual([chunk.source_length for chunk in chunks], [85, 57, 58])
        self.assertEqual([chunk.target_length for chunk in chunks], [85, 57, 61])
        self.assertEqual([chunk.pad_count for chunk in chunks], [0, 0, 3])

    def test_overlap_changes_stride_and_tail_split(self):
        chunks = plan_wan_chunks(258, 85, 8)
        self.assertEqual([chunk.start_frame for chunk in chunks], [0, 77, 154, 203])
        self.assertEqual([chunk.source_length for chunk in chunks], [85, 85, 57, 55])
        self.assertEqual([chunk.target_length for chunk in chunks], [85, 85, 57, 57])
        self.assertEqual([chunk.pad_count for chunk in chunks], [0, 0, 0, 2])


if __name__ == "__main__":
    unittest.main()
