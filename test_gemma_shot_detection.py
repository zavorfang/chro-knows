import unittest

from gemma_shot_detection import (
    AnalysisChunk,
    ChunkShotAnalysis,
    DetectedShot,
    GemmaShot,
    TraditionalCutCandidate,
    description_similarity,
    detect_cut_candidates_from_scores,
    finalize_shot_ranges,
    match_chunk_shots_to_candidates,
    parse_chunk_shot_response,
    plan_shot_analysis_chunks,
    should_merge_boundary_duplicate,
)


class GemmaShotDetectionTests(unittest.TestCase):
    def test_plan_shot_analysis_chunks_caps_each_window_at_59_seconds(self):
        chunks = plan_shot_analysis_chunks(total_frames=3600, fps=24)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].start_frame, 0)
        self.assertEqual(chunks[0].end_frame, 1415)
        self.assertLessEqual(chunks[0].duration_seconds, 59.0)
        self.assertEqual(chunks[1].start_frame, 1416)
        self.assertEqual(chunks[2].end_frame, 3599)

    def test_parse_chunk_shot_response_accepts_markdown_wrapped_json(self):
        response = """
        ```json
        {
            "first_shot_signature": "wide skyline",
            "last_shot_signature": "close-up on actor",
            "shots": [
                {
                    "start_seconds": 0.0,
                    "description": "Wide skyline with slow pan.",
                    "continues_from_previous": false,
                    "continues_to_next": true,
                    "confidence": 0.81
                },
                {
                    "start_seconds": 12.4,
                    "description": "Close-up on actor speaking to camera.",
                    "confidence": 0.92
                }
            ]
        }
        ```
        """
        shots, first_signature, last_signature = parse_chunk_shot_response(
            response, clip_duration_seconds=59.0
        )
        self.assertEqual(first_signature, "wide skyline")
        self.assertEqual(last_signature, "close-up on actor")
        self.assertEqual(len(shots), 2)
        self.assertEqual(shots[1].description, "Close-up on actor speaking to camera.")
        self.assertAlmostEqual(shots[1].start_seconds, 12.4)

    def test_detect_cut_candidates_from_scores_collapses_peak_runs(self):
        scores = [0.1, 0.12, 0.95, 0.88, 0.2, 0.1, 0.14, 0.16, 1.18, 0.97, 0.15]
        candidates = detect_cut_candidates_from_scores(scores, start_frame=100, fps=24)
        self.assertEqual([candidate.frame for candidate in candidates], [103, 109])
        self.assertGreaterEqual(candidates[1].confidence, candidates[0].confidence)

    def test_match_chunk_shots_to_candidates_snaps_internal_boundaries(self):
        analysis = ChunkShotAnalysis(
            chunk=AnalysisChunk(index=1, start_frame=1416, end_frame=2831, fps=24),
            shots=[
                GemmaShot(start_seconds=0.0, description="Continuing hallway shot."),
                GemmaShot(start_seconds=10.9, description="Close-up on hand opening door."),
                GemmaShot(start_seconds=22.2, description="Wide office interior."),
            ],
        )
        candidates = [
            TraditionalCutCandidate(frame=1678, score=1.0, confidence=0.88, kind="strong"),
            TraditionalCutCandidate(frame=1949, score=1.1, confidence=0.91, kind="strong"),
        ]
        matched = match_chunk_shots_to_candidates(analysis, candidates, tolerance_seconds=1.5)
        self.assertEqual([shot.start_frame for shot in matched], [1416, 1678, 1949])
        self.assertEqual(matched[1].description, "Close-up on hand opening door.")

    def test_match_chunk_shots_to_candidates_ignores_unmatched_internal_guess(self):
        analysis = ChunkShotAnalysis(
            chunk=AnalysisChunk(index=0, start_frame=0, end_frame=600, fps=24),
            shots=[
                GemmaShot(start_seconds=0.0, description="Continuous push-in on speaker."),
                GemmaShot(start_seconds=9.0, description="Same speaker wider because camera zooms out."),
            ],
        )
        matched = match_chunk_shots_to_candidates(analysis, [], tolerance_seconds=1.5)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].start_frame, 0)

    def test_boundary_merge_prefers_same_shot_without_strong_seam_cut(self):
        previous = DetectedShot(
            start_frame=1200,
            description="Medium shot of two people at a desk.",
            continues_to_next=True,
        )
        following = DetectedShot(
            start_frame=1416,
            description="Two people talking at the same desk from the same angle.",
            continues_from_previous=True,
        )
        seam = TraditionalCutCandidate(frame=1416, score=0.4, confidence=0.18, kind="clear")
        self.assertGreater(description_similarity(previous.description, following.description), 0.4)
        self.assertTrue(
            should_merge_boundary_duplicate(
                previous,
                following,
                boundary_same_shot=True,
                seam_candidate=seam,
            )
        )

    def test_finalize_shot_ranges_derives_end_frames_and_timestamps(self):
        shots = [
            DetectedShot(start_frame=0, description="Opening wide shot."),
            DetectedShot(start_frame=48, description="Close-up."),
            DetectedShot(start_frame=120, description="Reaction shot."),
        ]
        finalized = finalize_shot_ranges(shots, fps=24, clip_end_frame=167)
        self.assertEqual(finalized[0]["end_frame"], 47)
        self.assertEqual(finalized[1]["start_timestamp"], "00:00:02.000")
        self.assertEqual(finalized[2]["end_timestamp"], "00:00:06.958")


if __name__ == "__main__":
    unittest.main()
