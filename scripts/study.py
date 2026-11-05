#!/usr/bin/env python3
"""One study, one recoverable state, five evidence gates. Python 3.10+, POSIX."""

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time

try:
    from . import executor
except ImportError:
    import executor


STAGES = ("S1", "S2", "S3", "S4", "S5")
KINDS = {"baseline": 0, "smoke": 1, "screen": 1, "confirm": 1,
         "ablation": 2, "retest": 2, "rebuttal": 3, "final": 4}
REQUIRED_JOBS = {"S1": ("baseline",), "S2": ("smoke", "screen", "confirm"),
                 "S3": ("ablation", "retest"), "S4": ("rebuttal",), "S5": ("final",)}
REQUIRED_CHECKS = {"S1": ("baseline",), "S2": ("smoke", "uncertainty"),
                   "S3": ("ablation", "uncertainty"), "S4": ("rebuttal",),
                   "S5": ("numerical", "protocol", "citations", "code")}
TERMINAL = {"succeeded", "failed"}
MAX_INPUT = 1024 * 1024
MAX_STATE = 64 * 1024 * 1024


class StudyError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise StudyError(message)


def encode(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise StudyError("value must be finite JSON") from exc


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def decode(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise StudyError("invalid JSON: " + str(exc)) from exc
    encode(value)
    require(isinstance(value, dict), "JSON must be an object")
    return value


def read_json(path, limit=MAX_INPUT):
    with open(path, "rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "JSON exceeds size limit")
    return decode(raw)


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def file_hash(path):
    checksum = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()) and "\0" not in value,
            label + " must be a nonempty string")
    return value


def number(value, label, positive=False):
    require(type(value) in (int, float) and math.isfinite(value), label + " must be finite")
    require(value > 0 if positive else value >= 0, label + " is out of range")
    return value


def identifier(value, label="identifier"):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value),
            label + " must be 1-96 safe identifier characters")
    require(value not in (".", ".."), "invalid identifier")
    return value


def argv(value, label):
    require(isinstance(value, list) and value, label + " must be a nonempty argv array")
    for item in value:
        text(item, label + " argument")
    return value


def absolute(value, label):
    text(value, label)
    require(os.path.isabs(value) and os.path.normpath(value) == value,
            label + " must be an absolute normalized path")
    return value


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encode(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    """The lock spans every read/modify/write; full events precede snapshots."""

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.events = self.path.with_name(self.path.name + ".events.jsonl")
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.lock_path.open("a+b")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    def load(self):
        snapshot = read_json(self.path, MAX_STATE) if self.path.exists() else {}
        latest = None
        if self.events.exists():
            with self.events.open("r+b") as stream:
                while True:
                    offset = stream.tell()
                    line = stream.readline(MAX_STATE + 1)
                    if not line:
                        break
                    require(len(line) <= MAX_STATE, "event exceeds state size limit")
                    if not line.endswith(b"\n"):
                        # An interrupted append has no committed revision.
                        stream.truncate(offset)
                        stream.flush()
                        os.fsync(stream.fileno())
                        break
                    event = decode(line)
                    candidate = event.get("state")
                    require(isinstance(candidate, dict) and event.get("sha256") == digest(candidate),
                            "event integrity failure")
                    require(event.get("revision") == candidate.get("revision"), "event revision mismatch")
                    if latest is not None:
                        require(candidate["revision"] == latest["revision"] + 1, "event revision gap")
                    latest = candidate
        if latest is not None:
            require(snapshot.get("revision", 0) <= latest["revision"], "snapshot is ahead of event log")
            if snapshot.get("revision", 0) == latest["revision"]:
                require(digest(snapshot) == digest(latest), "snapshot does not match committed event")
            else:
                snapshot = latest
                self.write_snapshot(snapshot)
        return snapshot

    def write_snapshot(self, state):
        atomic_json(self.path, state)

    def save(self, state, action):
        state["revision"] = state.get("revision", 0) + 1
        state["updated_at"] = time.time()
        event = {"revision": state["revision"], "action": action, "state": state,
                 "sha256": digest(state)}
        raw = encode(event) + b"\n"
        require(len(raw) <= MAX_STATE, "state exceeds size limit")
        with self.events.open("ab") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(self.path.parent)
        self.write_snapshot(state)
        return copy.deepcopy(state)


def frozen_config(config):
    config = copy.deepcopy(config)
    encode(config)
    identifier(config.get("study_id"), "study_id")
    text(config.get("author"), "author")
    root = Path(absolute(config.get("source_root"), "source_root")).resolve()
    require(root.is_dir(), "source_root must exist")
    config["source_root"] = str(root)
    manifest = config.get("source_manifest", {})
    require(isinstance(manifest, dict), "source_manifest must be an object")
    for relative, expected in manifest.items():
        part = PurePosixPath(relative)
        require(not part.is_absolute() and relative == str(part) and ".." not in part.parts
                and ".git" not in part.parts and str(part) != ".", "unsafe source manifest path")
        require(isinstance(expected, str) and re.fullmatch("[0-9a-f]{64}", expected), "invalid source sha256")
        path = (root / relative).resolve()
        require(path.is_relative_to(root) and path.is_file(), "source manifest file outside source_root or missing")
        require(file_hash(path) == expected, "source hash mismatch: " + relative)
    identities = config.get("identities", {})
    for name in ("data", "evaluator"):
        text(identities.get(name), "identities." + name)
    protocol = config.get("protocol", {})
    for name in ("objective", "baseline", "statistical_rule"):
        text(protocol.get(name), "protocol." + name)
    for split in ("development", "confirmation", "final"):
        text(protocol.get("data_split", {}).get(split), "data_split." + split)
    count = protocol.setdefault("hypothesis_count", 3)
    require(type(count) is int and count > 0, "hypothesis_count must be a positive integer")
    stops = protocol.get("stop_conditions")
    require(isinstance(stops, list) and stops, "stop_conditions must be nonempty")
    for stop in stops:
        text(stop, "stop condition")
    metric = protocol.get("metric", {})
    text(metric.get("name"), "metric.name")
    require(metric.get("direction") in ("maximize", "minimize"), "invalid metric direction")
    number(metric.get("min_improvement"), "min_improvement")
    guards = protocol.get("guardrails")
    require(isinstance(guards, list), "guardrails must be an explicit list")
    for guard in guards:
        text(guard.get("metric"), "guardrail.metric")
        require(guard.get("operator") in ("<=", ">="), "guardrail operator must be <= or >=")
        require(type(guard.get("value")) in (int, float) and math.isfinite(guard["value"]), "invalid guardrail value")
    budget = config.get("budget", {})
    for name in ("max_jobs", "max_iterations"):
        require(type(budget.get(name)) is int and budget[name] > 0, name + " must be a positive integer")
    for name in ("per_job_seconds", "total_resource_seconds"):
        number(budget.get(name), name, positive=True)
    execution = config.get("execution", {})
    for name in ("cwd", "job_root"):
        absolute(execution.get(name), "execution." + name)
    commands = config.get("commands")
    require(isinstance(commands, dict) and commands, "commands must be nonempty")
    for name, command in commands.items():
        identifier(name, "command name")
        argv(command, "command")
    backend = config.get("executor", {})
    require(backend.get("mode") in ("local", "ssh", "custom"), "invalid executor mode")
    if backend["mode"] == "custom":
        argv(backend.get("argv"), "custom executor")
    if backend["mode"] == "ssh":
        for name in ("host", "python", "executor_path"):
            text(backend.get(name), "ssh." + name)
    validator = config.get("validator", {})
    argv(validator.get("argv"), "validator")
    files = validator.get("files")
    require(isinstance(files, list) and files, "validator.files must list its implementation files")
    paths = {str(Path(absolute(path, "validator file")).resolve()) for path in files}
    executable = shutil.which(validator["argv"][0])
    require(executable is not None, "validator executable not found")
    paths.add(str(Path(executable).resolve()))
    for arg in validator["argv"][1:]:
        path = Path(arg) if os.path.isabs(arg) else root / arg
        if path.is_file():
            paths.add(str(path.resolve()))
    validator["file_hashes"] = {path: file_hash(path) for path in sorted(paths)}
    validator.setdefault("timeout_seconds", 30)
    number(validator["timeout_seconds"], "validator timeout", positive=True)
    require(validator["timeout_seconds"] <= 300, "validator timeout exceeds 300 seconds")
    return config


def budget_usage(state):
    jobs = list(state["jobs"].values())
    state["budget"] = {"unit": "wall_seconds", "limits": state["config"]["budget"],
                       "used_jobs": len(jobs), "used_iterations": len(jobs),
                       "used_seconds": sum(job.get("charged_seconds", 0) for job in jobs),
                       "reserved_seconds": sum(job.get("reserved_seconds", 0) for job in jobs)}
    return state["budget"]


def check_budget(state, reserve=False):
    usage = budget_usage(state)
    limits = usage["limits"]
    extra = 1 if reserve else 0
    require(usage["used_jobs"] + extra <= limits["max_jobs"], "job budget exhausted")
    require(usage["used_iterations"] + extra <= limits["max_iterations"], "iteration budget exhausted")
    seconds = usage["used_seconds"] + usage["reserved_seconds"]
    if reserve:
        seconds += limits["per_job_seconds"]
    require(seconds <= limits["total_resource_seconds"] + 1e-9, "resource budget exhausted")


def invalidate(state, start=0, reason="inputs changed"):
    for stage in STAGES[start:]:
        gate = state["gates"][stage]
        if gate["status"] != "pending":
            if gate["status"] != "stale":
                state["gate_history"].append(copy.deepcopy(gate))
            gate["status"] = "stale"
            gate["stale_reason"] = reason
    state["stage"] = STAGES[start]
    if state.get("outcome") == "completed":
        state["outcome"] = None


def detect_drift(state):
    config = state["config"]
    expected = {str(Path(config["source_root"]) / relative): checksum
                for relative, checksum in config.get("source_manifest", {}).items()}
    expected.update(config["validator"]["file_hashes"])
    drift = []
    for path, checksum in expected.items():
        try:
            if file_hash(path) != checksum:
                drift.append(path)
        except OSError:
            drift.append(path)
    if drift:
        invalidate(state, reason="frozen files changed")
        state["blockers"] = ["Frozen files changed; explicitly revise the protocol/configuration."]
    else:
        for index, stage in enumerate(STAGES):
            gate = state["gates"][stage]
            if gate["status"] != "passed":
                continue
            evidence = state["evidence"].get(stage)
            try:
                require(evidence is not None and evidence["version"] == state["version"], "gate evidence version changed")
                for artifact in evidence["artifacts"]:
                    require(file_hash(artifact["path"]) == artifact["sha256"], "gate artifact changed")
                jobs = {key: state["jobs"][key] for key in gate["job_ids"]}
                require(all(job["status"] == "succeeded" and job["version"] == state["version"] for job in jobs.values()),
                        "gate job is no longer valid")
                require(input_fingerprint(state, evidence, jobs) == gate["input_fingerprint"], "gate inputs changed")
            except (StudyError, OSError, KeyError) as exc:
                invalidate(state, index, str(exc))
                state["blockers"] = [str(exc)]
                state["next_action"] = "Replace changed evidence and rerun stale gates."
                break
    state["drift"] = drift
    return drift


def input_fingerprint(state, evidence, jobs):
    return digest({"version": state["version"], "evidence": evidence,
                   "jobs": {key: value.get("result") for key, value in jobs.items()},
                   "validator": state["config"]["validator"]})


def load_study(store, expected_revision=None):
    state = store.load()
    require(state.get("schema") == 1 and "jobs" in state, "study not initialized")
    if expected_revision is not None:
        require(state["revision"] == expected_revision, "revision conflict")
    return state


def init_study(state_path, config):
    config = frozen_config(config)
    with Store(state_path) as store:
        state = store.load()
        require("schema" not in state, "state already initialized")
        reserved = {"study_id", "config", "version", "jobs", "gates", "evidence", "history"}
        require(not reserved.intersection(state), "existing state conflicts with study fields")
        state.update({"schema": 1, "study_id": config["study_id"], "config": config,
                      "version": digest(config), "protocol_revision": 1, "stage": "S1",
                      "candidates": [], "current_candidate": None, "next_action": "Run a matching baseline.",
                      "blockers": [], "drift": [], "outcome": None, "jobs": {}, "evidence": {},
                      "evidence_history": [], "gate_history": [], "history": [],
                      "gates": {stage: {"stage": stage, "status": "pending"} for stage in STAGES},
                      "versions": {digest(config): config}})
        budget_usage(state)
        return store.save(state, "init")


def get_status(state_path):
    with Store(state_path) as store:
        state = load_study(store)
        before = digest(state)
        detect_drift(state)
        budget_usage(state)
        return store.save(state, "detect-drift") if digest(state) != before else state


def active(state):
    require(state.get("outcome") is None, "study is finished; explicit revision is required to reopen")
    require(not state.get("drift"), "frozen inputs changed; revise before proceeding")


def response_update(state, job, response):
    require(isinstance(response, dict) and response.get("job_id") == job["job_id"], "executor job_id mismatch")
    encode(response)
    status = response.get("status")
    require(status in {"preparing", "running", "succeeded", "failed", "unknown"}, "invalid executor status")
    if status == "succeeded":
        require(type(response.get("exit_code")) is int and response["exit_code"] == 0,
                "successful job requires exit code zero")
        validate_metrics(response.get("result", {}).get("metrics"))
        number(response.get("elapsed_seconds"), "elapsed_seconds")
        absolute(response.get("job_dir"), "job_dir")
    if status in TERMINAL:
        elapsed = response.get("elapsed_seconds", job["request"]["timeout_seconds"])
        number(elapsed, "elapsed_seconds")
        job["charged_seconds"] = max(job.get("charged_seconds", 0), elapsed)
        job["reserved_seconds"] = 0
    elif job["status"] in TERMINAL:
        # Lost integrity after completion blocks reuse without refunding spent work.
        job["reserved_seconds"] = job["request"]["timeout_seconds"]
    for name in ("status", "exit_code", "result", "result_sha256", "job_dir", "elapsed_seconds", "error"):
        if name in response:
            job[name] = response[name]
    job["last_response"] = response
    budget_usage(state)


def unknown(job, exc):
    job["status"] = "unknown"
    job["error"] = str(exc)[:2000]


def collect_job(state, job_id):
    job = state["jobs"][job_id]
    before = digest({key: job.get(key) for key in ("status", "result")})
    request = {"operation": "collect", "job_id": job_id, "job_root": job["request"]["job_root"]}
    try:
        response_update(state, job, executor.request(job["executor"], request))
    except Exception as exc:
        unknown(job, exc)
        if not job.get("reserved_seconds"):
            job["reserved_seconds"] = job["request"]["timeout_seconds"]
    after = digest({key: job.get(key) for key in ("status", "result")})
    if before != after:
        for index, stage in enumerate(STAGES):
            if job_id in state["gates"][stage].get("job_ids", []):
                invalidate(state, index, "job status or result changed")
                break


def submit_job(state_path, job_id, kind, command, candidate=None, expected_revision=None):
    identifier(job_id, "job_id")
    require(kind in KINDS, "invalid job kind")
    with Store(state_path) as store:
        state = load_study(store, expected_revision)
        if detect_drift(state):
            store.save(state, "detect-drift")
        active(state)
        require(job_id not in state["jobs"], "job ID already exists; reconcile it, never resubmit")
        for stage in STAGES[:KINDS[kind]]:
            require(state["gates"][stage]["status"] == "passed", "prerequisite gate missing: " + stage)
        config = state["config"]
        require(command in config["commands"], "unknown frozen command")
        if kind != "baseline":
            require(candidate in [item["id"] for item in state["candidates"]], "unknown candidate")
            if state["current_candidate"] is not None:
                require(candidate == state["current_candidate"], "candidate differs from selected confirmation")
        check_budget(state, reserve=True)
        payload = {"operation": "submit", "job_id": job_id, "job_root": config["execution"]["job_root"],
                   "cwd": config["execution"]["cwd"], "argv": config["commands"][command],
                   "timeout_seconds": config["budget"]["per_job_seconds"]}
        job = {"job_id": job_id, "kind": kind, "command": command, "candidate": candidate,
               "version": state["version"], "status": "preparing", "request": payload,
               "executor": copy.deepcopy(config["executor"]), "reserved_seconds": payload["timeout_seconds"],
               "charged_seconds": 0, "submitted_at": time.time()}
        state["jobs"][job_id] = job
        budget_usage(state)
        state["next_action"] = "Reconcile " + job_id + " until terminal."
        store.save(state, "submit-intent")
        try:
            response_update(state, job, executor.request(job["executor"], payload))
        except Exception as exc:
            unknown(job, exc)
        return store.save(state, "submit-response")


def reconcile_job(state_path, job_id, expected_revision=None):
    with Store(state_path) as store:
        state = load_study(store, expected_revision)
        require(job_id in state["jobs"], "unknown job_id")
        collect_job(state, job_id)
        detect_drift(state)
        budget_usage(state)
        return store.save(state, "reconcile")


def add_evidence(state_path, evidence, expected_revision=None):
    evidence = copy.deepcopy(evidence)
    encode(evidence)
    stage = evidence.get("stage")
    require(stage in STAGES, "invalid evidence stage")
    with Store(state_path) as store:
        state = load_study(store, expected_revision)
        if detect_drift(state):
            store.save(state, "detect-drift")
        active(state)
        require(evidence.get("version") == state["version"], "evidence version mismatch")
        artifacts = evidence.get("artifacts")
        require(isinstance(artifacts, list) and artifacts, "evidence requires artifact files")
        evidence["artifacts"] = [{"path": absolute(path, "artifact"), "sha256": file_hash(path)}
                                 for path in artifacts]
        require(isinstance(evidence.get("jobs"), dict), "evidence.jobs must be an object")
        require(isinstance(evidence.get("judgment"), dict), "evidence.judgment must be an object")
        evidence["id"] = digest(evidence)
        evidence["recorded_at"] = time.time()
        state["evidence_history"].append(evidence)
        state["evidence"][stage] = evidence
        invalidate(state, STAGES.index(stage), "evidence replaced")
        return store.save(state, "evidence")


def validate_metrics(metrics):
    require(isinstance(metrics, dict) and metrics, "metrics must be a nonempty object")
    for name, value in metrics.items():
        text(name, "metric name")
        require(type(value) in (int, float) and math.isfinite(value), "metric must be finite: " + name)


def evidence_jobs(state, stage, evidence):
    jobs = {}
    mapping = evidence["jobs"]
    for kind in REQUIRED_JOBS[stage]:
        require(isinstance(mapping.get(kind), list) and mapping[kind], "missing job evidence: " + kind)
    for kind, job_ids in mapping.items():
        require(kind in KINDS and isinstance(job_ids, list), "invalid evidence job kind/list")
        for job_id in job_ids:
            require(isinstance(job_id, str) and job_id in state["jobs"], "evidence refers to missing job")
            job = state["jobs"][job_id]
            require(job["kind"] == kind, "job kind mismatch")
            require(job["version"] == state["version"], "job version mismatch")
            require(job["status"] == "succeeded" and job.get("exit_code") == 0, "job not successfully completed: " + job_id)
            validate_metrics(job.get("result", {}).get("metrics"))
            jobs[job_id] = job
    if stage in ("S2", "S3", "S5"):
        baseline_id = state["evidence"]["S1"]["jobs"]["baseline"][0]
        baseline = state["jobs"][baseline_id]
        require(baseline["status"] == "succeeded" and baseline["version"] == state["version"], "baseline is no longer valid")
        jobs[baseline_id] = baseline
    return jobs


def run_validator(state, stage, evidence, jobs):
    validator = state["config"]["validator"]
    request = {"stage": stage, "version": state["version"], "protocol": state["config"]["protocol"],
               "jobs": jobs, "evidence": evidence, "source_root": state["config"]["source_root"]}
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            result = subprocess.run(validator["argv"], input=encode(request), stdout=output, stderr=errors,
                                    cwd=state["config"]["source_root"], timeout=validator["timeout_seconds"], check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StudyError("validator failed: " + str(exc)) from exc
        errors.seek(0)
        require(result.returncode == 0, "validator failed: " + errors.read(2000).decode(errors="replace"))
        output.seek(0)
        raw = output.read(MAX_INPUT + 1)
    require(len(raw) <= MAX_INPUT, "validator output exceeds 1 MiB")
    facts = decode(raw)
    require(isinstance(facts.get("checks"), dict), "validator requires named checks")
    for name in REQUIRED_CHECKS[stage]:
        require(facts["checks"].get(name) is True, "validator check failed/missing: " + name)
    recomputed = facts.get("metrics")
    require(isinstance(recomputed, dict), "validator must recompute metrics")
    for job_id, job in jobs.items():
        validate_metrics(recomputed.get(job_id))
        require(recomputed[job_id] == job["result"]["metrics"], "recomputed metrics differ: " + job_id)
    return {"argv": validator["argv"], "file_hashes": validator["file_hashes"],
            "exit_code": result.returncode, "output_sha256": hashlib.sha256(raw).hexdigest(), "output": facts}


def positive_judgment(judgment, key):
    require(judgment.get(key) is True, "scientific judgment missing or inconclusive: " + key)


def independent(state, review):
    reviewer = text(review.get("reviewer"), "reviewer")
    require(review.get("independent") is True and reviewer != state["config"]["author"],
            "an independent reviewer is required")
    return reviewer


def check_judgment(state, stage, evidence):
    judgment = evidence["judgment"]
    mapping = evidence["jobs"]
    if stage == "S1":
        text(judgment.get("diagnosis"), "diagnosis")
        positive_judgment(judgment, "evaluation_protocol_unchanged")
        hypotheses = judgment.get("hypotheses")
        require(isinstance(hypotheses, list) and len(hypotheses) == state["config"]["protocol"]["hypothesis_count"],
                "incorrect hypothesis count")
        ids = set()
        for hypothesis in hypotheses:
            identifier(hypothesis.get("id"), "hypothesis id")
            require(hypothesis["id"] not in ids, "duplicate hypothesis id")
            ids.add(hypothesis["id"])
            for field in ("prediction", "change_boundary", "falsification"):
                text(hypothesis.get(field), "hypothesis." + field)
        require(len(mapping["baseline"]) == 1, "S1 requires one declared baseline")
    elif stage == "S2":
        positive_judgment(judgment, "selection_used_development_only")
        positive_judgment(judgment, "uncertainty_adequate")
        text(judgment.get("assessment"), "assessment")
        require(len(mapping["confirm"]) == 1, "declare exactly one confirmation winner")
        winner = state["jobs"][mapping["confirm"][0]]["candidate"]
        for kind in ("smoke", "screen"):
            require(any(state["jobs"][item]["candidate"] == winner for item in mapping[kind]),
                    "winner lacks " + kind + " evidence")
    elif stage == "S3":
        text(judgment.get("simplification"), "simplification")
        components = judgment.get("components")
        require(isinstance(components, list) and components, "component/interaction accounting required")
        for component in components:
            text(component.get("name"), "component name")
            require(component.get("kind") in ("scientific", "interaction_group", "infrastructure"), "invalid component kind")
            require(type(component.get("retained")) is bool, "component retained decision required")
            require(type(component.get("training_semantics")) is bool, "training semantics decision required")
            if component["retained"] and component["kind"] != "infrastructure":
                support = component.get("support_jobs")
                require(isinstance(support, list) and support and set(support) <= set(mapping["ablation"]),
                        "retained scientific component/group lacks ablation evidence")
                if component["training_semantics"]:
                    positive_judgment(component, "matched_retraining")
    elif stage == "S4":
        reviews = judgment.get("reviews")
        require(isinstance(reviews, list) and reviews, "independent review required")
        reviewers = {independent(state, review) for review in reviews}
        for review in reviews:
            critiques = review.get("critiques")
            require(isinstance(critiques, list) and critiques, "review must record concrete critiques")
            for critique in critiques:
                identifier(critique.get("id"), "critique id")
                require(critique.get("severity") in ("fatal", "major", "minor"), "invalid critique severity")
                require(type(critique.get("empirical")) is bool, "critique empirical classification required")
                text(critique.get("rationale"), "critique rationale")
                if critique["severity"] == "fatal":
                    require(critique.get("closed") is True and critique.get("closure_reviewer") in reviewers,
                            "fatal critique lacks independent closure")
                    require(critique.get("resolution") in ("experiment", "withdrawn", "clarified"), "invalid fatal resolution")
                    if critique["empirical"]:
                        require(critique["resolution"] in ("experiment", "withdrawn"), "empirical fatal critique needs experiment or withdrawal")
                        if critique["resolution"] == "experiment":
                            response = critique.get("response_jobs")
                            require(isinstance(response, list) and response and set(response) <= set(mapping["rebuttal"]),
                                    "fatal empirical critique lacks response experiments")
    else:
        audits = judgment.get("audits", {})
        for name in REQUIRED_CHECKS["S5"]:
            audit = audits.get(name, {})
            independent(state, audit)
            text(audit.get("scope"), name + " audit scope")
            text(audit.get("statement"), name + " audit statement")
            require(type(audit.get("fatal_open")) is int and audit["fatal_open"] == 0, "unresolved fatal audit findings")
            positive_judgment(audit, "approved")
        require(all(job["status"] in TERMINAL for job in state["jobs"].values()), "unresolved study jobs remain")


def metric_thresholds(state, job_ids):
    protocol = state["config"]["protocol"]
    metric = protocol["metric"]
    baseline_id = state["evidence"]["S1"]["jobs"]["baseline"][0]
    baseline = state["jobs"][baseline_id]["result"]["metrics"]
    require(metric["name"] in baseline, "baseline lacks primary metric")
    for job_id in job_ids:
        scores = state["jobs"][job_id]["result"]["metrics"]
        require(metric["name"] in scores, "job lacks primary metric")
        gain = scores[metric["name"]] - baseline[metric["name"]]
        if metric["direction"] == "minimize":
            gain = -gain
        require(gain >= metric["min_improvement"], "minimum practical improvement not met")
        for guard in protocol["guardrails"]:
            require(guard["metric"] in scores, "missing guardrail metric")
            value = scores[guard["metric"]]
            passed = value <= guard["value"] if guard["operator"] == "<=" else value >= guard["value"]
            require(passed, "guardrail failed: " + guard["metric"])


def run_gate(state_path, stage, expected_revision=None):
    require(stage in STAGES, "invalid stage")
    with Store(state_path) as store:
        state = load_study(store, expected_revision)
        require(state.get("outcome") is None, "study is finished; gate records are unchanged")
        index = STAGES.index(stage)
        record = {"stage": stage, "status": "failed", "version": state["version"], "checked_at": time.time(),
                  "mechanical": {}, "scientific_judgment": None, "reviewers": []}
        try:
            detect_drift(state)
            active(state)
            check_budget(state)
            for previous in STAGES[:index]:
                require(state["gates"][previous]["status"] == "passed", "prerequisite gate missing: " + previous)
            evidence = state["evidence"].get(stage)
            require(evidence is not None, "required evidence missing")
            require(evidence["version"] == state["version"], "evidence version mismatch")
            for artifact in evidence["artifacts"]:
                require(file_hash(artifact["path"]) == artifact["sha256"], "evidence artifact hash changed")
            jobs = evidence_jobs(state, stage, evidence)
            collect_ids = set(jobs)
            for previous in STAGES[:index]:
                collect_ids.update(state["gates"][previous].get("job_ids", []))
            for job_id in sorted(collect_ids):
                collect_job(state, job_id)
            for previous in STAGES[:index]:
                require(state["gates"][previous]["status"] == "passed", "prerequisite job integrity changed: " + previous)
            jobs = evidence_jobs(state, stage, evidence)
            check_budget(state)
            record["job_ids"] = sorted(jobs)
            record["evidence_id"] = evidence["id"]
            record["input_fingerprint"] = input_fingerprint(state, evidence, jobs)
            record["mechanical"] = run_validator(state, stage, evidence, jobs)
            # Validator execution is a fact; its scientific appropriateness still needs review.
            if stage in ("S2", "S3", "S5"):
                kind = {"S2": "confirm", "S3": "retest", "S5": "final"}[stage]
                metric_thresholds(state, evidence["jobs"][kind])
            check_judgment(state, stage, evidence)
            record["scientific_judgment"] = evidence["judgment"]
            if stage == "S4":
                record["reviewers"] = [review["reviewer"] for review in evidence["judgment"]["reviews"]]
            if stage == "S5":
                record["reviewers"] = sorted({review["reviewer"] for review in evidence["judgment"]["audits"].values()})
            record["status"] = "passed"
            state["blockers"] = []
            if stage == "S1":
                state["candidates"] = evidence["judgment"]["hypotheses"]
            if stage == "S2":
                state["current_candidate"] = state["jobs"][evidence["jobs"]["confirm"][0]]["candidate"]
            state["stage"] = STAGES[index + 1] if index < 4 else "complete"
            state["next_action"] = "Prepare " + state["stage"] + " evidence." if index < 4 else "Study workflow complete."
            if index == 4:
                state["outcome"] = "completed"
        except (StudyError, OSError, KeyError, TypeError) as exc:
            record["error"] = str(exc)
            if "judgment" in str(exc) or "independent" in str(exc):
                record["status"] = "inconclusive"
            state["blockers"] = [str(exc)]
            state["next_action"] = "Resolve " + stage + " blockers, or finish with a nonpositive outcome."
            if index < 4:
                invalidate(state, index + 1, "prerequisite gate failed")
            state["stage"] = stage
        if state["gates"][stage]["status"] != "pending":
            state["gate_history"].append(copy.deepcopy(state["gates"][stage]))
        state["gates"][stage] = record
        if state["outcome"] is None:
            state["stage"] = next(item for item in STAGES if state["gates"][item]["status"] != "passed")
        return store.save(state, "gate")


def revise_study(state_path, config, reason, expected_revision=None):
    text(reason, "revision reason")
    config = frozen_config(config)
    with Store(state_path) as store:
        state = load_study(store, expected_revision)
        require(config["study_id"] == state["study_id"], "cannot change study identity")
        require(config["author"] == state["config"]["author"], "cannot change study author")
        old = state["version"]
        state["version"] = digest(config)
        state["config"] = config
        state["versions"][state["version"]] = config
        state["protocol_revision"] += 1
        invalidate(state, reason=reason)
        state["history"].append({"action": "revise", "old_version": old, "version": state["version"], "reason": reason})
        state["outcome"] = None
        state["drift"] = []
        state["blockers"] = []
        state["candidates"] = []
        state["current_candidate"] = None
        state["next_action"] = "Revalidate baseline and all evidence under the new frozen version."
        budget_usage(state)
        return store.save(state, "revise")


def finish_study(state_path, outcome, reason, expected_revision=None):
    require(outcome in ("negative", "inconclusive", "budget_exhausted"), "invalid nonpositive outcome")
    text(reason, "finish reason")
    with Store(state_path) as store:
        state = load_study(store, expected_revision)
        state["outcome"] = outcome
        state["history"].append({"action": "finish", "outcome": outcome, "reason": reason})
        state["next_action"] = "Reconcile existing tasks; no new submissions."
        return store.save(state, "finish")


def review_package(state_path, output):
    state = get_status(state_path)
    package = {"purpose": "Independent review; declaring a different reviewer name does not establish independence.",
               "study": state, "required_checks": REQUIRED_CHECKS,
               "instructions": "Review artifacts and frozen protocol in a separate context; record concrete critiques and audit scopes."}
    atomic_json(output, package)
    return package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="explicit state JSON path")
    parser.add_argument("--expected-revision", type=int)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("status")
    init = commands.add_parser("init")
    init.add_argument("--config", required=True)
    submit = commands.add_parser("submit")
    submit.add_argument("--job-id", required=True)
    submit.add_argument("--kind", choices=KINDS, required=True)
    submit.add_argument("--command", required=True)
    submit.add_argument("--candidate")
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--job-id", required=True)
    evidence = commands.add_parser("evidence")
    evidence.add_argument("--file", required=True)
    gate = commands.add_parser("gate")
    gate.add_argument("--stage", choices=STAGES, required=True)
    revise = commands.add_parser("revise")
    revise.add_argument("--config", required=True)
    revise.add_argument("--reason", required=True)
    finish = commands.add_parser("finish")
    finish.add_argument("--outcome", choices=("negative", "inconclusive", "budget_exhausted"), required=True)
    finish.add_argument("--reason", required=True)
    package = commands.add_parser("review-package")
    package.add_argument("--output", required=True)
    args = parser.parse_args()
    path, revision = args.state, args.expected_revision
    try:
        if args.action == "init":
            state = init_study(path, read_json(args.config))
        elif args.action == "status":
            state = get_status(path)
        elif args.action == "submit":
            state = submit_job(path, args.job_id, args.kind, args.command, args.candidate, revision)
        elif args.action == "reconcile":
            state = reconcile_job(path, args.job_id, revision)
        elif args.action == "evidence":
            state = add_evidence(path, read_json(args.file), revision)
        elif args.action == "gate":
            state = run_gate(path, args.stage, revision)
        elif args.action == "revise":
            state = revise_study(path, read_json(args.config), args.reason, revision)
        elif args.action == "finish":
            state = finish_study(path, args.outcome, args.reason, revision)
        else:
            state = review_package(path, args.output)
        print(json.dumps(state, indent=2, allow_nan=False))
        return 1 if args.action == "gate" and state["gates"][args.stage]["status"] != "passed" else 0
    except (StudyError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, allow_nan=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
