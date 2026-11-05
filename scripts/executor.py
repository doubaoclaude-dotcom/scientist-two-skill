#!/usr/bin/env python3
"""Durable, dependency-free execution protocol. Python 3.10+, POSIX hosts."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time


MAX_JSON_BYTES = 1024 * 1024
STATUSES = {"preparing", "running", "succeeded", "failed", "unknown"}
TERMINAL = {"succeeded", "failed"}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite")
    if isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)


def _decode(raw):
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("JSON exceeds 1 MiB")
    try:
        value = json.loads(raw, object_pairs_hook=_object)
        _finite(value)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid protocol JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON must be an object")
    return value


def _encode(value):
    try:
        raw = json.dumps(value, allow_nan=False, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("value must be finite JSON") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("JSON exceeds 1 MiB")
    return raw


def _read(path):
    if path.is_symlink():
        raise ValueError("JSON artifact must not be a symbolic link")
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    return _decode(raw)


def _write(path, value):
    raw = _encode(value)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _text(value, name):
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(name + " must be a nonempty string without NUL")
    return value


def _absolute(value, name):
    value = _text(value, name)
    if not os.path.isabs(value) or os.path.normpath(value) != value:
        raise ValueError(name + " must be an absolute normalized path")
    return value


def _number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name + " must be a finite number")
    try:
        valid = math.isfinite(value) and (value > 0 if positive else value >= 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(name + " must be " + ("positive" if positive else "nonnegative"))
    return value


def _argv(value):
    if not isinstance(value, list) or not value:
        raise ValueError("argv must be a nonempty array")
    for item in value:
        if not isinstance(item, str) or "\0" in item:
            raise ValueError("argv entries must be strings without NUL")
    _text(value[0], "argv executable")
    return value


def _validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("request must be an object")
    _encode(payload)
    if not isinstance(payload.get("operation"), str) or payload["operation"] not in {"submit", "status", "collect"}:
        raise ValueError("operation must be submit, status, or collect")
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", job_id):
        raise ValueError("invalid job_id")
    _absolute(payload.get("job_root"), "job_root")
    if payload["operation"] == "submit":
        _absolute(payload.get("cwd"), "cwd")
        _argv(payload.get("argv"))
        _number(payload.get("timeout_seconds"), "timeout_seconds", positive=True)


def _job_dir(payload):
    return Path(payload["job_root"]) / payload["job_id"]


def _unknown(payload, error):
    return {"job_id": payload["job_id"], "job_dir": str(_job_dir(payload)),
            "status": "unknown", "error": error}


def _validate_result(result):
    if not isinstance(result, dict) or not isinstance(result.get("metrics"), dict):
        raise ValueError("result requires a metrics object")
    score = result["metrics"].get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("result metrics.score must be finite numeric data")
    try:
        finite = math.isfinite(score)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("result metrics.score must be finite numeric data")
    _finite(result)


def _validate_response(response, payload):
    if not isinstance(response, dict) or response.get("job_id") != payload["job_id"]:
        raise ValueError("executor returned wrong job_id")
    if not isinstance(response.get("status"), str) or response["status"] not in STATUSES:
        raise ValueError("executor returned invalid status")
    if response.get("job_dir") != str(_job_dir(payload)):
        raise ValueError("executor returned wrong job_dir")
    status = response["status"]
    if status != "unknown":
        _number(response.get("elapsed_seconds"), "elapsed_seconds")
        code = response.get("exit_code")
        if code is not None and (isinstance(code, bool) or not isinstance(code, int)):
            raise ValueError("invalid exit_code")
        if "exit_code" not in response:
            raise ValueError("missing exit_code")
    if status in {"preparing", "running"} and response["exit_code"] is not None:
        raise ValueError("unfinished job has an exit_code")
    if status == "succeeded":
        if response["exit_code"] != 0:
            raise ValueError("succeeded job requires exit_code zero")
        _validate_result(response.get("result"))
    _encode(response)
    return response


def _inspect(payload):
    directory = _job_dir(payload)
    if not directory.is_dir() or directory.is_symlink():
        return _unknown(payload, "job directory missing or unsafe; do not resubmit")
    try:
        status = _read(directory / "status.json")
        if not isinstance(status.get("status"), str):
            raise ValueError("invalid persisted status")
        if status.get("status") not in TERMINAL:
            heartbeat = _number(status.get("updated_at"), "updated_at")
            if time.time() - heartbeat > 10:
                return _unknown(payload, "worker heartbeat stale; reconcile this job, do not resubmit")
        status.pop("updated_at", None)
        if status.get("status") == "succeeded":
            result = _read(directory / "result.json")
            _validate_result(result)
            status["result"] = result
        return _validate_response(status, payload)
    except (OSError, ValueError) as exc:
        return _unknown(payload, "cannot verify persisted job: " + str(exc))


def _local(payload):
    _validate_payload(payload)
    if payload["operation"] != "submit":
        return _inspect(payload)
    directory = _job_dir(payload)
    directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        if directory.is_symlink() or not directory.is_dir():
            return _unknown(payload, "existing job directory is unsafe; do not resubmit")
        try:
            original = _read(directory / "request.json")
        except (OSError, ValueError):
            return _unknown(payload, "existing job has no verifiable request; do not resubmit")
        if original != payload:
            raise ValueError("job_id already exists with a different submission")
        return _inspect(payload)
    _write(directory / "request.json", payload)
    initial = {"job_id": payload["job_id"], "job_dir": str(directory),
               "status": "preparing", "exit_code": None, "elapsed_seconds": 0,
               "updated_at": time.time()}
    _write(directory / "status.json", initial)
    try:
        with (directory / "worker.log").open("ab", buffering=0) as log:
            worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(directory)],
                                      stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                      close_fds=True, start_new_session=True)
            threading.Thread(target=worker.wait, daemon=True).start()
    except OSError as exc:
        initial.update(status="failed", error="could not start worker: " + str(exc))
        _write(directory / "status.json", initial)
    return _inspect(payload)


def _terminate(process):
    # Kill only the experiment/transport session we created, including its children.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        if sig == signal.SIGTERM:
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
    process.wait()


def _worker(directory):
    payload = _read(directory / "request.json")
    _validate_payload(payload)
    if directory != _job_dir(payload):
        raise ValueError("worker directory does not match request")
    try:
        (directory / "worker.claim").mkdir()
    except FileExistsError:
        return
    started = time.monotonic()
    state = {"job_id": payload["job_id"], "job_dir": str(directory),
             "status": "preparing", "exit_code": None, "elapsed_seconds": 0}
    process = None

    def save():
        state.update(elapsed_seconds=time.monotonic() - started, updated_at=time.time())
        _write(directory / "status.json", state)

    try:
        if not Path(payload["cwd"]).resolve(strict=True).is_dir():
            raise ValueError("cwd must be a prepared directory")
        environment = os.environ.copy()
        environment.update(SCIENTIST_JOB_DIR=str(directory),
                           SCIENTIST_RESULT_PATH=str(directory / "result.json"))
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(payload["argv"], cwd=payload["cwd"], env=environment,
                                       stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       close_fds=True, start_new_session=True)
            state["status"] = "running"
            deadline = time.monotonic() + payload["timeout_seconds"]
            while True:
                save()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _terminate(process)
                    state["exit_code"] = process.returncode
                    raise ValueError("experiment exceeded timeout_seconds")
                try:
                    state["exit_code"] = process.wait(timeout=min(remaining, 1))
                    _terminate(process)
                    break
                except subprocess.TimeoutExpired:
                    pass
        if state["exit_code"] != 0:
            raise ValueError("experiment exited with nonzero status")
        result = _read(directory / "result.json")
        _validate_result(result)
        state["status"] = "succeeded"
    except (OSError, ValueError) as exc:
        if process is not None and process.poll() is None:
            _terminate(process)
            state["exit_code"] = process.returncode
        state.update(status="failed", error=str(exc))
    save()


def _transport(argv, payload, timeout):
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
            try:
                process.communicate(_encode(payload), timeout=timeout)
            except subprocess.TimeoutExpired:
                _terminate(process)
                return _unknown(payload, "transport timeout; reconcile this job, do not resubmit")
        except OSError as exc:
            return _unknown(payload, "transport unavailable: " + str(exc))
        if process.returncode:
            return _unknown(payload, "transport exited " + str(process.returncode) + "; reconcile this job")
        stdout.seek(0)
        return _validate_response(_decode(stdout.read(MAX_JSON_BYTES + 1)), payload)


def request(config, payload):
    """Submit/query/collect one job; never retry a submission after transport loss."""
    _validate_payload(payload)
    if not isinstance(config, dict):
        raise ValueError("executor config must be an object")
    mode = config.get("mode")
    if mode == "local":
        return _validate_response(_local(payload), payload)
    timeout = _number(config.get("request_timeout_seconds", 30), "request_timeout_seconds", positive=True)
    if mode == "custom":
        argv = _argv(config.get("argv"))
    elif mode == "ssh":
        host = config.get("host")
        if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", host):
            raise ValueError("ssh host must be an existing SSH alias")
        executable = _text(config.get("python", "python3"), "ssh python")
        if executable.startswith("-"):
            raise ValueError("ssh python must name an executable")
        endpoint = _absolute(config.get("executor_path"), "executor_path")
        argv = ["ssh"]
        if "config_file" in config:
            argv.extend(["-F", _absolute(config["config_file"], "ssh config_file")])
        argv.extend(["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "--", host,
                     shlex.join([executable, endpoint])])
    else:
        raise ValueError("executor mode must be local, ssh, or custom")
    return _transport(argv, payload, timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.worker is not None:
            _worker(args.worker)
        else:
            payload = _decode(sys.stdin.buffer.read(MAX_JSON_BYTES + 1))
            sys.stdout.buffer.write(_encode(_local(payload)) + b"\n")
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
