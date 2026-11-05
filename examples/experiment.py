#!/usr/bin/env python3
"""Synthetic arithmetic fixture, with no model, GPU, or scientific claim."""

import argparse
import json
import os
from pathlib import Path


SPLITS = {"development": [0, 1, 2], "confirmation": [3, 4, 5], "final": [6, 7, 8]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["baseline", "candidate", "ablation"], required=True)
    parser.add_argument("--split", choices=SPLITS, required=True)
    args = parser.parse_args()
    rows = [{"x": x, "target": 2 * x + 1,
             "prediction": 2 * x + (args.variant == "candidate")} for x in SPLITS[args.split]]
    errors = [(row["prediction"] - row["target"]) ** 2 for row in rows]
    result_path = Path(os.environ["SCIENTIST_RESULT_PATH"])
    raw_path = result_path.parent / "observations.json"
    raw_path.write_text(json.dumps({"synthetic": True, "variant": args.variant,
                                    "split": args.split, "rows": rows}, sort_keys=True) + "\n")
    metrics = {"score": 1 / (1 + sum(errors) / len(errors)), "max_abs_error": max(errors) ** 0.5}
    result_path.write_text(json.dumps({"metrics": metrics, "synthetic": True,
                                       "observations": str(raw_path)}, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
