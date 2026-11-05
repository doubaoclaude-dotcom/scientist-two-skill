#!/usr/bin/env python3
"""Independent arithmetic recomputation for a synthetic software test fixture.

This fixture does not constitute independent scientific review or an audit.
"""

import hashlib
import json
from pathlib import Path
import sys


EXPERIMENT_SHA256 = "61a5a51bb2f84f393bb65430cd525382fe33d15933f5ddcd94a74cda1640f430"
PROTOCOL = {
    "objective": "Synthetic fixture: recover y = 2*x + 1 on enumerated integer inputs.",
    "baseline": "Prediction 2*x, with the intercept deliberately omitted.",
    "data_split": {"development": "x = 0, 1, 2", "confirmation": "x = 3, 4, 5",
                   "final": "x = 6, 7, 8; opened only at S5"},
    "metric": {"name": "score", "direction": "maximize", "min_improvement": 0.1},
    "statistical_rule": "Exact enumeration; deterministic error has zero sampling uncertainty; no population inference.",
    "guardrails": [{"metric": "max_abs_error", "operator": "<=", "value": 1}],
    "stop_conditions": ["Stop after one selected hypothesis, or any failed verification."],
    "hypothesis_count": 3,
}
CHECKS = {"S1": ["baseline"], "S2": ["smoke", "uncertainty"],
          "S3": ["ablation", "uncertainty"], "S4": ["rebuttal"],
          "S5": ["numerical", "protocol", "citations", "code"]}


def validate(payload):
    if payload["protocol"] != PROTOCOL:
        raise ValueError("toy evaluation protocol changed")
    root = Path(payload["source_root"])
    if hashlib.sha256((root / "examples/experiment.py").read_bytes()).hexdigest() != EXPERIMENT_SHA256:
        raise ValueError("unexpected toy experiment source identity")
    if (root / "examples/validator.py").read_bytes() != Path(__file__).read_bytes():
        raise ValueError("unexpected evaluator source identity")
    metrics = {}
    splits = {"development": [0, 1, 2], "confirmation": [3, 4, 5], "final": [6, 7, 8]}
    for job_id, job in payload["jobs"].items():
        raw = json.loads((Path(job["job_dir"]) / "observations.json").read_text())
        variant, split = raw["variant"], raw["split"]
        if raw.get("synthetic") is not True or variant not in {"baseline", "candidate", "ablation"}:
            raise ValueError("unexpected observations identity")
        expected = [{"x": x, "target": 2*x+1, "prediction": 2*x+(variant == "candidate")}
                    for x in splits[split]]
        if raw["rows"] != expected:
            raise ValueError("raw observations do not match enumerated toy inputs")
        if (split == "final") != (job["kind"] == "final"):
            raise ValueError("final split used outside final evaluation")
        expected_variant = "baseline" if job["kind"] == "baseline" else "ablation" if job["kind"] == "ablation" else "candidate"
        if variant != expected_variant:
            raise ValueError("job variant does not match its declared purpose")
        if job["kind"] == "confirm" and split != "confirmation":
            raise ValueError("confirmation did not use its reserved split")
        errors = [(row["prediction"] - row["target"]) ** 2 for row in raw["rows"]]
        metrics[job_id] = {"score": 1 / (1 + sum(errors) / len(errors)),
                           "max_abs_error": max(errors) ** 0.5}
        if job["result"]["metrics"] != metrics[job_id]:
            raise ValueError("reported metrics disagree with raw observations")
    return {"metrics": metrics, "checks": {name: True for name in CHECKS[payload["stage"]]}}


if __name__ == "__main__":
    try:
        print(json.dumps(validate(json.load(sys.stdin)), allow_nan=False, sort_keys=True))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
