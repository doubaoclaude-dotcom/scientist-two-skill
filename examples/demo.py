#!/usr/bin/env python3
"""Run S1-S5 on a deterministic synthetic fixture; no model or GPU required.

Reviewer declarations below are test fixtures, not real independent reviews.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "examples"))
from validator import PROTOCOL


def run_demo(directory, mode="local"):
    import study

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "state.json"
    if state_path.exists():
        raise ValueError("demo output already has state.json; use a new directory")
    manifest = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in ["examples/experiment.py", "examples/validator.py"]}
    commands = {}
    for kind in ["baseline", "smoke", "screen", "confirm", "ablation", "retest", "rebuttal", "final"]:
        variant = "baseline" if kind == "baseline" else "ablation" if kind == "ablation" else "candidate"
        split = "confirmation" if kind == "confirm" else "final" if kind == "final" else "development"
        commands[kind] = [sys.executable, str(ROOT / "examples/experiment.py"),
                          "--variant", variant, "--split", split]
    executor = {"mode": mode}
    if mode == "custom":
        executor["argv"] = [sys.executable, str(ROOT / "examples/custom_adapter.py")]
    config = {
        "study_id": "synthetic-arithmetic-demo", "author": "synthetic-fixture-author",
        "source_root": str(ROOT), "source_manifest": manifest,
        "identities": {"data": "Synthetic integer enumeration y=2*x+1; disjoint x ranges 0..2, 3..5, 6..8.",
                       "evaluator": "Pinned independent arithmetic recomputation in examples/validator.py."},
        "protocol": PROTOCOL,
        "budget": {"max_jobs": 20, "max_iterations": 20, "per_job_seconds": 5,
                   "total_resource_seconds": 100},
        "executor": executor, "execution": {"cwd": str(ROOT), "job_root": str(directory / "jobs")},
        "commands": commands,
        "validator": {"argv": [sys.executable, str(ROOT / "examples/validator.py")],
                      "files": [str(ROOT / "examples/validator.py")]},
    }
    (directory / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    state = study.init_study(state_path, config)
    stages = {
        "S1": ["baseline"], "S2": ["smoke", "screen", "confirm"],
        "S3": ["ablation", "retest"], "S4": ["rebuttal"], "S5": ["final"],
    }
    judgments = {
        "S1": {"diagnosis": "Synthetic baseline omits the intercept and incurs unit error on every row.",
               "hypotheses": [
                   {"id": "h1", "prediction": "Adding the known intercept makes exact predictions.",
                    "change_boundary": "Only the prediction intercept; evaluation remains frozen.",
                    "falsification": "Candidate fails to improve reserved confirmation score by 0.1."},
                   {"id": "h2", "prediction": "Changing the slope creates nonconstant residuals.",
                    "change_boundary": "Prediction slope only.",
                    "falsification": "All enumerated prediction errors remain constant."},
                   {"id": "h3", "prediction": "Removing the intercept restores baseline error.",
                    "change_boundary": "Remove prediction intercept only.",
                    "falsification": "Ablation retains the candidate score."}],
               "evaluation_protocol_unchanged": True},
        "S2": {"selection_used_development_only": True, "uncertainty_adequate": True,
               "assessment": "Selected h1 on development arithmetic; reserved confirmation verifies exact improvement. No stochastic inference."},
        "S3": {"simplification": "The intercept is the sole retained scientific component; its removal restores baseline error.",
               "components": [{"name": "intercept", "kind": "scientific", "retained": True,
                               "support_jobs": ["ablation"], "training_semantics": False,
                               "matched_retraining": False}]},
        "S4": {"reviews": [{"reviewer": "fixture-reviewer", "independent": True,
                "critiques": [{"id": "fixture-intercept", "severity": "fatal", "empirical": True,
                               "response_jobs": ["rebuttal"], "resolution": "experiment", "closed": True,
                               "closure_reviewer": "fixture-reviewer",
                               "rationale": "SYNTHETIC TEST FIXTURE: rerun independently recomputed from raw arithmetic observations; no real reviewer participated."}]}]},
        "S5": {"audits": {name: {"reviewer": "fixture-reviewer", "independent": True,
                    "scope": "software test fixture", "statement": "SYNTHETIC TEST FIXTURE: arithmetic and pinned protocol verified; no external claims or citations; not real independent scientific review.",
                    "fatal_open": 0, "approved": True} for name in ["numerical", "protocol", "citations", "code"]}},
    }
    for stage, kinds in stages.items():
        for kind in kinds:
            state = study.submit_job(state_path, kind, kind, kind,
                                     candidate=None if kind == "baseline" else "h1")
            deadline = time.monotonic() + 15
            while state["jobs"][kind]["status"] not in {"succeeded", "failed"}:
                if time.monotonic() >= deadline:
                    raise RuntimeError("demo job did not finish; reconcile existing job: " + kind)
                time.sleep(0.05)
                state = study.reconcile_job(state_path, kind)
            if state["jobs"][kind]["status"] != "succeeded":
                raise RuntimeError("demo job failed: " + kind)
        artifact = directory / (stage + "-fixture.json")
        artifact.write_text(json.dumps({"synthetic": True,
            "notice": "Software test fixture only. Independent reviewer declarations are fixtures, not real scientific review.",
            "stage": stage, "judgment": judgments[stage]}, indent=2) + "\n")
        state = study.add_evidence(state_path, {"stage": stage, "version": state["version"],
            "artifacts": [str(artifact)], "jobs": {kind: [kind] for kind in kinds},
            "judgment": judgments[stage]})
        state = study.run_gate(state_path, stage)
        if state["gates"][stage]["status"] != "passed":
            raise RuntimeError("demo gate failed: " + stage + " " + json.dumps(state["gates"][stage]))
    return {"synthetic": True, "mode": mode, "gates": list(stages),
            "baseline_score": state["jobs"]["baseline"]["result"]["metrics"]["score"],
            "final_score": state["jobs"]["final"]["result"]["metrics"]["score"],
            "jobs": len(state["jobs"]), "state": str(state_path), "artifacts": str(directory),
            "notice": "Software test fixture; reviewer declarations are synthetic, not real scientific review."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, help="new output directory to retain state and artifacts")
    parser.add_argument("--mode", choices=["local", "custom"], default="local")
    args = parser.parse_args()
    if args.directory is not None:
        result = run_demo(args.directory, args.mode)
        result["retained"] = True
    else:
        with tempfile.TemporaryDirectory(prefix="scientist-demo-") as directory:
            result = run_demo(directory, args.mode)
        result["retained"] = False
        result["notice"] += " Temporary state and artifacts were removed; use --directory to retain them."
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
