# State, evidence, and five-stage workflow

This is an independent workflow adaptation, not the ScientistTwo paper's exact six-module implementation. The host agent or researcher reasons about the science; `scripts/study.py` records state, calls executors, and enforces explicit process checks. The five-stage demo is a software fixture. Its reviewer names and judgments are synthetic, and completing it is not a real independent scientific review.

## Controller commands

Run commands from the installed skill directory. Use an explicit state path for every invocation:

```sh
python3 scripts/study.py --state /absolute/study/state.json init --config /absolute/study/config.json
python3 scripts/study.py --state /absolute/study/state.json submit --job-id baseline-01 --kind baseline --command baseline
python3 scripts/study.py --state /absolute/study/state.json reconcile --job-id baseline-01
python3 scripts/study.py --state /absolute/study/state.json status
python3 scripts/study.py --state /absolute/study/state.json evidence --file /absolute/study/s1.json
python3 scripts/study.py --state /absolute/study/state.json gate --stage S1
python3 scripts/study.py --state /absolute/study/state.json submit --job-id h1-smoke-01 --kind smoke --command smoke --candidate h1
python3 scripts/study.py --state /absolute/study/state.json review-package --output /absolute/study/review-package.json
python3 scripts/study.py --state /absolute/study/state.json revise --config /absolute/study/revised-config.json --reason 'Predeclared protocol correction'
python3 scripts/study.py --state /absolute/study/state.json finish --outcome inconclusive --reason 'Insufficient uncertainty evidence'
```

`--expected-revision N`, before the subcommand, rejects outdated writes. Gate refusal returns exit code 1 with the recorded gate state; invalid commands return exit code 2 with JSON on stderr. Successful commands return JSON on stdout. Do not edit the snapshot directly: its full contents are checked against the event log.

The equivalent Python API accepts `str` or `Path` state paths:

```python
import study  # Add this skill's scripts directory to sys.path.

state = study.init_study(state_path, config)
state = study.submit_job(state_path, "baseline-01", "baseline", "baseline")
state = study.reconcile_job(state_path, "baseline-01")
state = study.add_evidence(state_path, evidence)
state = study.run_gate(state_path, "S1")
```

Additional functions are `get_status`, `revise_study(state_path, config, reason)`, `finish_study(state_path, outcome, reason)`, and `review_package(state_path, output)`. Submission, reconciliation, evidence, gate, revision, and finish functions accept `expected_revision`. The runnable [demo](../examples/demo.py) constructs the complete configuration and evidence for all five stages.

## Freeze before S1

The initialization configuration requires these fields:

| Field | Meaning |
| --- | --- |
| `study_id`, `author` | Stable study identifier and author identity declaration. |
| `source_root` | Absolute controller-side directory containing the declared source files. |
| `source_manifest` | Nonempty object mapping normalized relative file paths to lowercase SHA-256 hashes. No `..`, absolute paths, or `.git` entries. |
| `identities.data`, `identities.evaluator` | Frozen data and evaluator identity descriptions or hashes; the project validator must verify their actual use. |
| `protocol.objective`, `protocol.baseline` | Research target and baseline definition. |
| `protocol.data_split` | Nonempty `development`, `confirmation`, and `final` split descriptions. |
| `protocol.metric` | `{name, direction: "maximize" or "minimize", min_improvement: nonnegative finite number}`. |
| `protocol.statistical_rule` | Prespecified uncertainty/statistical decision rule, implemented by the project validator. |
| `protocol.guardrails` | Explicit list, possibly empty, of `{metric, operator: "<=" or ">=", value: finite number}`. |
| `protocol.stop_conditions` | Nonempty list of prespecified stop conditions. The host interprets scientific conditions; resource limits are enforced mechanically. |
| `protocol.hypothesis_count` | Positive integer, default 3. |
| `budget` | Positive `max_jobs`, `max_iterations`, `per_job_seconds`, `total_resource_seconds`. The first two are integers. |
| `executor` | `local`, `ssh`, or `custom` configuration from the [executor contract](executor-contract.md). |
| `execution` | Absolute execution-host `cwd` and persistent `job_root`. |
| `commands` | Nonempty object mapping names to argument arrays. Submission chooses a frozen name; no shell command interpolation. |
| `validator` | `{argv: [...], files: [absolute implementation paths], timeout_seconds: 30}`. Timeout is optional and at most 300 seconds. |

All configuration is stored in state and contributes to the version fingerprint. Initialization also hashes validator files, its executable, and existing file arguments. Changes to a declared source/validator file invalidate previous gates. Configuration edits take effect only through `revise`; an external configuration file is not a second state source.

Declare all scientific source and evaluator implementation files. For large external datasets or pretrained weights, use an explicit immutable manifest and have the validator check it against the actual data/weights. A text identity description alone does not prove which bytes an experiment used. The core does not discover transitive imports, hash entire environments, copy datasets, or prove an undeclared dependency is unchanged. Include relevant configuration/manifest files explicitly and extend the project validator as needed.

For SSH, `source_root` is the controller's prepared copy, while `execution.cwd` is the separately deployed remote copy. The same relative-path SHA-256 manifest is checked on the execution host before starting. The controller's Git commit is not remote execution evidence. Configuration must not contain secrets; use existing SSH identities or environment-injected adapter authentication.

## State and budgets

The snapshot contains schema/study/revision, the frozen `config` and content-derived `version`, `protocol_revision`, current `stage`, candidates, next action, blockers, jobs, current evidence, gate records, evidence/gate history, and all previous frozen configurations. Existing unrelated top-level fields survive initialization and later writes. Conflicting study fields are rejected.

Each job records its stable ID, kind, command, candidate, version, original backend and request, execution state, result/hash/path, reserved budget, and actual charge. Job IDs remain permanently occupied, including failed and unknown jobs. To retain rejected directions or negative observations, record them in evidence artifacts/judgment fields; failed, OOM, timeout, missing-result, and no-gain jobs remain in the ledger.

The bundled unit is **elapsed job wall-seconds**, not CPU-seconds, GPU-seconds, GPU-hours, or a claim of hardware utilization. Every submission consumes one job and one iteration, and reserves its entire `per_job_seconds` allowance before calling the executor. A terminal collection releases the reservation and charges actual elapsed seconds. A terminal failure with unavailable elapsed time conservatively charges the full timeout. Unknown jobs retain reservations; a previously terminal job whose integrity becomes unknown conservatively reserves a timeout again without refunding prior work.

Total used plus reserved seconds must fit the frozen limit. Validation rejects a gate if actual runtime exceeds the total budget, including small timeout/cleanup overruns; leave reasonable headroom. Revisions do not reset job counts or spent/reserved resources. The controller does not cancel other jobs or assume a disconnected task stopped.

Legal nonpositive outcomes are `negative`, `inconclusive`, and `budget_exhausted`. `finish` stops new submissions while allowing existing job reconciliation. S5 success sets `outcome: "completed"`; this means the recorded workflow checks passed, not that the scientific result is positive or established. A gate call on a finished study is rejected without changing its records. An explicit revision can reopen it.

## Recovery and concurrency

Keep `state.json`, `state.json.events.jsonl`, and `state.json.lock` together. The lock uses POSIX `flock`; a single write transaction holds it across state mutation and external submission/validation. Each update appends and fsyncs a complete recoverable state event, then atomically replaces and fsyncs the snapshot. Revision and snapshot/event hash checks prevent lost updates and silent direct snapshot edits.

If a process stops after the event is durable but before the snapshot replacement, the next command restores the full latest state, including job identity and reservations. An incomplete final event line is discarded. A complete corrupt event or divergent snapshot is reported rather than guessed around. Preserve the event log; it is not an optional debug log. Logs contain full states and grow with the study; there is no automatic compaction.

Submission intent is durable before network/process invocation. If that invocation times out, returns illegal JSON, or disconnects, the job is `unknown`. Even a crash leaving `preparing` is reconciled under the same job ID. Use `reconcile`, which calls `collect` on the stored backend and job root; never submit a new ID merely because an old one is unknown. No resubmission or budget refund is automatic. The host must investigate an adapter/host that cannot establish the task's actual state.

There is no daemon, scheduler, or host-agent wakeup service. Detached experiment processes can continue, but state files do not cause an agent conversation to resume. Durable filesystem rename/fsync/flock semantics are required; unusual network filesystems are outside the tested assumptions.

## Evidence and gates

An evidence submission has this common envelope:

```json
{
  "stage": "S1",
  "version": "copy the exact state.version fingerprint",
  "artifacts": ["/absolute/study/diagnosis-and-hypotheses.md"],
  "jobs": {"baseline": ["baseline-01"]},
  "judgment": {}
}
```

The controller hashes actual artifact files on submission. It stores their paths/hashes, the supplied judgment, a content fingerprint, and a history record. Evidence from another version is rejected. Replacing evidence makes that stage and later signed-off gates stale. Changing a prior signed-off artifact also makes the earliest affected gate and later gates stale on status, submission, or gate checks.

Each gate checks all prerequisites; current version; evidence artifacts; successfully completed jobs, exits, and result hashes; finite metrics; budget; the frozen validator; and required scientific judgment fields. It recollects jobs supporting the current and all preceding gates, so a prior result that has disappeared or become corrupt cannot silently support later stages. A remote host/adapter must be available for this freshness check.

| Stage | Required job kinds | Required validator checks | Required judgments |
| --- | --- | --- | --- |
| S1 | `baseline` (exactly one) | `baseline` | Diagnosis; the configured number of testable hypotheses; unchanged evaluation protocol. |
| S2 | `smoke`, `screen`, `confirm` (exactly one winner) | `smoke`, `uncertainty` | Selection used development evidence only; sufficient uncertainty evidence; assessment. The winner must have smoke and screen evidence. |
| S3 | `ablation`, `retest` | `ablation`, `uncertainty` | Simplification and component/interaction accounting; retained scientific components/groups supported by ablations; matched retraining when training semantics change. |
| S4 | `rebuttal` | `rebuttal` | Independent critiques; fatal empirical questions answered by new experiment or withdrawn claim, with independent closure. |
| S5 | `final` | `numerical`, `protocol`, `citations`, `code` | Four independent audit declarations for the same version, explicit reproduction scope, zero unresolved fatal findings. All study jobs must be terminal. |

S2 confirmation, S3 simplified retest, and S5 final metrics must meet the frozen improvement over the S1 baseline and all guardrails. Validator metric requests include the baseline for these stages. Non-baseline jobs require a candidate ID from S1. After S2, new jobs must use the selected candidate. Job kinds enforce stage prerequisites, including delaying final-test jobs until S4 passes.

The controller records a judgment about development-only selection; it cannot observe undocumented experiments. Never use final-test data to select hypotheses, seeds, checkpoints, or hyperparameters. Data already used for selection is development evidence. A project validator should enforce split identities, prespecified seed counts, uncertainty calculations, stopping rules, and any confirmatory-test discipline required by the study.

Judgment details:

- **S1:** `diagnosis`, `evaluation_protocol_unchanged: true`, and `hypotheses: [{id, prediction, change_boundary, falsification}, ...]`.
- **S2:** `selection_used_development_only: true`, `uncertainty_adequate: true`, and `assessment`.
- **S3:** `simplification` and `components: [{name, kind, retained, support_jobs, training_semantics, matched_retraining}, ...]`. Kinds are `scientific`, `interaction_group`, or `infrastructure`. Interacting components may be justified together; infrastructure/correctness code need not independently improve the score. Retained scientific groups need ablation job references; training-semantic changes need matched retraining.
- **S4:** `reviews: [{reviewer, independent: true, critiques: [...]}]`. Each critique has `id`, `severity` (`fatal`, `major`, or `minor`), `empirical`, and `rationale`. Fatal critiques additionally require `closed: true`, a `closure_reviewer` among the independent reviewers, and `resolution`. Empirical fatal critiques permit `experiment` with nonempty `response_jobs` from rebuttal evidence, or `withdrawn`; text-only clarification is insufficient.
- **S5:** `audits` has `numerical`, `protocol`, `citations`, and `code` entries. Each has `reviewer`, `independent: true`, nonempty `scope` and `statement`, `fatal_open: 0`, and `approved: true`. Record numerical scope distinctly as log/table alignment, reevaluation, or matched retraining. The reviewer judges whether each scope suffices.

Reviewer identity must differ from the author, but a different string does not authenticate a human or independent agent context. If an independent reviewer is unavailable, export a review package and end inconclusively rather than inventing a reviewer. The package contains local artifact references and state; transfer the referenced artifacts explicitly if another machine needs them. Internal review is not conference acceptance.

For citation review, save source identity and the exact passage/section supporting each claim; existence of a paper alone is insufficient. For code/body review, retain bidirectional claim/formula/module → code symbol → configuration → test/experiment mappings and reverse coverage. Line matching is not proof of semantic equivalence. These artifacts and project-specific integrity validators supply the evidence behind S5's named checks.

## Frozen validator contract

The controller runs the frozen argument array in `source_root`, with JSON stdin and bounded JSON stdout. The request is:

```json
{
  "stage": "S2",
  "version": "frozen version fingerprint",
  "protocol": {"...": "the frozen protocol"},
  "source_root": "/absolute/prepared/source",
  "jobs": {"job-id": {"result": {"metrics": {}}, "job_dir": "/absolute/job", "...": "recorded job metadata"}},
  "evidence": {"...": "the submitted evidence with actual artifact hashes"}
}
```

Output must be one JSON object, no log text:

```json
{
  "checks": {"smoke": true, "uncertainty": true},
  "metrics": {"job-id": {"score": 0.75}}
}
```

Return freshly recomputed metrics for **every** requested job, including injected baseline jobs; they must exactly equal the collected metric values. Use a specified deterministic rounding/serialization policy when necessary. Nonzero exit, timeout, output over 1 MiB, missing checks, nonfinite metrics, or mismatched values fail the gate. Logs belong on stderr. The gate records the actual command, implementation hashes, exit code, output hash and values separately from reviewer judgments.

The [example validator](../examples/validator.py) independently checks raw arithmetic observations rather than trusting result summaries. For a real study, implement checks from raw predictions/logs/data and inspect integrity artifacts, not just `return True`. A user-supplied `passed: true` evidence field is ignored. The controller proves that the frozen program ran and returned checks; it cannot prove the program's scientific correctness, novelty, causality, statistical adequacy, or arbitrary code semantics.

A validator runs on the controller. For remote/custom jobs, make the needed raw artifacts readable there through an explicit authorized collection step/shared storage, or let the frozen validator perform authorized remote verification. The core's JSON `collect` response does not silently download arbitrary raw datasets.

This is a process guardrail under ordinary filesystem permissions. An actor with arbitrary shell/write access can alter code, validators, artifacts, and state logs together. It is not a security sandbox, an immutable attestation service, or a substitute for independent scientific review.
