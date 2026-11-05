#!/usr/bin/env python3
"""Runnable JSON adapter: delegate each request to the bundled local endpoint.

Replace the subprocess with an authorized scheduler/API integration while keeping
the same durable job identity, process status and JSON response contract.
"""

from pathlib import Path
import subprocess
import sys


if __name__ == "__main__":
    endpoint = Path(__file__).resolve().parents[1] / "scripts" / "executor.py"
    raise SystemExit(subprocess.call([sys.executable, str(endpoint)],
                                    stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr))
