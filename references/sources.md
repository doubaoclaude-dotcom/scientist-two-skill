# Sources and attribution

Verified 2026-11-05. This note records factual source checks for the skill; it does not reproduce source prompts or code.

## ScientistTwo paper

- [arXiv abstract](https://arxiv.org/abs/2609.19644) and [v1 HTML paper](https://arxiv.org/html/2609.19644v1), Jaehyun Nam et al., submitted 2026-09-17. arXiv identifies the paper as v1 and provides the full text.
- The paper describes a multi-agent workflow covering seed-idea generation, subset-to-full-set evaluation, idea refinement, ablation studies, manuscript drafting with simulated peer review, and meta-review/refinement (sections 3.1–3.6).
- Main result: 86 of 107 benchmark problems advanced (80.4%), with average relative gain of 25.2% over human SOTA baselines (abstract, §4.1). Attribute this only to their evaluated set and setup; it is not a general success guarantee.
- Integrity scope: four checks—score reproducibility, specification compliance, reference verification, and method-code alignment (§4.2, Table 7). Their ScientistTwo row reports 49/49 score verification, 0/49 spec violations, 0 hallucinated references out of 1814, and 49/49 method-code alignment. These are reported benchmark audit counts, not a universal guarantee. The paper says search-augmented reference checking and code-to-manuscript audit/refinement are used.
- Limitations/scope: reported results concern benchmarked research tasks, including target challenges drawn from ICLR/ICML/NeurIPS papers; the abstract's broad claims should be contextualized by these evaluations. The paper reports primary coding work using Claude Code/Opus 4.8 and only a five-task backend generalization check (§4.2).
- Rights: arXiv displays **CC BY 4.0**. Cite/attribute the authors and paper; do not imply the source workflow or text is proprietary to this skill.

## Related autoresearch projects (distinct licenses and scope)

- [karpathy/autoresearch](https://github.com/karpathy/autoresearch), [program.md](https://github.com/karpathy/autoresearch/blob/master/program.md) (checked 2026-11-05). The repo README states MIT. The program configures experiments on nanochat training, one GPU, a fixed five-minute training budget, edits to `train.py` only, a `val_bpb` objective, and a keep/discard results loop. Credit Andrej Karpathy and describe it as the source of the constrained iterative experiment pattern; it is not a general scientific-paper workflow. README's MIT statement is the visible license evidence; no separate root LICENSE file was located at the checked `master` raw URL.
- [olelehmann1337/autoresearch-skill](https://github.com/olelehmann1337/autoresearch-skill), [`SKILL.md`](https://raw.githubusercontent.com/olelehmann1337/autoresearch-skill/main/SKILL.md) (checked 2026-11-05). This is a Claude Code skill for iteratively evaluating and mutating a skill prompt against binary evals, with baseline and experiment logs. It says it adapts Karpathy's methodology. GitHub page/raw checks did not expose a repository LICENSE file; treat its license as **not verified**, and do not copy its prompt text. It is not the source for broad research lifecycle or paper integrity claims.
- [KalarisLabs/research-agent-skills](https://github.com/KalarisLabs/research-agent-skills/tree/main/skills/autoresearch), [`skills/autoresearch/SKILL.md`](https://raw.githubusercontent.com/KalarisLabs/research-agent-skills/main/skills/autoresearch/SKILL.md) and [repository LICENSE](https://raw.githubusercontent.com/KalarisLabs/research-agent-skills/main/LICENSE) (checked 2026-11-05). This skill describes a two-loop research orchestrator: rapid measurable experiments plus periodic synthesis/direction-setting; literature, hypotheses, state/log/findings files, and routing to domain skills. Repository is MIT © 2026 Kalaris Labs; the license says portions of skills adapt third-party MIT projects and points to `THIRD_PARTY_NOTICES.md`/`LICENSES/`. Attribute Kalaris Labs for this project and retain required notices if adapting covered material. Its prescribed autonomous continuity/reporting behavior is the authors' design, not a universal requirement or empirical result.

### Repository snapshots

The following HEAD commits were resolved with Git's remote reference protocol on 2026-11-05 (the source links above may move):

| Repository | HEAD |
| --- | --- |
| karpathy/autoresearch | `228791fb499afffb54b46200aca536f79142f117` |
| olelehmann1337/autoresearch-skill | `5860fa717f44c85c80647d673f6f3c335facfcf2` |
| KalarisLabs/research-agent-skills | `fa023d6d166562a8de118f59bb73647c0e444b8c` |

## Skill discovery / installation

- [Official Claude Code Skills docs](https://code.claude.com/docs/en/skills) (checked 2026-11-05): a skill is a directory containing `SKILL.md` with YAML frontmatter and Markdown instructions. Install per-project at `.claude/skills/<skill-name>/SKILL.md`, or personally at `~/.claude/skills/<skill-name>/SKILL.md`; the docs also describe managed and plugin scopes. Basic personal-directory discovery path: `mkdir -p ~/.claude/skills/<name>` then place `SKILL.md` there.
- Installation verified against [official Codex skills docs](https://developers.openai.com/codex/skills/) (redirects to ChatGPT Learn; checked 2026-11-05). Codex discovers local skills as directories with `SKILL.md` in repo `.agents/skills` locations (from CWD through repo root), user `$HOME/.agents/skills`, admin `/etc/codex/skills`, and bundled system paths. For a project skill, use `<repo>/.agents/skills/<name>/SKILL.md`; for user-wide use `~/.agents/skills/<name>/SKILL.md`. The docs do not list `$CODEX_HOME/skills` as a discovery location.
- Optional third-party installer for Kalaris repository: `npx skills add KalarisLabs/research-agent-skills --skill autoresearch --agent codex` (or `--agent claude-code`), documented by that repository README. This is not an Anthropic/OpenAI official installer. A local manual copy into the respective documented skills directory is the official discovery mechanism.

## Accuracy cautions

- The ScientistTwo paper does **not** use the phrases “zero citation hallucinations” or “code-text consistency.” It does report zero hallucinated references in the specific 1814-reference audit and 49/49 method-code alignment in the final variant; phrase these as bounded Table 7 results.
- Do not state that ScientistTwo's 80.4% applies to all research or all tasks. Keep denominator (86/107), benchmark context, and paper attribution adjacent.
- The three projects are independent works with separate license evidence. Do not infer that the unlicensed olelehmann repository is MIT merely because its inspiration or other projects are MIT.
