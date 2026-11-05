---
name: scientist-two
description: Run evidence-driven research studies with frozen evaluation protocols, finite experiment budgets, five stage gates, and recoverable local, SSH, or custom jobs. Use for hypothesis testing, ablations, experimental rebuttals, and research integrity audits.
---

# Scientist Two

Use the host agent for research reasoning and the bundled Python scripts for durable experiment records. This is an independent adaptation, not an official ScientistTwo implementation or a reproduction of its research results.

Resolve scripts relative to this skill directory. Read [workflow.md](references/workflow.md) for the controller commands, evidence schema, and gate checks. Read [executor-contract.md](references/executor-contract.md) when configuring compute or recovering a job. See the [English README](README.md) or [中文说明](README.zh-CN.md) for installation and the CPU demonstration. [Sources](references/sources.md) records provenance and attribution.

## Before experiments

Agree on the research goal, baseline, data splits, evaluator, primary metric direction, minimum practical improvement, statistical decision rule, guardrails, resource limits, and stopping conditions. Freeze the protocol and file identities before S1. Validate a baseline with the same protocol or explicitly establish a prior result's matching provenance.

Choose local, SSH, or custom execution using existing authorized compute. An installed skill does not authorize paid compute, external publication, new credentials, or data transfers. Source preparation is an explicit allowlisted step; remote source hashes must be verified on the execution host. Never upload a whole working tree by default.

## Research cycle

1. **S1 — Diagnose and hypothesize.** Diagnose the bottleneck; propose three candidates by default (configurable), with falsifiable predictions and bounded changes under the same evaluation protocol.
2. **S2 — Screen and confirm.** Run smoke tests, a fixed development subset, and full confirmation of selected candidates. Use the frozen metric, uncertainty, guardrail, and budget rules. Preserve failures, OOMs, null results, and early stops.
3. **S3 — Ablate and simplify.** Test components and interacting groups. Infrastructure and correctness code need not improve a metric alone. Retrain matched ablations for training-semantic changes; inference toggles alone do not establish their contribution. Reevaluate the simplified final version.
4. **S4 — Review and rebut experimentally.** Request an independent context or human reviewer; respond to fatal empirical objections with new experiments, or withdraw the claims and rereview. If no independent reviewer is available, export a review package and leave the gate pending.
5. **S5 — Audit the final version.** Check numbers/reproducibility, protocol compliance, citations, and bidirectional claim/formula/module → code symbol → configuration → test/experiment mapping. All required evidence must describe the same final version, with no unresolved fatal issue.

The five stages are this product's adaptation. Do not imply that a passed gate proves novelty, causality, semantic correctness, or conference acceptance. Separate script-verified facts from named reviewers' scientific judgments. A model-written `passed=true` is not an integrity audit.

## Evidence discipline

- Keep selection data separate from final testing. A test set used to select hypotheses, seeds, checkpoints, or hyperparameters becomes development evidence; it cannot serve as untouched confirmation.
- Record source, configuration, data, evaluator, protocol, job, and artifact identities. After changes, stale evidence remains history but cannot support new-version gates.
- Distinguish log/table consistency, reevaluation, and retraining. State exactly which scope was performed.
- A real citation is not necessarily supporting evidence: record its exact supporting location and the claim it supports. Mapping code lines is not a semantic proof.
- Finish honestly with negative, inconclusive, or budget-exhausted outcomes when appropriate. Do not relax criteria to manufacture a positive result.

## Recovery and stop rules

Use one controller and one explicit state path per study. Reserve budget and persist submission intent before starting work. A disconnect or timeout can leave a job `unknown`; reconcile the same stable ID, never blindly resubmit it. Stop new submissions when the budget is exhausted; let existing jobs finish within their own limits. Do not kill unrelated processes or discard failed code. Use isolated work directories or branches, without destructive Git resets.

The state files do not wake a sleeping agent or create a background research loop. A process with arbitrary write access can alter records: gates prevent workflow mistakes, not hostile tampering. Keep the user informed of actual validation, unresolved review, and remaining budget.
