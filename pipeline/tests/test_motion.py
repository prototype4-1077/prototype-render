import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import motion


class MotionBudgetTests(unittest.TestCase):
    def test_pan_and_zoom_remain_static(self):
        for mode in ("pan", "zoom", "ken_burns", "static"):
            self.assertEqual(motion.motion_kind({"motion_mode": mode}), motion.STATIC)

    def test_depth_keyframes_and_hero_are_animated(self):
        self.assertEqual(
            motion.motion_kind({"motion_mode": "depth"}), motion.ANIMATED,
        )
        self.assertEqual(
            motion.motion_kind({"motion_mode": "keyframes"}), motion.ANIMATED,
        )
        self.assertEqual(motion.motion_kind({"hero": True}), motion.ANIMATED)

    def test_literal_search_defaults_to_true_video(self):
        self.assertEqual(
            motion.motion_kind({"query": "hands writing in notebook"}), motion.VIDEO,
        )

    def test_budget_is_calculated_by_duration_not_scene_count(self):
        script = {
            "max_still_source_ratio": .35,
            "scenes": [
                {"duration": 3.5, "motion_kind": motion.ANIMATED},
                {"duration": 6.5, "motion_kind": motion.VIDEO},
            ],
        }
        result = motion.validate_budget(script)
        self.assertAlmostEqual(result.still_source_ratio, .35)
        self.assertAlmostEqual(result.video_ratio, .65)

    def test_animated_stills_count_in_full_toward_the_still_cap(self):
        script = {
            "max_still_source_ratio": .35,
            "scenes": [
                {"duration": 6.5, "motion_kind": motion.ANIMATED},
                {"duration": 3.5, "motion_kind": motion.VIDEO},
            ],
        }
        with self.assertRaisesRegex(
                motion.MotionBudgetError, "animated stills count toward this cap"):
            motion.validate_budget(script)

    def test_budget_rejects_even_one_long_static_scene(self):
        script = {
            "max_still_source_ratio": .35,
            "scenes": [
                {"duration": 5, "motion_kind": motion.STATIC},
                {"duration": 5, "motion_kind": motion.VIDEO},
                {"duration": 1, "motion_kind": motion.ANIMATED},
            ],
        }
        with self.assertRaisesRegex(motion.MotionBudgetError, "still-derived shots are"):
            motion.validate_budget(script)

    def test_defaults_upgrade_explicit_static_stills_but_keep_video_sources(self):
        script = {
            "scenes": [
                {"duration": 1, "source_image": "still.png",
                 "motion_mode": "pan", "motion_kind": motion.STATIC},
                {"duration": 1, "query": "walking", "motion_kind": motion.VIDEO},
                {"duration": 1, "hero": True},
            ],
        }
        self.assertTrue(motion.apply_motion_defaults(script))
        self.assertEqual(script["max_still_source_ratio"], .50)
        self.assertEqual(script["scenes"][0]["motion_kind"], motion.ANIMATED)
        self.assertEqual(script["scenes"][0]["motion_mode"], "cinemagraph")
        self.assertEqual(script["scenes"][1]["motion_kind"], motion.VIDEO)
        self.assertEqual(script["scenes"][2]["motion_kind"], motion.ANIMATED)

    def test_true_motion_requires_temporal_verification(self):
        script = {
            "scenes": [
                {"duration": 2, "motion_kind": motion.VIDEO},
                {"duration": 1, "motion_kind": motion.ANIMATED},
            ],
        }
        with self.assertRaisesRegex(
                motion.MotionBudgetError, "lack temporal verification"):
            motion.validate_video_evidence(script)
        script["scenes"][0]["motion_verified"] = True
        self.assertTrue(motion.validate_video_evidence(script))

    def test_recipe_inference_follows_the_literal_action(self):
        self.assertEqual(motion.infer_recipe({"text": "The seed opens under soil."}),
                         "organic")
        self.assertEqual(motion.infer_recipe({"text": "She watches herself in a mirror."}),
                         "reflection")
        self.assertEqual(motion.infer_recipe({"text": "A phone records the room."}),
                         "screen")


class MotionRenderTests(unittest.TestCase):
    @unittest.skipUnless(__import__("importlib").util.find_spec("cv2"),
                         "OpenCV is installed by pipeline requirements")
    def test_depth_animation_is_a_real_band_sized_video(self):
        with tempfile.TemporaryDirectory() as td:
            source = os.path.join(td, "source.png")
            output = os.path.join(td, "motion.mp4")
            image = Image.new("RGB", (480, 270), (58, 66, 72))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 150, 480, 270), fill=(78, 61, 45))
            draw.ellipse((175, 45, 305, 240), fill=(188, 155, 112))
            image.save(source)
            yy, xx = np.mgrid[0:270, 0:480]
            depth = np.exp(-(((xx - 240) / 120) ** 2 + ((yy - 145) / 125) ** 2))
            motion.render_depth_animation(
                source, depth.astype(np.float32), .3, output,
                recipe="human", strength=.7, seed=4,
            )
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,nb_frames",
                "-of", "csv=p=0", output,
            ], check=True, capture_output=True, text=True)
            width, height, frames = probe.stdout.strip().split(",")
            self.assertEqual((int(width), int(height)),
                             (motion.W, motion.H))
            self.assertGreaterEqual(int(frames), 8)


if __name__ == "__main__":
    unittest.main()


class MultiplaneCameraTests(unittest.TestCase):
    def test_dolly_zoom_background_blooms_while_subject_holds(self):
        import motion
        end = motion.camera_path("dolly_zoom", 1.0)
        start = motion.camera_path("dolly_zoom", 0.0)
        bg_growth = end["bg"][2] - start["bg"][2]
        mid_growth = abs(end["mid"][2] - start["mid"][2])
        self.assertGreater(bg_growth, 0.10)
        self.assertLess(mid_growth, 0.01)
        self.assertLess(end["near"][2], start["near"][2])

    def test_push_in_scales_ordered_by_depth(self):
        import motion
        p = motion.camera_path("push_in", 1.0)
        self.assertGreater(p["near"][2], p["mid"][2])
        self.assertGreater(p["mid"][2], p["bg"][2])

    def test_orbit_planes_move_in_opposite_directions(self):
        import motion
        p = motion.camera_path("orbit", 0.9)
        self.assertLess(p["bg"][0] * p["near"][0], 0.0)

    def test_rack_focus_crossfades_blur_between_planes(self):
        import motion
        early = motion.camera_path("rack_focus", 0.05)
        late = motion.camera_path("rack_focus", 0.95)
        self.assertGreater(early["near"][4], 1.0)
        self.assertLess(early["bg"][4], 0.5)
        self.assertGreater(late["bg"][4], 1.0)
        self.assertLess(late["near"][4], 0.5)

    def test_camera_paths_are_deterministic(self):
        import motion
        for move in motion.CAMERA_MOVES:
            self.assertEqual(motion.camera_path(move, 0.4),
                             motion.camera_path(move, 0.4))

    def test_still_fingerprint_tracks_motion_version_for_heroes_only(self):
        import motion
        hero = {"hero": True, "hero_style": "effects", "image_prompt": "x"}
        stock = {"query": "ocean waves", "pexels_id": 5}
        self.assertNotEqual(motion.scene_visual_fingerprint(hero),
                            motion.scene_visual_fingerprint({**hero, "image_prompt": "y"}))
        stock_before = motion.scene_visual_fingerprint(stock)
        hero_before = motion.scene_visual_fingerprint(hero)
        old_version = motion.MOTION_3D_VERSION
        try:
            motion.MOTION_3D_VERSION = "different"
            self.assertEqual(stock_before, motion.scene_visual_fingerprint(stock))
            self.assertNotEqual(hero_before, motion.scene_visual_fingerprint(hero))
        finally:
            motion.MOTION_3D_VERSION = old_version
