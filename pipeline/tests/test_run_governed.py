from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from governor import PipelineGovernor  # noqa: E402
from run_governed import _marker, _quarantine_quality_outputs  # noqa: E402


class GovernedRunnerTests(unittest.TestCase):
    def test_marker_prefers_protocol_lines(self):
        self.assertEqual(_marker("noise\nRUN AGAIN (footage 2/20)\n"), "RUN AGAIN (footage 2/20)")
        self.assertEqual(_marker("noise\nDONE -> final.mp4\n"), "DONE -> final.mp4")

    def test_quality_quarantine_is_targeted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_dir = root / "build" / "demo"
            build_dir.mkdir(parents=True)
            final = build_dir / "final.mp4"
            youtube = build_dir / "final_youtube.mp4"
            final.write_bytes(b"bad")
            youtube.write_bytes(b"good")
            governor = PipelineGovernor(build_dir, repo_root=root, heartbeat_seconds=0.05)
            report = {
                "failures": [{"code": "decode_failed", "target": "portrait", "message": "bad"}],
                "outputs": {
                    "portrait": {"path": str(final)},
                    "youtube": {"path": str(youtube)},
                },
            }
            actions = _quarantine_quality_outputs(build_dir, report, governor)
            self.assertEqual(len(actions), 1)
            self.assertFalse(final.exists())
            self.assertTrue(youtube.exists())
            self.assertEqual(len(list(build_dir.glob("final.mp4.quality-rejected.*"))), 1)


if __name__ == "__main__":
    unittest.main()
