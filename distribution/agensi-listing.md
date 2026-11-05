# Agensi listing copy

**Title:** Scientist Two — Research Planning & Evidence Review

**Short description:** Free research planning guide with frozen protocols, finite experiment budgets, S1–S5 evidence requirements, and independent review. Optional execution uses a separately installed runtime on your existing authorized environment.

**Description:** Plan hypothesis tests, screening and confirmation, ablations, experimental rebuttals, and final integrity audits. The companion can deliver a protocol, bounded experiment plan, evidence ledger, and review package without installing code. Proposed experiments are marked not executed and unverified gates remain pending.

For real jobs and machine-checked workflow gates, use the independent public Scientist Two runtime on existing authorized macOS/Linux compute with Python 3.10+ and persistent POSIX storage/process support. This instruction-only package does not supply a terminal, GPU, hosted compute, or runtime. Environment compatibility must be checked where work will run. No research performance claim is made; demonstration metrics and reviewers are synthetic fixtures.

**Price/license:** Free; MIT. Independent and unofficial, with no affiliation with or endorsement by the ScientistTwo authors.

**Source and installation:** https://github.com/doubaoclaude-dotcom/scientist-two-skill

**Documentation:** https://github.com/doubaoclaude-dotcom/scientist-two-skill/blob/main/README.md

**Compatibility note:** Planning and evidence review work with agents that can read the skill, including Codex and Claude Code. Optional execution needs a separately obtained runtime, Python 3.10+ on macOS/Linux, terminal access, persistent POSIX storage and worker support. Reuse existing project, venv or conda environments. SSH uses an already configured host. Existing WSL2/containers need environment checks; native Windows is unsupported.

**Categories:** Research & Analysis (primary); Agents & Orchestration; Education & Learning.

**Tags:** research, scientific-method, evidence, reproducibility, experiment-design, ablation, codex, claude-code, open-source, python.

**Use cases:** Plan a bounded hypothesis test; separate tuning from final evaluation; design ablations; prepare an independent review package; audit whether claims have supporting evidence; coordinate optional jobs on existing local or SSH compute.

**Permissions:** Planning needs only the information the user supplies. Optional execution reads approved project/data files, writes research state and job outputs, and runs commands in the user's authorized environment. Optional SSH or public-source setup needs network access. No telemetry, credentials, hosted compute, or paid service is supplied by this package.

**Limitations:** Plans are not measurements. Without execution, gates remain pending. Independent review must be real; reviewer identities are not authenticated by the runtime. The package is not a security sandbox, autonomous scheduler, or guarantee of scientific improvement. Agensi does not supply the optional execution environment.

## See it in action

The following planning-only test request was actually processed using the companion. No dataset, terminal, or measured result was provided; this is an example of planning output, not a research result.

**Request:** I want to test whether a reranker improves a small document-search system. I have 200 labeled queries and a current BM25 baseline. I can use my existing laptop later, but this chat has no terminal and you do not have my dataset or measured baseline results. Please prepare a bounded experiment plan with a maximum of 12 runs and 30 minutes per run. Keep final evaluation separate from tuning, specify what evidence I should collect, and tell me what is still needed before execution.

**Result:**

**Protocol draft — not executed; gates pending.**

Question: Does a frozen reranker improve BM25 search quality enough to justify its latency?

Before S1, freeze corpus, labels, query split, code/config/model hashes, evaluator, hardware, seeds and stopping rules. Group duplicate or related queries; allocate about 140 to development and 60 to sealed final evaluation. If any queries informed earlier tuning, they cannot be untouched test data.

Primary metric: nDCG@10, higher is better. Proposed success rule: final paired-query bootstrap 95% CI for the improvement excludes zero, point gain ≥0.02, and p95 end-to-end latency ≤2× BM25. Agree these thresholds before execution; the small test set may yield an inconclusive result.

**Budget: ≤12 runs, each ≤30 wall-minutes; ≤360 run-minutes total.** Failures and retries count. Stop at either cap; do not inspect test results to tune.

1. **S1, run 1:** Smoke-check labels, rankings and evaluator; measure matched BM25 on development and diagnose errors.
2. **S2, runs 2–4:** Screen one fixed pretrained reranker at BM25 candidate depths 20, 50 and 100. Predictions: reranking improves ordering; deeper pools help when relevant documents fall outside shallow pools, at higher latency.
3. **S2–S3, runs 5–7:** Confirm the development winner, compare its identical candidate pool without reranking, then reevaluate the simplest retained version.
4. **S4, runs 8–10 reserved:** Give an independent reviewer the protocol and development evidence; use these runs only for objections. Freeze the final choice.
5. **S5, runs 11–12:** Evaluate matched BM25 and the frozen winner once on sealed queries; audit results and provenance.

Collect per-query scores, ranked IDs, latency, logs, versions, resource use, failures, uncertainty and a run ledger. Map claims to code/config/tests; preserve reviewer critique and audit scope.

Needed: dataset, corpus, label scheme, split history, model choice, runnable laptop environment and reviewer. No measurements or environment checks were performed; all gates remain pending.

**中文简介：** 免费、MIT 开源的独立非官方科研规划与证据审阅指南，覆盖冻结协议、有限预算、S1–S5 证据要求、独立审查和研究诚信检查。无需安装即可完成规划和审阅；真实实验与机器门控可选用另行获取的公开 runtime，在已有授权环境中执行。未执行的实验明确标注 not executed，未验证门控保持 gates pending。此包不提供终端、GPU 或托管算力，不宣称复现论文科研成绩。

**Upload artifact:** Build the instruction-only ZIP using the README command. It contains only `SKILL.md` (from `distribution/agensi.md`) and `LICENSE`; do not upload the repository runtime as part of this package.
