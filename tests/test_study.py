"""Controller constraints; demo tests separately exercise real process execution."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import study


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state_path = self.root / "state.json"
        self.source = self.root / "experiment.py"
        self.source.write_text("# Deterministic fixture implementation.\n")
        self.validator = self.root / "validator.py"
        self.validator.write_text(
            "import json, pathlib, sys\n"
            "r=json.load(sys.stdin)\n"
            "metrics={k:json.loads((pathlib.Path(v['job_dir'])/'result.json').read_text())['metrics'] for k,v in r['jobs'].items()}\n"
            "checks={k:True for k in ['baseline','smoke','uncertainty','ablation','rebuttal','numerical','protocol','citations','code']}\n"
            "print(json.dumps({'checks':checks,'metrics':metrics}))\n")
        self.artifact = self.root / "notes.txt"
        self.artifact.write_text("Synthetic evidence for controller tests.\n")
        self.config = {
            "study_id": "fixture", "author": "author", "source_root": str(self.root),
            "source_manifest": {"experiment.py": study.file_hash(self.source)},
            "identities": {"data": "fixture data v1", "evaluator": "fixture evaluator v1"},
            "protocol": {"objective": "Test workflow mechanics", "baseline": "fixed baseline",
                         "data_split": {"development": "fixture dev", "confirmation": "fixture confirm", "final": "fixture final"},
                         "metric": {"name": "score", "direction": "maximize", "min_improvement": 1},
                         "statistical_rule": "deterministic fixture, no empirical claim", "guardrails": [],
                         "stop_conditions": ["stop on budget exhaustion"], "hypothesis_count": 3},
            "budget": {"max_jobs": 10, "max_iterations": 10, "per_job_seconds": 5, "total_resource_seconds": 50},
            "executor": {"mode": "local"}, "execution": {"cwd": str(self.root), "job_root": str(self.root / "jobs")},
            "commands": {"run": [sys.executable, "experiment.py"]},
            "validator": {"argv": [sys.executable, str(self.validator)], "files": [str(self.validator)]},
        }
        self.responses = {}
        mock_executor = patch.object(study.executor, "request", side_effect=self.collect)
        mock_executor.start()
        self.addCleanup(mock_executor.stop)

    def collect(self, config, payload):
        response = copy.deepcopy(self.responses.get(payload["job_id"], {"job_id": payload["job_id"], "status": "unknown"}))
        if response["status"] == "succeeded":
            path = Path(response["job_dir"]) / "result.json"
            try:
                response["result"] = study.read_json(path)
                study.executor._validate_result(response["result"])
            except (OSError, ValueError):
                return {"job_id": payload["job_id"], "status": "unknown", "error": "invalid result JSON"}
        return response

    def init(self):
        return study.init_study(self.state_path, self.config)

    def response(self, job_id="baseline", score=1, elapsed=0.1, status="succeeded"):
        directory = self.root / "jobs" / job_id
        directory.mkdir(parents=True, exist_ok=True)
        result = {"metrics": {"score": score}}
        path = directory / "result.json"
        path.write_text(json.dumps(result))
        response = {"job_id": job_id, "status": status, "exit_code": 0 if status == "succeeded" else 2,
                    "result": result, "job_dir": str(directory), "elapsed_seconds": elapsed}
        self.responses[job_id] = copy.deepcopy(response)
        return response

    def baseline(self):
        response = self.response()
        with patch.object(study.executor, "request", return_value=response):
            return study.submit_job(self.state_path, "baseline", "baseline", "run")

    def evidence(self, state):
        return {"stage": "S1", "version": state["version"], "artifacts": [str(self.artifact)],
                "jobs": {"baseline": ["baseline"]}, "passed": True,
                "judgment": {"diagnosis": "known fixture bottleneck", "evaluation_protocol_unchanged": True,
                             "hypotheses": [{"id": "h" + str(i), "prediction": "testable", "change_boundary": "fixture",
                                             "falsification": "no gain"} for i in range(3)]}}

    def pass_s1(self):
        self.init()
        state = self.baseline()
        study.add_evidence(self.state_path, self.evidence(state))
        state = study.run_gate(self.state_path, "S1")
        self.assertEqual(state["gates"]["S1"]["status"], "passed", state["gates"]["S1"])
        return state

    def test_intent_and_budget_are_durable_before_executor(self):
        self.init()
        def request(config, payload):
            snapshot = study.read_json(self.state_path)
            self.assertEqual(payload["operation"], "submit")
            self.assertNotIn("input_manifest", payload)
            self.assertEqual(snapshot["jobs"]["baseline"]["status"], "preparing")
            self.assertEqual(snapshot["budget"]["reserved_seconds"], 5)
            self.assertEqual(snapshot["budget"]["used_jobs"], 1)
            return self.response()
        with patch.object(study.executor, "request", side_effect=request):
            state = study.submit_job(self.state_path, "baseline", "baseline", "run")
        self.assertEqual(state["budget"]["reserved_seconds"], 0)
        self.assertEqual(state["budget"]["used_seconds"], 0.1)

    def test_unknown_never_resubmits_and_retains_reservation(self):
        self.init()
        with patch.object(study.executor, "request", side_effect=TimeoutError("connection lost")) as request:
            state = study.submit_job(self.state_path, "lost", "baseline", "run")
            self.assertEqual(state["jobs"]["lost"]["status"], "unknown")
            self.assertEqual(state["budget"]["reserved_seconds"], 5)
            with self.assertRaisesRegex(study.StudyError, "already exists"):
                study.submit_job(self.state_path, "lost", "baseline", "run")
            self.assertEqual(request.call_count, 1)
        with patch.object(study.executor, "request", return_value=self.response("lost")) as request:
            state = study.reconcile_job(self.state_path, "lost")
            self.assertEqual(request.call_args.args[1]["operation"], "collect")
        self.assertEqual(state["jobs"]["lost"]["status"], "succeeded")

    def test_event_before_snapshot_fault_recovers_identity_budget_revision_and_fields(self):
        self.state_path.write_text(json.dumps({"external_notes": {"keep": True}}))
        original = self.init()
        with patch.object(study.Store, "write_snapshot", side_effect=OSError("simulated power loss")):
            with self.assertRaises(OSError):
                study.submit_job(self.state_path, "lost", "baseline", "run")
        state = study.get_status(self.state_path)
        self.assertEqual(state["revision"], original["revision"] + 1)
        self.assertEqual(state["external_notes"], {"keep": True})
        self.assertEqual(state["budget"]["reserved_seconds"], 5)
        self.assertEqual(state["jobs"]["lost"]["status"], "preparing")
        with self.assertRaisesRegex(study.StudyError, "already exists"):
            study.submit_job(self.state_path, "lost", "baseline", "run")

    def test_torn_final_event_is_discarded_before_next_append(self):
        state = self.init()
        events = self.state_path.with_name("state.json.events.jsonl")
        with events.open("ab") as stream:
            stream.write(b'{"revision":')
        restored = study.get_status(self.state_path)
        self.assertEqual(restored["revision"], state["revision"])
        study.finish_study(self.state_path, "inconclusive", "fixture complete")
        self.assertEqual(study.get_status(self.state_path)["outcome"], "inconclusive")

    def test_revision_conflict_does_not_overwrite(self):
        state = self.init()
        with self.assertRaisesRegex(study.StudyError, "revision conflict"):
            study.finish_study(self.state_path, "negative", "old caller", state["revision"] - 1)
        self.assertEqual(study.get_status(self.state_path)["revision"], state["revision"])

    def test_snapshot_tampering_is_detected(self):
        self.init()
        state = study.read_json(self.state_path)
        state["outcome"] = "completed"
        self.state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(study.StudyError, "snapshot does not match"):
            study.get_status(self.state_path)

    def test_resource_reservation_limit_blocks_before_executor(self):
        self.config["budget"]["total_resource_seconds"] = 4
        self.init()
        with patch.object(study.executor, "request") as request:
            with self.assertRaisesRegex(study.StudyError, "resource budget"):
                study.submit_job(self.state_path, "baseline", "baseline", "run")
            request.assert_not_called()

    def test_job_and_iteration_limits_include_failed_jobs(self):
        self.config["budget"]["max_iterations"] = 1
        self.init()
        with patch.object(study.executor, "request", return_value=self.response(status="failed")):
            study.submit_job(self.state_path, "baseline", "baseline", "run")
        with self.assertRaisesRegex(study.StudyError, "iteration budget"):
            study.submit_job(self.state_path, "again", "baseline", "run")
        state = study.finish_study(self.state_path, "negative", "no improvement")
        self.assertEqual(state["jobs"]["baseline"]["status"], "failed")
        self.assertEqual(state["outcome"], "negative")

    def test_prerequisite_gate_and_missing_evidence_block(self):
        self.init()
        state = study.run_gate(self.state_path, "S2")
        self.assertIn("prerequisite", state["gates"]["S2"]["error"])
        state = study.run_gate(self.state_path, "S1")
        self.assertIn("evidence missing", state["gates"]["S1"]["error"])
        with self.assertRaisesRegex(study.StudyError, "prerequisite"):
            study.submit_job(self.state_path, "smoke", "smoke", "run", "h0")

    def test_unfinished_job_cannot_support_gate(self):
        state = self.init()
        with patch.object(study.executor, "request", return_value={"job_id": "baseline", "status": "running"}):
            study.submit_job(self.state_path, "baseline", "baseline", "run")
        study.add_evidence(self.state_path, self.evidence(state))
        state = study.run_gate(self.state_path, "S1")
        self.assertIn("not successfully completed", state["gates"]["S1"]["error"])

    def test_nonfinite_and_incomplete_success_are_not_accepted(self):
        self.init()
        response = self.response()
        response["result"]["metrics"]["score"] = float("nan")
        with patch.object(study.executor, "request", return_value=response):
            state = study.submit_job(self.state_path, "baseline", "baseline", "run")
        self.assertEqual(state["jobs"]["baseline"]["status"], "unknown")
        self.assertEqual(state["budget"]["reserved_seconds"], 5)
        response = self.response("missing-result")
        response.pop("result")
        with patch.object(study.executor, "request", return_value=response):
            state = study.submit_job(self.state_path, "missing-result", "baseline", "run")
        self.assertEqual(state["jobs"]["missing-result"]["status"], "unknown")

    def test_source_manifest_is_optional_local_tracking(self):
        self.config.pop("source_manifest")
        state = self.pass_s1()
        self.assertNotIn("source_manifest", state["config"])
        self.assertNotIn("result_sha256", state["jobs"]["baseline"])
        self.source.write_text("# Changed source is not tracked without an explicit manifest.\n")
        self.assertEqual(study.get_status(self.state_path)["gates"]["S1"]["status"], "passed")
        with patch.object(study.executor, "request", return_value=self.response("changed-source")) as request:
            state = study.submit_job(self.state_path, "changed-source", "baseline", "run")
        self.assertEqual(state["jobs"]["changed-source"]["status"], "succeeded")
        self.assertNotIn("input_manifest", request.call_args.args[1])

    def test_explicit_source_manifest_still_requires_valid_local_hashes(self):
        self.assertEqual(study.frozen_config(self.config | {"source_manifest": {}})["source_manifest"], {})
        for manifest in (None, [], {"experiment.py": "0" * 64}, {"../outside": "a" * 64}):
            with self.subTest(manifest=manifest), self.assertRaises(study.StudyError):
                study.frozen_config(self.config | {"source_manifest": manifest})

    def test_legacy_result_hash_metadata_does_not_invalidate_gate(self):
        state = self.pass_s1()
        gate = copy.deepcopy(state["gates"]["S1"])
        with study.Store(self.state_path) as store:
            state = store.load()
            state["jobs"]["baseline"]["result_sha256"] = "a" * 64
            state["jobs"]["baseline"]["external_notes"] = "keep"
            store.save(state, "legacy-metadata-fixture")
        for fields in ({"result_sha256": "b" * 64}, {}, {"result_sha256": None}):
            with self.subTest(fields=fields), patch.object(study.executor, "request",
                    return_value=self.responses["baseline"] | fields):
                state = study.reconcile_job(self.state_path, "baseline")
                self.assertEqual(state["gates"]["S1"], gate)
                self.assertEqual(state["gate_history"], [])
                self.assertEqual(state["jobs"]["baseline"]["external_notes"], "keep")
                self.assertEqual(state["budget"]["reserved_seconds"], 0)

    def test_gate_tracks_structured_result_content_and_ignores_serialization(self):
        state = self.pass_s1()
        gate = copy.deepcopy(state["gates"]["S1"])
        path = self.root / "jobs" / "baseline" / "result.json"
        path.write_text(json.dumps(state["jobs"]["baseline"]["result"], indent=4) + "\n")
        state = study.reconcile_job(self.state_path, "baseline")
        self.assertEqual(state["gates"]["S1"], gate)
        result = state["jobs"]["baseline"]["result"] | {"details": "changed"}
        path.write_text(json.dumps(result))
        state = study.reconcile_job(self.state_path, "baseline")
        self.assertEqual(state["jobs"]["baseline"]["status"], "succeeded")
        self.assertEqual(state["gates"]["S1"]["status"], "stale")
        self.assertEqual(state["gate_history"][-1], gate)

    def test_old_gate_fingerprint_becomes_stale_without_migrating_history(self):
        state = self.pass_s1()
        with study.Store(self.state_path) as store:
            state = store.load()
            state["jobs"]["baseline"]["result_sha256"] = "a" * 64
            state["gates"]["S1"]["input_fingerprint"] = study.digest({
                "version": state["version"], "evidence": state["evidence"]["S1"],
                "jobs": {"baseline": "a" * 64}, "validator": state["config"]["validator"]})
            state["external_notes"] = {"keep": True}
            original = store.save(state, "legacy-gate-fixture")
        changed = study.get_status(self.state_path)
        self.assertEqual(changed["gates"]["S1"]["status"], "stale")
        self.assertEqual(changed["gate_history"][-1], original["gates"]["S1"])
        for field in ("version", "jobs", "budget", "external_notes", "evidence_history", "history"):
            self.assertEqual(changed[field], original[field])
        rerun = study.run_gate(self.state_path, "S1")
        self.assertEqual(rerun["gates"]["S1"]["status"], "passed")
        self.assertNotEqual(rerun["gates"]["S1"]["input_fingerprint"], original["gates"]["S1"]["input_fingerprint"])

    def test_user_passed_flag_does_not_replace_validator_recomputation(self):
        self.init()
        state = self.baseline()
        evidence = self.evidence(state)
        study.add_evidence(self.state_path, evidence)
        raw = self.root / "jobs" / "baseline" / "result.json"
        raw.write_text(json.dumps({"metrics": {"score": 9}}))
        with patch.object(study.executor, "request", return_value=self.responses["baseline"]):
            state = study.run_gate(self.state_path, "S1")
        self.assertIn("recomputed metrics differ", state["gates"]["S1"]["error"])

    def test_prior_result_corruption_invalidates_completed_prerequisite(self):
        state = self.pass_s1()
        for kind in ("smoke", "screen", "confirm"):
            response = self.response(kind, score=2)
            with patch.object(study.executor, "request", return_value=response):
                study.submit_job(self.state_path, kind, kind, "run", "h0")
        evidence = {"stage": "S2", "version": state["version"], "artifacts": [str(self.artifact)],
                    "jobs": {kind: [kind] for kind in ("smoke", "screen", "confirm")},
                    "judgment": {"selection_used_development_only": True, "uncertainty_adequate": True,
                                 "assessment": "deterministic fixture"}}
        study.add_evidence(self.state_path, evidence)
        (self.root / "jobs" / "baseline" / "result.json").write_text("corrupted result")
        state = study.run_gate(self.state_path, "S2")
        self.assertEqual(state["jobs"]["baseline"]["status"], "unknown")
        self.assertEqual(state["gates"]["S1"]["status"], "stale")
        self.assertEqual(state["gates"]["S2"]["status"], "failed")
        self.assertEqual(state["stage"], "S1")

    def test_gate_on_finished_study_does_not_change_records(self):
        state = self.pass_s1()
        state = study.finish_study(self.state_path, "negative", "fixture end")
        with self.assertRaisesRegex(study.StudyError, "finished"):
            study.run_gate(self.state_path, "S1")
        self.assertEqual(study.get_status(self.state_path), state)
        with study.Store(self.state_path) as store:
            state = store.load()
            state["outcome"] = "completed"
            state["gates"]["S5"] = {"stage": "S5", "status": "passed"}
            store.save(state, "fixture-completion")
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(study.StudyError, "finished"):
            study.run_gate(self.state_path, "S5")
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_source_and_validator_drift_make_passed_gate_stale(self):
        for target in (self.source, self.validator):
            with self.subTest(target=target.name):
                if self.state_path.exists():
                    self.state_path.unlink()
                    self.state_path.with_name("state.json.events.jsonl").unlink()
                self.config["source_manifest"]["experiment.py"] = study.file_hash(self.source)
                state = self.pass_s1()
                old = target.read_text()
                target.write_text(old + "\n# changed\n")
                changed = study.get_status(self.state_path)
                self.assertEqual(changed["gates"]["S1"]["status"], "stale")
                self.assertEqual(changed["gate_history"][-1]["status"], "passed")
                self.assertEqual(changed["version"], state["version"])
                with self.assertRaisesRegex(study.StudyError, "frozen inputs"):
                    study.submit_job(self.state_path, "another", "baseline", "run")
                target.write_text(old)

    def test_prior_artifact_changes_invalidate_prerequisite(self):
        self.pass_s1()
        self.artifact.write_text("Changed diagnosis after signoff")
        state = study.get_status(self.state_path)
        self.assertEqual(state["gates"]["S1"]["status"], "stale")
        with self.assertRaisesRegex(study.StudyError, "prerequisite"):
            study.submit_job(self.state_path, "smoke", "smoke", "run", "h0")

    def test_revision_retains_old_jobs_evidence_and_spent_budget(self):
        state = self.pass_s1()
        self.config["protocol"]["objective"] = "Revised objective"
        revised = study.revise_study(self.state_path, self.config, "predeclared protocol change")
        self.assertNotEqual(state["version"], revised["version"])
        self.assertEqual(revised["gates"]["S1"]["status"], "stale")
        self.assertEqual(revised["jobs"]["baseline"]["version"], state["version"])
        self.assertEqual(revised["budget"]["used_seconds"], 0.1)
        self.assertEqual(len(revised["evidence_history"]), 1)
        with self.assertRaisesRegex(study.StudyError, "evidence version"):
            study.add_evidence(self.state_path, self.evidence(state))
        evidence = self.evidence(revised)
        study.add_evidence(self.state_path, evidence)
        gated = study.run_gate(self.state_path, "S1")
        self.assertIn("job version mismatch", gated["gates"]["S1"]["error"])

    def test_actual_overrun_blocks_gate(self):
        self.config["budget"]["total_resource_seconds"] = 5
        state = self.init()
        with patch.object(study.executor, "request", return_value=self.response(elapsed=5.1)):
            study.submit_job(self.state_path, "baseline", "baseline", "run")
        study.add_evidence(self.state_path, self.evidence(state))
        gated = study.run_gate(self.state_path, "S1")
        self.assertIn("resource budget", gated["gates"]["S1"]["error"])

    def test_independent_reviews_cannot_be_self_reviews(self):
        state = self.init()
        evidence = {"jobs": {}, "judgment": {"reviews": [{"reviewer": "author", "independent": True, "critiques": []}]}}
        with self.assertRaisesRegex(study.StudyError, "independent"):
            study.check_judgment(state, "S4", evidence)
        evidence = {"jobs": {}, "judgment": {"audits": {name: {"reviewer": "author", "independent": True}
                                                              for name in study.REQUIRED_CHECKS["S5"]}}}
        with self.assertRaisesRegex(study.StudyError, "independent"):
            study.check_judgment(state, "S5", evidence)

    def test_fatal_empirical_critique_requires_new_experiment_or_withdrawal(self):
        state = self.init()
        critique = {"id": "c1", "severity": "fatal", "empirical": True, "closed": True,
                    "closure_reviewer": "peer", "rationale": "fixture", "resolution": "clarified"}
        evidence = {"jobs": {"rebuttal": ["r1"]}, "judgment": {
            "reviews": [{"reviewer": "peer", "independent": True, "critiques": [critique]}]}}
        with self.assertRaisesRegex(study.StudyError, "experiment or withdrawal"):
            study.check_judgment(state, "S4", evidence)
        critique["resolution"] = "experiment"
        critique["response_jobs"] = []
        with self.assertRaisesRegex(study.StudyError, "response experiments"):
            study.check_judgment(state, "S4", evidence)

    def test_training_semantics_requires_matched_retraining(self):
        state = self.init()
        evidence = {"jobs": {"ablation": ["a1"]}, "judgment": {"simplification": "fixture",
            "components": [{"name": "training component", "kind": "scientific", "retained": True,
                            "support_jobs": ["a1"], "training_semantics": True, "matched_retraining": False}]}}
        with self.assertRaisesRegex(study.StudyError, "matched_retraining"):
            study.check_judgment(state, "S3", evidence)

    def test_threshold_and_guardrail_checks_are_mechanical(self):
        state = self.pass_s1()
        state["jobs"]["winner"] = {"result": {"metrics": {"score": 1.5}}}
        with self.assertRaisesRegex(study.StudyError, "minimum practical"):
            study.metric_thresholds(state, ["winner"])
        state["jobs"]["winner"]["result"]["metrics"]["score"] = 2
        state["config"]["protocol"]["guardrails"] = [{"metric": "score", "operator": "<=", "value": 1.9}]
        with self.assertRaisesRegex(study.StudyError, "guardrail failed"):
            study.metric_thresholds(state, ["winner"])


if __name__ == "__main__":
    unittest.main()
