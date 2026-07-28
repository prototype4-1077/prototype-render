import os
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import hero
import motion
import still_reference


def stock(text, stock_id, url, **extra):
    scene = {
        "text": text,
        "query": text,
        "motion_kind": "video",
        "motion_mode": "stock",
        "motion_verified": True,
        "stock_id": stock_id,
        "stock_frame_url": url,
    }
    scene.update(extra)
    return scene


class ReferenceSelectionTests(unittest.TestCase):
    def test_hero_image_validation_rejects_a_truncated_jpeg(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "hero.jpg")
            Image.effect_noise((640, 360), 42).convert("RGB").save(
                path, quality=95, progressive=True
            )
            self.assertTrue(hero._valid_image(path))
            original_signature = hero._file_signature(path)
            scene = {"hero_raw_signature": original_signature}
            self.assertTrue(hero.source_matches(scene, path))

            with open(path, "rb+") as handle:
                handle.truncate(os.path.getsize(path) // 2)

            self.assertFalse(hero._valid_image(path))
            self.assertNotEqual(original_signature, hero._file_signature(path))
            self.assertFalse(hero.source_matches(scene, path))

    def test_semantic_relationship_beats_simple_timeline_proximity(self):
        script = {"scenes": [
            {
                "text": "The unopened mail arrives at your boundary.",
                "image_prompt": "sealed envelope offered through apartment doorway",
                "symbol_family": "architecture",
                "primary_symbol": "doorway",
                "hero": True,
                "motion_kind": "animated_still",
            },
            stock("cars cross a busy city intersection", "near", "https://x/near.jpg",
                  symbol_family="world_scale", primary_symbol="traffic"),
            stock("hand carries sealed envelope through front doorway", "related",
                  "https://x/related.jpg", symbol_family="architecture",
                  primary_symbol="doorway"),
        ]}
        ranked = still_reference.ranked_reference_scenes(script, 0)
        self.assertEqual(ranked[0][2], 2)
        self.assertGreater(ranked[0][0], ranked[1][0])

    def test_timeline_distance_breaks_an_equal_semantic_tie(self):
        target = {"text": "A compass turns.", "hero": True,
                  "motion_kind": "animated_still"}
        script = {"scenes": [
            stock("a compass turns", "far", "https://x/far.jpg"),
            {"text": "bridge"},
            target,
            stock("a compass turns", "near", "https://x/near.jpg"),
        ]}
        self.assertEqual(
            still_reference.ranked_reference_scenes(script, 2)[0][2], 3,
        )

    def test_unusable_public_frames_are_not_reference_candidates(self):
        scene = stock("door", "bad", "https://x/bad.jpg")
        scene["stock_frame_url_unusable"] = True
        self.assertFalse(still_reference.is_stock_reference_scene(scene))

    def test_binding_saves_the_exact_public_frame_and_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            script = {"scenes": [
                {"text": "a paper map", "hero": True,
                 "motion_kind": "animated_still"},
                stock("hands unfold a paper map", "map-7", "https://x/map.jpg"),
            ]}

            def fake_download(url, output):
                self.assertEqual(url, "https://x/map.jpg")
                Image.new("RGB", (640, 360), (90, 110, 120)).save(output)

            with mock.patch.object(
                    still_reference, "_download_snapshot", side_effect=fake_download):
                result = still_reference.bind_reference(td, script, 0)
            scene = script["scenes"][0]
            self.assertEqual(result["scene_index"], 1)
            self.assertEqual(scene["still_reference_stock_id"], "map-7")
            self.assertEqual(scene["still_reference_url"], "https://x/map.jpg")
            self.assertTrue(os.path.exists(os.path.join(td, scene["still_reference_frame"])))


class StillPolicyTests(unittest.TestCase):
    def test_defaults_upgrade_pan_zoom_and_static_stills_to_cinemagraph(self):
        for mode in ("pan", "zoom", "ken_burns", "static"):
            script = {"scenes": [{
                "source_image": "still.png",
                "motion_mode": mode,
                "motion_kind": motion.STATIC,
            }]}
            motion.apply_motion_defaults(script)
            scene = script["scenes"][0]
            self.assertEqual(scene["motion_mode"], "cinemagraph")
            self.assertEqual(scene["motion_kind"], motion.ANIMATED)
            self.assertEqual(script["still_image_policy"], still_reference.POLICY)

    def test_keyframes_keep_their_visible_transformation_mode(self):
        script = {"scenes": [{
            "keyframes": ["one.png", "two.png"],
            "motion_mode": "static",
        }]}
        motion.apply_motion_defaults(script)
        self.assertEqual(script["scenes"][0]["motion_mode"], "keyframes")

    def test_stock_acquisition_precedes_still_work(self):
        with tempfile.TemporaryDirectory() as td:
            clip = os.path.join(td, "clip_01.mp4")
            with open(clip, "wb") as handle:
                handle.write(b"0" * 100_001)
            script = {"scenes": [
                {"hero": True, "motion_kind": "animated_still"},
                {"motion_kind": "video", "motion_verified": True,
                 "stock_frame_url_checked": True},
                {"motion_kind": "video", "motion_verified": False},
            ]}
            self.assertEqual(still_reference.stock_targets(td, script), [2])

    def test_generated_graphic_is_not_retried_for_missing_stock_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            for index in (1, 2):
                clip = os.path.join(td, f"clip_{index:02d}.mp4")
                with open(clip, "wb") as handle:
                    handle.write(b"0" * 100_001)
            script = {"scenes": [
                {"hero": True, "motion_kind": "animated_still"},
                {
                    "motion_kind": "video",
                    "motion_mode": "generated_graphic",
                    "motion_verified": True,
                },
                {
                    "motion_kind": "video",
                    "motion_mode": "stock",
                    "motion_verified": True,
                    "stock_frame_url_checked": True,
                },
            ]}
            self.assertEqual(still_reference.stock_targets(td, script), [])

    def test_stock_video_is_retried_for_missing_reference_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            clip = os.path.join(td, "clip_01.mp4")
            with open(clip, "wb") as handle:
                handle.write(b"0" * 100_001)
            script = {"scenes": [
                {"hero": True, "motion_kind": "animated_still"},
                {
                    "motion_kind": "video",
                    "motion_mode": "stock",
                    "motion_verified": True,
                },
            ]}
            self.assertEqual(still_reference.stock_targets(td, script), [1])

    def test_validation_rejects_an_unreferenced_animated_still(self):
        with tempfile.TemporaryDirectory() as td:
            script = {"scenes": [{
                "hero": True,
                "motion_kind": "animated_still",
                "motion_mode": "cinemagraph",
            }]}
            with self.assertRaisesRegex(
                    still_reference.StillReferenceError, "closest-stock"):
                still_reference.validate(td, script)

    def test_completed_reference_and_motion_path_passes_validation(self):
        with tempfile.TemporaryDirectory() as td:
            script = {"scenes": [
                {"text": "a turning key", "hero": True,
                 "motion_kind": "animated_still", "motion_mode": "cinemagraph"},
                stock("a turning key in a lock", "key-1", "https://x/key.jpg"),
            ]}

            def fake_download(_url, output):
                Image.new("RGB", (640, 360), (100, 110, 120)).save(output)

            with mock.patch.object(
                    still_reference, "_download_snapshot", side_effect=fake_download):
                still_reference.bind_reference(td, script, 0)
            still_reference.mark_motion_complete(script["scenes"][0])
            self.assertTrue(still_reference.validate(td, script))

    @unittest.skipUnless(__import__("importlib").util.find_spec("cv2"),
                         "OpenCV is installed by pipeline requirements")
    def test_local_enhancement_preserves_original_and_outputs_band_geometry(self):
        with tempfile.TemporaryDirectory() as td:
            source = os.path.join(td, "source.jpg")
            reference = os.path.join(td, "reference.jpg")
            output = os.path.join(td, "enhanced.jpg")
            Image.new("RGB", (300, 500), (24, 28, 34)).save(source)
            Image.new("RGB", (640, 360), (105, 120, 130)).save(reference)
            with open(source, "rb") as handle:
                before = handle.read()
            still_reference.enhance_image(source, reference, output)
            with open(source, "rb") as handle:
                self.assertEqual(handle.read(), before)
            with Image.open(output) as image:
                self.assertEqual(image.size, (still_reference.BAND_WIDTH,
                                              still_reference.BAND_HEIGHT))


class HeroConditioningTests(unittest.TestCase):
    def test_generation_url_uses_kontext_and_the_exact_reference(self):
        url = hero.generation_url(
            "a person entering a room", 77,
            "https://images.example/frame.jpg?size=large",
        )
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["model"], ["kontext"])
        self.assertEqual(
            query["image"], ["https://images.example/frame.jpg?size=large"],
        )
        self.assertEqual(query["enhance"], ["true"])
        self.assertEqual(query["safe"], ["true"])


if __name__ == "__main__":
    unittest.main()
