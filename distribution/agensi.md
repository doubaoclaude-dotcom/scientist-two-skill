---
name: scientist-two
description: Plan evidence-driven research with frozen protocols, finite budgets, five-stage evidence requirements, and independent review. Use for hypotheses, ablations, experimental rebuttals, or integrity audits; optionally execute through a separately obtained Scientist Two runtime on existing authorized compute.
---

# Scientist Two — research companion

This free, MIT-licensed companion is an independent, unofficial adaptation of ScientistTwo. It provides research planning, protocol freezing, S1–S5 evidence requirements, and review guidance without installing code. It does not reproduce the paper's research performance.

Public runtime and documentation: [GitHub](https://github.com/doubaoclaude-dotcom/scientist-two-skill), [installation and demos](https://github.com/doubaoclaude-dotcom/scientist-two-skill/blob/main/README.md), [中文说明](https://github.com/doubaoclaude-dotcom/scientist-two-skill/blob/main/README.zh-CN.md), [workflow/evidence schema](https://github.com/doubaoclaude-dotcom/scientist-two-skill/blob/main/references/workflow.md), [executor contract](https://github.com/doubaoclaude-dotcom/scientist-two-skill/blob/main/references/executor-contract.md), [sources](https://github.com/doubaoclaude-dotcom/scientist-two-skill/blob/main/references/sources.md), [MIT license](https://github.com/doubaoclaude-dotcom/scientist-two-skill/blob/main/LICENSE).

## Choose the available workflow

Start with the user's requested research question and available artifacts. Planning and evidence review are useful complete deliverables on their own: produce a frozen protocol draft, bounded experiment plan, evidence ledger, and review package as appropriate. Clearly label proposed experiments **not executed** and unverified stage gates **gates pending**. A plan, a plausible number, or a model-written `passed=true` is not execution evidence or a machine gate result. Do not invent observations, job IDs, citations, reviewer identities, or approvals.

Optional real execution requires a separately obtained public Scientist Two runtime and an authorized command-capable environment. This package contains instructions and a license only; it provides no terminal, GPU, hosted compute, or persistent worker. Agensi's per-script temporary execution does not establish support for the runtime's cross-file imports, persistent storage, or detached workers. Do not reconstruct a runtime by saving/exporting Agensi content, or present these instructions as executable runtime code.

Prefer the environment the user specifies, then an existing authorized project environment, venv, conda environment, or `python3` with Python 3.10+ on macOS/Linux. Reuse an existing WSL2 or container only after checking Python, POSIX locking/atomic replacement, writable persistent storage, and process-group/detached-worker support; native Windows is unsupported. Do not claim an environment is validated without actually testing it. The runtime uses the Python standard library and requires no pip dependencies.

When runtime files are missing, point to the installation documentation. If installing is already authorized for the task and the host permits it, use a separate checkout of the public repository into a new destination. Never automatically pull over an existing checkout, overwrite user files, or delete a working directory. Resolve runtime scripts relative to that checkout and follow its own SKILL.md and linked contracts; do not infer that scripts are bundled here.

Use local execution first when appropriate. SSH may reuse an already configured host alias, credentials, and host-key trust; do not acquire paid compute, create credentials, change host-key checking, or transfer data without the required authorization. The controller needs its own accessible runtime and state files; an SSH executor needs the deployed executor, prepared source, Python, and persistent job directory on its host. A runtime on one side does not make it available on the other. Remote result JSON does not imply local access to raw artifacts: explicitly collect allowlisted files for a local validator, or use an authorized remote-aware validator. Do not upload a whole working tree by default.

## Freeze before experimenting

Record the research goal, matched baseline, source/configuration/data/evaluator identities, data splits, primary metric and direction, minimum practical improvement, statistical decision rule, guardrails, finite job/iteration/time budgets, per-job limits, and stopping conditions. Freeze the protocol before S1; reuse it for every comparison. Record any revision explicitly and invalidate affected prior evidence for the new version.

Keep development/selection data separate from final testing. A test set used to select hypotheses, seeds, checkpoints, or hyperparameters becomes development evidence and cannot serve as untouched confirmation. A prior baseline is acceptable only with matching provenance. Do not relax criteria after seeing results to manufacture a positive finding.

## Five stages and required evidence

1. **S1 — Diagnose and hypothesize.** Establish the matched baseline, diagnose its bottleneck, and propose three candidates by default, adjusting to the agreed scope. Give each a falsifiable prediction and bounded change under the frozen protocol.
2. **S2 — Screen and confirm.** Require smoke results, development-only screening, and full confirmation of selected candidates. Record uncertainty, guardrails, resource use, failed runs, OOMs, null results, and early stops. Claims must match actual completed experiments.
3. **S3 — Ablate and simplify.** Test retained scientific components and interacting groups, simplify, then reevaluate the final version. Training-semantic changes require matched retraining; inference toggles alone do not establish their contribution. Infrastructure and correctness code need not improve a metric in isolation.
4. **S4 — Review and rebut experimentally.** Obtain an independent context or human reviewer and preserve their actual critique. Address fatal empirical objections through new experiments or withdraw the affected claims and rereview. Without an independent reviewer, export a review package and leave the gate pending. Never reuse a demo's synthetic reviewer declarations as real review.
5. **S5 — Audit the same final version.** Require numerical/reproducibility, protocol, citation, and code-mapping audits with no unresolved fatal issue. Trace claims/formulas/modules to code symbols, configuration, and tests/experiments in both directions. Record the scope and reviewer for each audit.

For each stage, identify the version, artifacts, job IDs where execution occurred, observed outcomes, reviewer judgments, unresolved issues, and gate status. Distinguish log/table consistency checks, reevaluation, and retraining. Cite the precise source location supporting a claim; a real citation or a mapped code line is not proof of scientific or semantic correctness. Passed gates do not prove novelty, causality, or acceptance.

## Execution and recovery discipline

When using the separate runtime, follow its documented controller and evidence schema rather than inventing substitute gate logic. Use one controller and explicit state path per study. Reserve the finite budget and persist submission intent before work starts. Budget units are elapsed job wall-seconds, not CPU-seconds or GPU-hours. Stop new submissions when exhausted, allowing existing jobs only their agreed limits.

Assign a stable job ID before submission. A timeout or disconnect can leave a job `unknown`; inspect status and reconcile that same ID before any retry. Never blindly resubmit under a fresh ID. Preserve reservations until reconciliation, failed/negative results, logs, and earlier evidence. Use isolated work directories or branches without destructive resets or killing unrelated processes. State files do not wake a sleeping agent or provide an autonomous research scheduler.

Separate runtime-verified facts from named reviewers' scientific judgments and manual document review. The runtime's records and declared reviewer independence are not tamper-proof or authenticated; arbitrary write access can change them. If no runtime was run, report **not executed; gates pending**, alongside the completed planning or review deliverables. If execution occurred, report only checks actually performed, unresolved review, remaining budget, and artifact locations accessible to the recipient. Negative, inconclusive, and budget-exhausted outcomes are valid conclusions.
