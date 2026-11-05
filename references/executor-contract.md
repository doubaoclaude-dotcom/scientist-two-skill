# Executor protocol

The controller calls `executor.request(config, payload) -> dict`, using
`scripts/executor.py`. The same endpoint runs locally, over native SSH, or behind
a custom adapter. The bundled executor requires Python 3.10+ and a POSIX execution
host (Linux/macOS); it uses process groups.
No scheduler, model SDK, password, API key, or GPU is required.

## Configuration

```json
{"mode": "local"}
```

```json
{
  "mode": "ssh",
  "host": "compute-alias",
  "python": "python3",
  "executor_path": "/srv/scientist/executor.py"
}
```

`host` is an existing SSH alias containing letters, numbers, underscores, periods
or hyphens, starting with a letter or number. SSH uses `BatchMode=yes` and
`StrictHostKeyChecking=yes`; establish identity and verify the host key yourself.
An optional absolute `config_file` selects an existing SSH config using `ssh -F`.
No settings, credentials, keys, or host-key exceptions are written by this tool.
The remote executable and endpoint are quoted with `shlex.join`; experiment
arguments travel as JSON on stdin and never become part of a shell command.

```json
{
  "mode": "custom",
  "argv": ["python3", "/absolute/skill/examples/custom_adapter.py"]
}
```

The example adapter is runnable: it passes stdin/stdout to the bundled local
endpoint, which starts a detached worker. Replace that call with an authorized
scheduler/API integration while preserving this contract. The adapter receives
one JSON request on stdin and must exit after writing exactly one JSON object on
stdout; diagnostics belong on stderr or in log files. Never mix banners with the
protocol. It must durably implement all three operations, including stable IDs,
process status, and valid result JSON, before using it for research.

SSH/custom accept optional positive `request_timeout_seconds` (default 30). This
bounds the transport call, not the experiment. A transport timeout, failed spawn,
or nonzero transport exit yields `unknown`; the core does not retry. Malformed
JSON, wrong job identity/path, invalid status, invalid score, or missing success
fields raise `ValueError`. The controller records such errors as unknown outcomes.

## Requests and identity

```json
{
  "operation": "submit",
  "job_id": "study01-h01-screen-01",
  "job_root": "/srv/scientist/jobs",
  "cwd": "/srv/scientist/source",
  "argv": ["python3", "experiment.py", "--variant", "baseline", "--split", "development"],
  "timeout_seconds": 30
}
```

No source hash manifest is required. The executor runs the prepared files in
`cwd` without comparing their bytes to the controller's copy. The old
`input_manifest` field has no validation role; deploy the intended source files
explicitly before submitting a new job.

`job_root` and `cwd` must be normalized absolute paths on the execution host.
`job_id` matches `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`. `argv` is a nonempty array of
strings, used directly with `subprocess.Popen` without `shell=True`.
`timeout_seconds` is a positive finite number. Numeric booleans are rejected.

The following requests refer to the same permanent identity:

```json
{"operation": "status", "job_id": "study01-h01-screen-01", "job_root": "/srv/scientist/jobs"}
```

```json
{"operation": "collect", "job_id": "study01-h01-screen-01", "job_root": "/srv/scientist/jobs"}
```

An atomic `mkdir(job_root/job_id)` claims the ID, then request and status snapshots
are flushed to disk before worker launch. A duplicate identical submission
returns that task's current state. A different request for an existing ID is
rejected. An incomplete or corrupt existing directory returns `unknown` and is
never repurposed. A separate worker claim prevents repeated worker entry from
starting another command. Keep the persistent root and task directories; deleting
them deletes the executor's duplicate protection.

## Experiment output and responses

The command runs in `cwd`. Its environment adds `SCIENTIST_JOB_DIR` and
`SCIENTIST_RESULT_PATH`; the latter is `job_root/job_id/result.json`. The existing
environment is inherited for authorized runtime setup but is not dumped into any
manifest. Write the result to this path:

```python
import json
import os
from pathlib import Path

Path(os.environ["SCIENTIST_RESULT_PATH"]).write_text(
    json.dumps({"metrics": {"score": 0.75}}, allow_nan=False)
)
```

This score demonstrates the interface, not research performance. The complete
result must be an object with `metrics.score` as a finite number; all other JSON
numbers must also be finite. JSON requests, result files and responses are limited
to 1 MiB; the success response's metadata also counts toward that limit. Duplicate
JSON keys, invalid UTF-8/JSON, nonfinite numbers and symlink result files are
rejected. The worker requires both exit code zero and a valid result for success.

```json
{
  "job_id": "study01-h01-screen-01",
  "status": "succeeded",
  "job_dir": "/srv/scientist/jobs/study01-h01-screen-01",
  "exit_code": 0,
  "elapsed_seconds": 0.12,
  "result": {"metrics": {"score": 0.75}}
}
```

| Status | Required fields beyond `job_id`, `job_dir`, `status` | Meaning |
| --- | --- | --- |
| `preparing` | `exit_code: null`, finite nonnegative `elapsed_seconds` | Identity is reserved; preparation or launch is pending. |
| `running` | `exit_code: null`, finite nonnegative `elapsed_seconds` | Worker is monitoring the experiment. |
| `succeeded` | `exit_code: 0`, finite nonnegative `elapsed_seconds`, `result` | Process and result checks passed. |
| `failed` | `exit_code` (integer or null before launch), finite nonnegative `elapsed_seconds`, diagnostic `error` from bundled worker | Nonzero exit, timeout, missing/corrupt result, or launch failure. |
| `unknown` | Bundled endpoint supplies diagnostic `error` | Outcome cannot currently be verified; preserve identity and reconcile. |

`status` and `collect` both return the current response; successful responses
include the result. The bundled endpoint re-reads and validates result JSON on
each call without comparing a saved hash. Missing or invalid JSON returns
`unknown`; valid rewritten JSON is accepted. No `result_sha256` is required.
The controller can still invalidate evidence when collected result values change;
formatting-only edits do not count as a changed result.
`collect` does not download arbitrary directories or logs from SSH hosts. Inspect
the returned execution-host `job_dir` or explicitly copy an allowlist of artifacts.

Each job preserves `request.json`, `status.json`, `result.json` if produced,
`stdout.log`, `stderr.log`, and `worker.log`. Failure never deletes source, logs or
result bytes. The worker's elapsed time includes preparation, execution and
cleanup, so it can slightly exceed the process deadline. This is wall-clock
duration, not CPU/GPU utilization.

## Durability, timeout and recovery limits

Workers detach into their own session and use file-backed logs; controller exit
or an SSH connection ending does not end the worker. The experiment has a separate
owned process group. Timeout sends TERM then KILL only to that group; cleanup
also terminates leftover children when the experiment leader exits. Experiments
must not escape their group by daemonizing or creating independent sessions.
This is process management, not containment against hostile code.

The worker refreshes status while waiting. After ten seconds without a heartbeat,
a nonterminal job is reported `unknown`. This can also happen during unusually
slow filesystem operations or filesystem stalls. A crashed worker, host reboot or
missing directory never proves that no compute started. Query/collect the same
ID, inspect the persistent directory and resolve the cause; never infer failure
from a lost response and automatically resubmit. There is no reboot supervisor,
automatic restart, cancellation API or background controller wakeup. Job files
are durable on a persistent filesystem; a host reboot does not restart processes.

## Explicit source deployment

No automatic directory mirroring, deletion sync or upload occurs. Prepare an
execution-host directory and transfer only an explicit allowlist, for example:

```sh
# Example authorized host/destination; create these directories on that host first.
scp scripts/executor.py compute-alias:/srv/scientist/executor.py
scp examples/experiment.py compute-alias:/srv/scientist/source/experiment.py
```

Exclude `.git`, datasets, weights, logs, generated results, credentials, local SSH
configuration and private files. Provision datasets separately under an explicit
data policy and record their identity in the frozen study protocol. No source
or result checksums need to be generated or transferred. Source identity is not
automatically checked on the execution host; record the deployed version when
needed by the study. Runtime libraries/interpreters also need separately recorded
environment identity when required by the research protocol.

The endpoint can be exercised without a controller:

```sh
python3 scripts/executor.py < /absolute/request.json
python3 examples/custom_adapter.py < /absolute/request.json
```

Invalid requests exit with code 2 and diagnostics only on stderr. Successful
protocol calls exit zero even when the experiment status is failed or unknown.

`tests/test_executor.py` runs real local/custom success, failure, timeout,
duplicate, identity, malformed-response and result-format checks; its SSH
command/disconnect tests are explicitly simulated. The separate opt-in
`tests/test_ssh_real.py` tests a real isolated localhost SSH server when available;
it does not validate a cloud scheduler, GPU environment or external host.
