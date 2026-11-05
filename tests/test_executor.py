"""Real local/custom executions; SSH unit tests explicitly simulate transport."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import executor


SUCCESS = """import json, os
from pathlib import Path
Path(os.environ['SCIENTIST_RESULT_PATH']).write_text(json.dumps({'metrics': {'score': 0.75}}))
print('experiment output')
"""


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "source"
        self.source.mkdir()
        self.root = self.base / "jobs"
        self.config = {"mode": "local"}

    def tearDown(self):
        self.temporary.cleanup()

    def payload(self, script=SUCCESS, job_id="test-job", timeout=5):
        target = self.source / (job_id + ".py")
        target.write_text(script)
        return {"operation": "submit", "job_id": job_id, "job_root": str(self.root),
                "cwd": str(self.source), "argv": [sys.executable, str(target)],
                "timeout_seconds": timeout}

    def query(self, payload, operation="status"):
        return {key: payload[key] for key in ("job_id", "job_root")} | {"operation": operation}

    def complete(self, payload):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = executor.request(self.config, self.query(payload, "collect"))
            if response["status"] in executor.TERMINAL:
                return response
            time.sleep(0.03)
        self.fail("job did not finish: " + repr(response))

    def test_real_local_success_is_async_and_collects_current_json_without_hashes(self):
        payload = self.payload("import time\ntime.sleep(0.4)\n" + SUCCESS)
        started = time.monotonic()
        initial = executor.request(self.config, payload)
        self.assertLess(time.monotonic() - started, 0.35)
        self.assertIn(initial["status"], {"preparing", "running"})
        response = self.complete(payload)
        self.assertEqual(response["status"], "succeeded")
        self.assertEqual(response["exit_code"], 0)
        self.assertEqual(response["result"]["metrics"]["score"], 0.75)
        directory = self.root / payload["job_id"]
        self.assertNotIn("result_sha256", response)
        self.assertNotIn("result_sha256", executor._read(directory / "status.json"))
        self.assertIn("experiment output", (directory / "stdout.log").read_text())
        (directory / "result.json").write_text(json.dumps(response["result"], indent=4) + "\n")
        self.assertEqual(executor.request(self.config, self.query(payload))["result"], response["result"])
        # Old persisted hashes are metadata; collection validates the current JSON.
        status = executor._read(directory / "status.json")
        executor._write(directory / "status.json", status | {"result_sha256": "0" * 64})
        (directory / "result.json").write_text('{"metrics":{"score":0.5}}')
        changed = executor.request(self.config, self.query(payload, "collect"))
        self.assertEqual(changed["status"], "succeeded")
        self.assertEqual(changed["result"]["metrics"]["score"], 0.5)
        for invalid in ('{broken', '{"metrics":{"score":NaN}}'):
            (directory / "result.json").write_text(invalid)
            self.assertEqual(executor.request(self.config, self.query(payload))["status"], "unknown")

    def test_real_nonzero_missing_corrupt_nonfinite_and_oversize_preserved(self):
        scripts = {
            "nonzero": "import sys\nprint('failure evidence', file=sys.stderr)\nsys.exit(7)",
            "missing": "pass",
            "corrupt": "import os\nopen(os.environ['SCIENTIST_RESULT_PATH'], 'w').write('{broken')",
            "nonfinite": "import os\nopen(os.environ['SCIENTIST_RESULT_PATH'], 'w').write('{\"metrics\":{\"score\":NaN}}')",
            "oversize": "import os\nopen(os.environ['SCIENTIST_RESULT_PATH'], 'w').write('x' * (1024 * 1024 + 1))",
        }
        for name, script in scripts.items():
            with self.subTest(name=name):
                payload = self.payload(script, job_id=name)
                executor.request(self.config, payload)
                response = self.complete(payload)
                self.assertEqual(response["status"], "failed")
                self.assertEqual(response["exit_code"], 7 if name == "nonzero" else 0)
                directory = self.root / name
                self.assertTrue((directory / "request.json").exists())
                if name in {"corrupt", "nonfinite", "oversize"}:
                    self.assertTrue((directory / "result.json").exists())
        self.assertIn("failure evidence", (self.root / "nonzero" / "stderr.log").read_text())

    def test_real_timeout_kills_owned_descendants(self):
        marker = self.source / "surviving-child"
        child = "import time; from pathlib import Path; time.sleep(0.8); Path(" + repr(str(marker)) + ").touch()"
        payload = self.payload("import subprocess,sys,time\nsubprocess.Popen([sys.executable, '-c', "
                               + repr(child) + "])\ntime.sleep(5)", timeout=0.2)
        executor.request(self.config, payload)
        response = self.complete(payload)
        self.assertEqual(response["status"], "failed")
        self.assertIn("timeout_seconds", response["error"])
        self.assertNotEqual(response["exit_code"], 0)
        time.sleep(0.8)
        self.assertFalse(marker.exists())

    def test_real_concurrent_duplicate_and_worker_reentry_never_start_twice(self):
        script = "from pathlib import Path\nimport time\nwith Path('count').open('a') as f: f.write('started\\n')\ntime.sleep(0.2)\n" + SUCCESS
        payload = self.payload(script)
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: executor.request(self.config, payload), range(2)))
        self.assertTrue(all(reply["job_id"] == payload["job_id"] for reply in replies))
        self.assertEqual(self.complete(payload)["status"], "succeeded")
        executor._worker(self.root / payload["job_id"])
        self.assertEqual(executor.request(self.config, payload)["status"], "succeeded")
        self.assertEqual((self.source / "count").read_text(), "started\n")
        with self.assertRaisesRegex(ValueError, "different submission"):
            executor.request(self.config, payload | {"timeout_seconds": 8})

    def test_unknown_existing_job_is_not_started(self):
        payload = self.payload()
        directory = self.root / payload["job_id"]
        directory.mkdir(parents=True)
        response = executor.request(self.config, payload)
        self.assertEqual(response["status"], "unknown")
        self.assertFalse((directory / "worker.claim").exists())
        executor._write(directory / "request.json", payload)
        executor._write(directory / "status.json", {"job_id": payload["job_id"], "job_dir": str(directory),
                        "status": "running", "exit_code": None, "elapsed_seconds": 1, "updated_at": 0})
        self.assertEqual(executor.request(self.config, payload)["status"], "unknown")
        self.assertFalse((directory / "worker.claim").exists())

    def test_changed_execution_source_runs_and_legacy_manifest_is_ignored(self):
        payload = self.payload()
        payload["input_manifest"] = {Path(payload["argv"][1]).name: "0" * 64}
        Path(payload["argv"][1]).write_text(SUCCESS.replace("0.75", "0.5"))
        executor.request(self.config, payload)
        response = self.complete(payload)
        self.assertEqual(response["status"], "succeeded")
        self.assertEqual(response["result"]["metrics"]["score"], 0.5)

    def test_invalid_ids_paths_and_numbers(self):
        payload = self.payload()
        invalid = [{"job_id": "../outside"}, {"job_id": "-option"}, {"job_root": "relative"},
                   {"job_root": str(self.root) + "/../escape"}, {"timeout_seconds": float("inf")},
                   {"timeout_seconds": True}, {"timeout_seconds": 0}, {"cwd": "relative"},
                   {"argv": "python3 run.py"}, {"operation": []}]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                executor.request(self.config, payload | fields)
        self.assertFalse(self.root.exists())

    def test_real_custom_adapter_survives_endpoint_exit(self):
        adapter = Path(__file__).resolve().parents[1] / "examples" / "custom_adapter.py"
        self.config = {"mode": "custom", "argv": [sys.executable, str(adapter)]}
        payload = self.payload("import time\ntime.sleep(0.2)\n" + SUCCESS)
        response = executor.request(self.config, payload)
        self.assertIn(response["status"], {"preparing", "running"})
        completed = self.complete(payload)
        self.assertEqual(completed["status"], "succeeded")
        self.assertNotIn("result_sha256", completed)

    def test_real_custom_rejects_wrong_identity_and_illegal_output(self):
        payload = self.query(self.payload())
        valid = {"job_id": payload["job_id"], "job_dir": str(self.root / payload["job_id"]), "status": "unknown"}
        outputs = ["not JSON", "[]", json.dumps(valid | {"job_id": "another"}),
                   json.dumps(valid | {"job_dir": "/wrong"}), json.dumps(valid | {"status": []}),
                   '{"job_id":"a","job_id":"b"}', json.dumps(valid | {"number": float("nan")})]
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(ValueError):
                executor.request({"mode": "custom", "argv": [sys.executable, "-c", "print(" + repr(output) + ")"]}, payload)

    def test_real_custom_timeout_is_unknown_without_retry(self):
        payload = self.query(self.payload())
        started = time.monotonic()
        response = executor.request({"mode": "custom", "argv": [sys.executable, "-c", "import time; time.sleep(5)"],
                                     "request_timeout_seconds": 0.1}, payload)
        self.assertEqual(response["status"], "unknown")
        self.assertLess(time.monotonic() - started, 2)

    def test_simulated_ssh_escaping_and_host_key_options(self):
        payload = self.query(self.payload())
        config = {"mode": "ssh", "host": "compute-alias", "python": "/opt/python with space",
                  "executor_path": "/srv/path with ' quote/executor.py", "config_file": "/tmp/ssh config"}
        with patch.object(executor, "_transport", return_value=executor._unknown(payload, "simulated")) as transport:
            executor.request(config, payload)
        argv, sent, _ = transport.call_args.args
        self.assertEqual(argv[:3], ["ssh", "-F", "/tmp/ssh config"])
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertEqual(argv[-2], "compute-alias")
        self.assertEqual(shlex.split(argv[-1]), [config["python"], config["executor_path"]])
        self.assertEqual(sent, payload)

    def test_simulated_ssh_disconnect_and_status_parser(self):
        payload = self.query(self.payload())
        config = {"mode": "ssh", "host": "compute-alias", "executor_path": "/srv/executor.py"}
        response = executor._unknown(payload, "simulated remote state")

        def process(argv, **kwargs):
            class SimulatedSSH:
                returncode = 0

                def communicate(self, raw, timeout):
                    self.request = json.loads(raw)
                    kwargs["stdout"].write(json.dumps(response).encode())
            return SimulatedSSH()

        with patch.object(executor.subprocess, "Popen", side_effect=process):
            self.assertEqual(executor.request(config, payload), response)
        with patch.object(executor.subprocess, "Popen") as spawn:
            spawn.return_value.returncode = 255
            self.assertEqual(executor.request(config, payload)["status"], "unknown")
            self.assertEqual(spawn.call_count, 1)

    def test_cli_stdout_is_protocol_only_and_invalid_request_has_no_stdout(self):
        endpoint = str(Path(executor.__file__).resolve())
        payload = self.query(self.payload())
        response = subprocess.run([sys.executable, endpoint], input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(response.returncode, 0)
        self.assertEqual(json.loads(response.stdout)["status"], "unknown")
        bad = subprocess.run([sys.executable, endpoint], input="broken", text=True, capture_output=True)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(bad.stdout, "")


if __name__ == "__main__":
    unittest.main()
