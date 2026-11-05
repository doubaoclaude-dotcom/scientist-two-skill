"""End-to-end synthetic fixture checks, including independent raw-data validation."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DemoTest(unittest.TestCase):
    def test_default_cleans_temporary_output(self):
        completed = subprocess.run([sys.executable, str(ROOT / "examples/demo.py")],
                                   text=True, capture_output=True, timeout=45)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertFalse(summary["retained"])
        self.assertFalse(Path(summary["artifacts"]).exists())

    def test_local_and_custom_complete(self):
        for mode in ["local", "custom"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                completed = subprocess.run(
                    [sys.executable, str(ROOT / "examples/demo.py"), "--directory", directory, "--mode", mode],
                    text=True, capture_output=True, timeout=45)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                summary = json.loads(completed.stdout)
                self.assertEqual(summary["baseline_score"], 0.5)
                self.assertEqual(summary["final_score"], 1.0)
                self.assertEqual(summary["jobs"], 8)
                self.assertTrue(summary["retained"])
                state = json.loads(Path(summary["state"]).read_text())
                self.assertEqual(state["outcome"], "completed")
                self.assertEqual(state["stage"], "complete")
                self.assertTrue(all(state["gates"][stage]["status"] == "passed" for stage in summary["gates"]))
                self.assertTrue((Path(directory) / "jobs/final/observations.json").is_file())
                duplicate = subprocess.run(
                    [sys.executable, str(ROOT / "examples/demo.py"), "--directory", directory],
                    text=True, capture_output=True, timeout=5)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn("already has state.json", duplicate.stderr)
                # Recompute a final job and reject raw-data tampering independently of result.json.
                spec = importlib.util.spec_from_file_location("toy_validator", ROOT / "examples/validator.py")
                validator = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(validator)
                payload = {"stage": "S5", "protocol": validator.PROTOCOL,
                           "source_root": str(ROOT), "jobs": {"final": state["jobs"]["final"]}}
                self.assertEqual(validator.validate(payload)["metrics"]["final"]["score"], 1.0)
                observations = Path(directory) / "jobs/final/observations.json"
                raw = json.loads(observations.read_text())
                raw["rows"][0]["prediction"] += 1
                observations.write_text(json.dumps(raw))
                with self.assertRaisesRegex(ValueError, "raw observations"):
                    validator.validate(payload)


if __name__ == "__main__":
    unittest.main()
