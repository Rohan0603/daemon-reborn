# GitHub Chief / Worker governance migration — Daemon Reborn

> **Current operating overlay (2026-11-09).** This section supersedes legacy **Linear** work-tracking, executor-routing and status-change instructions below, but **does not supersede project-specific architectural, security, provenance, validation, asset-licensing, decision-record or release-safety requirements**. Keep the original historical instructions below for traceability.

- **Task authority:** GitHub repository Issues plus an explicitly selected GitHub Projects v2 board. Project membership, Status, Priority, milestones and native dependencies are **NOT VERIFIED / not yet configured by this PR**; no agent may claim implementation `Ready` on this migration alone. Legacy Linear issue IDs (ORC-/VES-/RBRN-) remain source references, not an independent execution queue once a GitHub counterpart is approved.
- **Human invocation only:** The owner starts Chief/Worker sessions manually or through an approved AI-tool schedule. Changing labels, status or Actions events never launches AI agents. No unattended dispatcher or runner tokens are introduced.
- **Route labels:** exactly one primary `chief` or `worker`; `human` only with `chief` for actual owner gates. `metadata-bootstrap` is only an auxiliary `worker` flag, never implementation permission.
- **Mandatory first handoff:** Chief records `GITHUB METADATA SETUP` with target Project, field values, milestone/relationships and read-back status. If the Chief cannot access Projects, an explicitly scoped `METADATA BOOTSTRAP HANDOFF` may route `worker + metadata-bootstrap` **for metadata only**, then return to Chief with verified evidence; a separate `worker + Ready` handoff is required before implementation. On partial failures stop and reconcile, never invent Project read-back.
- **Safety retained:** Daemon Reborn's exact requirements, immutable approved decisions, Windows validation gates, Pixelorama asset provenance and QA checks remain binding. Preserve strict issue-before-code, source-based review and acceptance evidence. Never copy artifacts from legacy Daemon unless separately authorized.
- **Canonical full contract:** [docs/GITHUB_AGENT_GOVERNANCE.md](docs/GITHUB_AGENT_GOVERNANCE.md) is the adopted reusable Chief/Worker protocol. For work tracking/route/status conflicts it takes precedence over the historical Linear-only wording below; the existing instructions below remain authoritative for domain-specific work.
- **Default branch:** `main`. Do not modify branch protection, production code or existing CI as part of this PR.

---

## Existing Daemon Reborn project-specific agent instructions (preserved)

# Agent entrypoint

Linear is the only source of truth for requirements, decisions, research, work status and acceptance. This file and the README are pointers and bootstrap instructions; do not add a repository TODO list or copy project plans here.

## Read before work

1. Open the [Daemon Reborn project and issue tracker](https://linear.app/agtorchestrator/project/daemon-reborn-9b03c799740c) and read the assigned issue, its comments, acceptance criteria and current `blockedBy` relations. Confirm every required predecessor is Done before starting.
2. Read [00 START HERE](https://linear.app/agtorchestrator/document/00-start-here-project-constitution-and-source-of-truth-2496696b000f), the [Agent Operating Contract](https://linear.app/agtorchestrator/document/06-agent-operating-contract-required-task-lifecycle-c88d55f4572a), the [Architecture Blueprint](https://linear.app/agtorchestrator/document/02-architecture-blueprint-and-boundaries-d3a340b5cc98), the [Decision Register](https://linear.app/agtorchestrator/document/08-decision-register-adrs-approved-and-pending-5951be6efd5e), and relevant [Research](https://linear.app/agtorchestrator/document/07-research-register-questions-evidence-and-results-06a2326ff88e) and [Quality](https://linear.app/agtorchestrator/document/10-quality-and-acceptance-matrix-50c74a9061d3) guidance.
3. Work only from a scoped Linear issue. If it lacks the outcome and why it matters, authoritative source URLs with relevant versions/dates, baseline, dependencies, in-scope and excluded work, implementation steps, measurable acceptance, exact checks, security/privacy notes, evidence, rollback or open questions, ask for refinement in Linear before implementation.

## Route and execute

- Each issue has exactly one `RBRN / Executor` label: `RBRN / ChatGPT` for research and architecture decisions, `RBRN / Codex` for narrow coding and automated tests, or `RBRN / Work` for multi-app, UI, manual execution and release packaging. A label does not itself delegate work.
- Consequential work follows a Linear research issue → ChatGPT source-based investigation and recommendation → Research Register and proposed ADR → overseer approval in the Decision Register → implementation issue. Do not let an implementation executor silently make architecture, vendor or significant security/privacy decisions.
- Before code or research, move the issue to **In Progress** and post **START** with intent, baseline branch/SHA, source URLs and relevant versions/dates read, dependencies, plan, checks and risks. Read back the saved status and comment. Post **PROGRESS** at meaningful checkpoints. If a blocker appears, post **BLOCKED** with its ID, owner and exact unblock condition; do not work around dependency links.
- Keep changes limited to the issue. Never copy code, assets, secrets or configuration from legacy Daemon. Do not change approved architecture. Route consequential research, vendor, security/privacy or architecture uncertainty to ChatGPT; record evidence and approved decisions in Linear before implementation.
- Keep commits and pull requests small and issue-linked. Run the issue's actual checks and record commands, environment, exit codes and failures; label unavailable checks **NOT RUN** with a reproducible next action. Do not claim results from prior or partial runs.

## Review and handoff

Before review, post **REVIEW HANDOFF** in Linear and move the issue to **In Review**. Include the acceptance checklist, exact test results, PR/commit links and SHAs, relevant source URLs and versions/dates, screenshots/audio/benchmarks or redacted logs, security/privacy/consent and licensing impact, limitations, rollback path and the next reviewer action. Read back the saved handoff and status. Never mark an issue **Done** until a reviewer accepts it and merged code/evidence are verified; then post **CLOSEOUT** with the merged SHA and read back the closeout.

Keep all work tracking in Linear. Update existing issues for discovered work, and link new issues instead of leaving hidden TODOs in code or documentation.
