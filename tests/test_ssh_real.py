"""Opt-in real OpenSSH test: SCIENTIST_TEST_SSH=1 python3 -m unittest discover -s tests -p test_ssh_real.py -v.

Starts a temporary loopback-only sshd with disposable keys. Requires ssh, ssh-keygen,
and sshd (SCIENTIST_SSHD may select its absolute path). No user SSH files are changed.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import executor


@unittest.skipUnless(os.environ.get("SCIENTIST_TEST_SSH") == "1", "opt-in real localhost SSH test")
class RealSSHTest(unittest.TestCase):
    def test_detached_job_collection_without_hashes_and_changed_remote_source(self):
        sshd = os.environ.get("SCIENTIST_SSHD", shutil.which("sshd") or "/usr/sbin/sshd")
        with tempfile.TemporaryDirectory(prefix="scientist-ssh-") as temporary:
            root = Path(temporary).resolve()
            for name in ("host", "client"):
                subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / name)], check=True)
            (root / "authorized_keys").write_text((root / "client.pub").read_text())
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            host_key = (root / "host.pub").read_text().split()
            (root / "known_hosts").write_text(f"[127.0.0.1]:{port} {host_key[0]} {host_key[1]}\n")
            server_config = root / "sshd_config"
            server_config.write_text(
                f"Port {port}\nListenAddress 127.0.0.1\nHostKey {root}/host\n"
                f"PidFile {root}/pid\nAuthorizedKeysFile {root}/authorized_keys\n"
                "StrictModes no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\n"
            )
            client_config = root / "ssh_config"
            client_config.write_text(
                f"Host scientist-loopback\n  HostName 127.0.0.1\n  Port {port}\n"
                f"  IdentityFile {root}/client\n  IdentitiesOnly yes\n"
                f"  UserKnownHostsFile {root}/known_hosts\n  StrictHostKeyChecking yes\n"
            )
            source = root / "source with spaces and 'quotes'"
            source.mkdir()
            program = source / "experiment.py"
            program.write_text(
                "import json, os, time\n"
                "time.sleep(0.4)\n"
                "with open(os.environ['SCIENTIST_RESULT_PATH'], 'w') as f:\n"
                "    json.dump({'metrics': {'score': 0.75}}, f)\n"
            )
            config = {"mode": "ssh", "host": "scientist-loopback", "python": sys.executable,
                      "executor_path": str(Path(executor.__file__).resolve()), "config_file": str(client_config)}
            payload = {"operation": "submit", "job_id": "real-ssh", "job_root": str(root / "jobs"),
                       "cwd": str(source), "argv": [sys.executable, str(program)], "timeout_seconds": 5}
            with (root / "sshd.log").open("w") as log:
                server = subprocess.Popen([sshd, "-D", "-e", "-f", str(server_config)], stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if server.poll() is not None:
                            self.fail("sshd exited: " + (root / "sshd.log").read_text())
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=.1):
                                break
                        except OSError:
                            time.sleep(.05)
                    first = executor.request(config, payload)
                    self.assertIn(first["status"], {"preparing", "running", "succeeded"}, first)
                    query = {key: payload[key] for key in ("job_id", "job_root")}
                    query["operation"] = "collect"
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        result = executor.request(config, query)
                        if result["status"] in {"succeeded", "failed"}:
                            break
                        time.sleep(.1)
                    self.assertEqual(result["status"], "succeeded", result)
                    self.assertEqual(result["result"]["metrics"]["score"], .75)
                    self.assertNotIn("result_sha256", result)
                    self.assertEqual(executor.request(config, payload)["result"], result["result"])
                    program.write_text(program.read_text().replace("0.75", "0.5"))
                    altered = dict(payload, job_id="source-drift")
                    executor.request(config, altered)
                    query["job_id"] = "source-drift"
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        changed = executor.request(config, query)
                        if changed["status"] in {"succeeded", "failed"}:
                            break
                        time.sleep(.1)
                    self.assertEqual(changed["status"], "succeeded", changed)
                    self.assertEqual(changed["result"]["metrics"]["score"], 0.5)
                finally:
                    server.terminate()
                    server.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
