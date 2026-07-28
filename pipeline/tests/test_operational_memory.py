from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import operational_memory
import preflight


class OperationalMemoryTests(unittest.TestCase):
    def test_occurrences_are_idempotent_and_indexed(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp)
            (store / "occurrences").mkdir()
            (store / "solutions.json").write_text(json.dumps({
                "schema_version": 1,
                "solutions": [{
                    "id": "solution-a",
                    "status": "verified",
                    "fixed_at": "2026-01-01T00:00:00+00:00",
                    "verification_requirement": "one success",
                    "match": {"codes": ["known_failure"]},
                }],
            }), encoding="utf-8")
            (store / "prevention_rules.json").write_text('{"schema_version":1,"rules":[]}', encoding="utf-8")
            record = {
                "recorded_at": "2026-01-02T00:00:00+00:00",
                "phase": "preflight",
                "github_run_id": "100",
                "slug": "fixture",
                "status": "blocked",
                "code": "known_failure",
                "stage": "preflight",
                "message": "known failure happened",
            }
            first = operational_memory.write_occurrence(record, store=store)
            second = operational_memory.write_occurrence(record, store=store)
            self.assertEqual(first, second)
            self.assertEqual(len(list((store / "occurrences").glob("*.json"))), 1)
            payload = operational_memory.rebuild_index(store=store)
            self.assertEqual(payload["occurrence_count"], 1)
            self.assertEqual(payload["incident_count"], 1)
            self.assertEqual(payload["open_failure_count"], 1)

    def test_success_can_verify_a_known_solution(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp)
            (store / "occurrences").mkdir()
            (store / "solutions.json").write_text(json.dumps({
                "schema_version": 1,
                "solutions": [{
                    "id": "solution-a",
                    "status": "verified",
                    "fixed_at": "2026-01-01T00:00:00+00:00",
                    "verification_requirement": "one success",
                    "match": {"codes": ["known_failure"]},
                }],
            }), encoding="utf-8")
            (store / "prevention_rules.json").write_text('{"schema_version":1,"rules":[]}', encoding="utf-8")
            operational_memory.write_occurrence({
                "recorded_at": "2026-01-02T00:00:00+00:00",
                "phase": "render",
                "github_run_id": "101",
                "slug": "fixture",
                "status": "done",
                "code": "render_success",
                "stage": "render",
                "message": "done",
                "matched_solution_ids": ["solution-a"],
            }, store=store)
            payload = operational_memory.rebuild_index(store=store)
            proof = payload["solution_evidence"]["solution-a"]
            self.assertEqual(proof["successful_verifications"], 1)
            self.assertEqual(proof["recurrences_after_fix"], 0)


class PreflightTests(unittest.TestCase):
    def _write_script(self, directory: Path, script: dict) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "script.json"
        path.write_text(json.dumps(script), encoding="utf-8")
        return path

    def _scene(self, text: str, query: str = "door opens in hallway") -> dict:
        return {
            "text": text,
            "query": query,
            "narrative_mode": "stock_ok",
            "motion_kind": "video",
            "motion_mode": "stock",
        }

    def test_standalone_label_is_safely_removed_without_narration_change(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "standalone"
            narration = ["One line.", "Another line.", "Final question?"]
            self._write_script(build, {
                "title": "Standalone",
                "slug": "standalone",
                "title_mode": "standalone",
                "series_label": "Wrong Series",
                "visual_policy": "advisory",
                "max_still_source_ratio": 1.0,
                "scenes": [self._scene(text) for text in narration],
            })
            report = preflight.assess(build, fix_safe=True)
            self.assertTrue(report["passed"], report)
            script = json.loads((build / "script.json").read_text(encoding="utf-8"))
            self.assertIsNone(script["series_label"])
            self.assertEqual([scene["text"] for scene in script["scenes"]], narration)
            self.assertIn("sol-standalone-title-eyebrow-v1", report["applied_solution_ids"])

    def test_june_missing_voice_is_filled_from_character_bible(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "june-fixture"
            self._write_script(build, {
                "title": "June Fixture",
                "slug": "june-fixture",
                "profile": "june_oxley",
                "series_label": "JUNE OXLEY",
                "visual_policy": "advisory",
                "max_still_source_ratio": 1.0,
                "scenes": [self._scene("June talks on the porch.") for _ in range(3)],
            })
            report = preflight.assess(build, fix_safe=True)
            self.assertTrue(report["passed"], report)
            script = json.loads((build / "script.json").read_text(encoding="utf-8"))
            self.assertEqual(script["elevenlabs_voice_id"], "NOpBlnGInO9m6vDvFkFC")
            self.assertEqual(script["elevenlabs_voice_name"], "Granpa Spuds Oxley")
            self.assertIn("sol-june-canonical-voice-v1", report["applied_solution_ids"])

    def test_visual_symbol_failure_is_blocked_before_render(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "flat-symbols"
            scenes = [
                self._scene(f"Menu choice number {index}.", "menu on table with chair")
                for index in range(12)
            ]
            self._write_script(build, {
                "title": "Flat Symbols",
                "slug": "flat-symbols",
                "visual_policy": "diverse_symbols",
                "max_still_source_ratio": 1.0,
                "scenes": scenes,
            })
            report = preflight.assess(build, fix_safe=True)
            self.assertFalse(report["passed"])
            codes = {item["code"] for item in report["blockers"]}
            self.assertIn("visual_symbol_plan", codes)
            matched = {
                solution
                for item in report["blockers"]
                for solution in item.get("matched_solution_ids") or []
            }
            self.assertIn("sol-visual-symbol-diversity-v1", matched)

    def test_word_weighted_still_budget_blocks_before_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "still-heavy"
            scenes = []
            for index in range(6):
                scene = self._scene(f"This is narration scene {index} with equal weight.")
                if index < 3:
                    scene.pop("motion_kind")
                    scene.pop("motion_mode")
                    scene["hero"] = True
                    scene["narrative_mode"] = "hero"
                    scene["image_prompt"] = "cinematic image of a door"
                scenes.append(scene)
            self._write_script(build, {
                "title": "Still Heavy",
                "slug": "still-heavy",
                "visual_policy": "advisory",
                "max_still_source_ratio": 0.35,
                "scenes": scenes,
            })
            report = preflight.assess(build, fix_safe=True)
            self.assertFalse(report["passed"])
            codes = {item["code"] for item in report["blockers"]}
            self.assertIn("planned_still_budget", codes)

    def test_verbatim_source_mismatch_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "verbatim"
            self._write_script(build, {
                "title": "Verbatim",
                "slug": "verbatim",
                "source_script_verbatim": True,
                "visual_policy": "advisory",
                "max_still_source_ratio": 1.0,
                "scenes": [self._scene("This text changed.")],
            })
            (build / "source-narration.txt").write_text("This text was original.", encoding="utf-8")
            report = preflight.assess(build, fix_safe=True)
            self.assertFalse(report["passed"])
            self.assertIn("source_narration_mismatch", {item["code"] for item in report["blockers"]})


if __name__ == "__main__":
    unittest.main()
