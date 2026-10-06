---
name: bmad-multi-llm-council
description: Swarm Adversarial Cross-Review Gate for BMAD. Dispatches unified diffs to independent external LLM reviewers (MiniMax, Kimi, Codex, Gemini) via standard local CLI adapters. Use when the user requests multi-model verification, cross-LLM code review, or adversarial review by an independent model.
---

# BMAD Multi-LLM Council (Swarm Cross-Review Gate)

## Purpose & Philosophy

Traditional agentic development suffers from **same-model confirmation bias**: when the implementing LLM reviews its own code or spawns subagents on the same model weights, systematic blind spots (concurrency races, multi-tenant leaks, edge cases) go unnoticed.

The **Multi-LLM Council** operationalizes an adversarial, multi-provider review gate:
- **Independent Evaluator:** A different model family (e.g. MiniMax M3, Kimi K3, Codex, Gemini) audits the unified diff.
- **Zero-Dependency CLI Adapters:** Communicates via local CLI/stdio or ephemeral prompt files on disk (`review-prompts/`), preserving the BMAD core principle of "simplicity over cleverness".
- **Strict Evidence Standard:** Evaluators are constrained to report only concrete, reproducible bugs with file/line evidence. Stylistic suggestions are silenced.

## Workflow

1. **Invocation:** Run `python skills/bmad-multi-llm-council/scripts/council_dispatcher.py <diff_file>` or integrate the script into `bmad-code-review` / `bmad-build` via custom lenses.
2. **Adapter Probing & Failover:** The dispatcher probes available local CLIs in priority order (`minimax`, `kimi`, `codex`, `gemini`), passing the diff safely via stdin or tempfile to prevent OS `ARG_MAX` limits.
3. **Execution:** The diff is audited strictly for contract regressions, multi-tenancy isolation leaks, unsafe concurrency, and security vulnerabilities.
4. **Result & Triage Hand-off:**
   - If clean, outputs `APPROVED` and exits `0`.
   - If defects are detected, outputs the findings and exits `1`. When called from `bmad-code-review`, findings route directly into `step-03-triage.md`.
5. **Fail-Safe Fallback:** If no CLI is configured or authenticated, a manual review prompt with a unique timestamp/PID is written to `_bmad-output/review-prompts/` and halts with exit code `2` (`HALT_INSPECT`), preventing uninspected code from passing automated pipelines.
