"""Concurrent renders must not erase each other's learning."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from merge_memory import merge, merge_list, merge_dict  # noqa: E402


class MergeMemoryTests(unittest.TestCase):
    def test_both_renders_clip_history_survives(self):
        base = {"used_ids": [1, 2]}
        ours = {"used_ids": [1, 2, 3]}
        theirs = {"used_ids": [1, 2, 4]}
        self.assertEqual(sorted(merge(base, ours, theirs)["used_ids"]), [1, 2, 3, 4])

    def test_bans_from_either_side_are_kept(self):
        merged = merge({"banned_ids": []}, {"banned_ids": [9]}, {"banned_ids": [7]})
        self.assertEqual(sorted(merged["banned_ids"]), [7, 9])

    def test_each_side_keeps_the_weight_it_changed(self):
        base = {"query_weights": {"a": 0.5, "b": 0.5}}
        ours = {"query_weights": {"a": 0.9, "b": 0.5}}
        theirs = {"query_weights": {"a": 0.5, "b": 0.2}}
        self.assertEqual(merge(base, ours, theirs)["query_weights"], {"a": 0.9, "b": 0.2})

    def test_notes_from_both_sides_append(self):
        merged = merge({"notes": ["n0"]}, {"notes": ["n0", "mine"]}, {"notes": ["n0", "theirs"]})
        self.assertIn("mine", merged["notes"])
        self.assertIn("theirs", merged["notes"])

    def test_dedupes_records_by_id(self):
        base = {"videos": []}
        ours = {"videos": [{"id": "v1", "score": 1}]}
        theirs = {"videos": [{"id": "v1", "score": 1}, {"id": "v2"}]}
        ids = [v["id"] for v in merge(base, ours, theirs)["videos"]]
        self.assertEqual(sorted(ids), ["v1", "v2"])

    def test_deletion_agreed_by_both_sides_sticks(self):
        merged = merge({"rules": ["old"]}, {"rules": []}, {"rules": []})
        self.assertEqual(merged["rules"], [])

    def test_missing_or_corrupt_inputs_do_not_crash(self):
        self.assertEqual(merge({}, {}, {}), {})
        self.assertEqual(merge_list(None, None, None), [])
        self.assertEqual(merge_dict(None, None, None), {})


if __name__ == "__main__":
    unittest.main()
