# Agent entrypoint

Linear is the only source of truth for requirements, decisions, research, work status and acceptance. This file and the README are pointers and bootstrap instructions; do not add a repository TODO list or copy project plans here.

## Read before work

1. Open the [Daemon Reborn project and issue tracker](https://linear.app/agtorchestrator/project/daemon-reborn-9b03c799740c) and read the assigned issue, its comments, acceptance criteria and current `blockedBy` relations. Confirm every required predecessor is Done before starting.
2. Read the [approved workflow v3.1](https://linear.app/agtorchestrator/document/12-agent-workflow-v31-routing-dor-risk-and-merge-policy-8cb589a28d1e), [00 START HERE](https://linear.app/agtorchestrator/document/00-start-here-project-constitution-and-source-of-truth-2496696b000f), the [Agent Operating Contract](https://linear.app/agtorchestrator/document/06-agent-operating-contract-required-task-lifecycle-c88d55f4572a), the [Architecture Blueprint](https://linear.app/agtorchestrator/document/02-architecture-blueprint-and-boundaries-d3a340b5cc98), the [Decision Register](https://linear.app/agtorchestrator/document/08-decision-register-adrs-approved-and-pending-5951be6efd5e), and relevant [Research](https://linear.app/agtorchestrator/document/07-research-register-questions-evidence-and-results-06a2326ff88e) and [Quality](https://linear.app/agtorchestrator/document/10-quality-and-acceptance-matrix-50c74a9061d3) guidance.
3. Work only from a scoped Linear issue. If it lacks the outcome and why it matters, authoritative source URLs with relevant versions/dates, baseline, dependencies, in-scope and excluded work, implementation steps, measurable acceptance, exact checks, security/privacy notes, evidence, rollback or open questions, ask for refinement in Linear before implementation.

## Route and execute

- Each actionable issue uses exactly one **Agent Executor** label: `ChatGPT` (research, architecture, design, major decisions, ChatGPT DoR certification), `Coding Agent` (tool-agnostic Codex/Claude Code/OpenCode lightweight implementation), or `Work` (Windows GUI/audio, E2E, packaging, system validation). Use exactly one **Task Type** (`Research`, `Decision / ADR`, `Architecture`, `Design / Spec`, `Implementation`, `Verification / QA`, `Documentation`) and relevant **Component** labels. No project-specific label prefixes. A label does not itself delegate work.
- Consequential work follows a Linear research issue → ChatGPT source-based investigation and recommendation → Research Register and proposed ADR → overseer approval in the Decision Register → implementation issue. Do not let an implementation executor silently make architecture, vendor or significant security/privacy decisions.
- Before code or research, move the issue to **In Progress** and post **START** with intent, baseline branch/SHA, source URLs and relevant versions/dates read, dependencies, plan, checks and risks. Read back the saved status and comment. Post **PROGRESS** at meaningful checkpoints. If a blocker appears, post **BLOCKED** with its ID, owner and exact unblock condition; do not work around dependency links.
- Keep changes limited to the issue. Never copy code, assets, secrets or configuration from legacy Daemon. Do not change approved architecture. Route consequential research, vendor, security/privacy or architecture uncertainty to ChatGPT; record evidence and approved decisions in Linear before implementation.
- Keep commits and pull requests small and issue-linked. Run the issue's actual checks and record commands, environment, exit codes and failures; label unavailable checks **NOT RUN** with a reproducible next action. Do not claim results from prior or partial runs.


## Strict implementation readiness and manual handoff

- **Before claiming a new Coding Agent issue:** confirm a dated **ChatGPT `DoR PASS`** in the issue after the latest material scope/ADR/dependency change. Todo alone, a label, or a completed predecessor is not certification. If it is missing or stale, post **DoR FAIL / needs refinement** and leave the issue unclaimed. Existing active tasks are reviewed for gaps without inventing retroactive approval.
- Verify the issue's measurable outcome, approved ADR/research evidence, actual repository baseline and contracts, dependency relations, scoped file/module ownership, failure/privacy cases, explicit acceptance and test commands, risk tier, non-goals, rollback, and escalation. Read linked authoritative context; avoid reconstructing requirements from chat.
- Manual routing: the operator dispatches `ChatGPT` issues using the strongest available reasoning mode. Issue labels/status **do not** launch ChatGPT automatically.
- For consequential unknowns or major decision walls, first search for an existing issue; otherwise create a **separate linked ChatGPT + Research / Decision / ADR / Architecture / Design / Spec** issue with precise question, alternatives, source versions, evidence gaps, risk, affected scope, and acceptance criteria. Mark only dependent implementation blocked, continue safe independent scope, and wait for owner-approved ADR changes.
- A `Work + Verification / QA` issue is separate only when real Windows GUI, sound, visual, system, security, release or environment proof is required. Code-level acceptance does not complete parent feature/milestone validation.

## PR risk, approvals and merge authority

- Explicitly record **Risk: Normal / Elevated / Critical** in the Linear issue and pull request. Assess the *actual diff* before merge; priority is not risk. Security/permissions/secrets/consent, irreversible data changes, OS actions, signing/trust and architectural changes generally require **Critical** review. Cross-component/provider integration, concurrency and migrations generally require **Elevated** review.
- Every PR requires real automated checks, relevant negative tests and **independent reviewer signoff**; implementer cannot approve own changes. Report all NOT RUN checks and material limitations.
- **Normal:** after required CI/checks and independent reviewer signoff, an authorized agent may **deliberately initiate** merge and record the exact merged SHA in Linear. This does **not** authorize unattended GitHub auto-merge, which remains prohibited.
- **Elevated / Critical:** require explicit owner approval tied to the reviewed **head commit SHA** before any merge, in addition to risk-appropriate integration/security/negative tests and independent review. If the PR changes after approval, reevaluate risk and seek renewed approval.
- Never confuse GitHub configuration with policy; if protected branch rules are not verified, enforce reviewer/owner checks operationally and record platform limitations. Never silently enable GitHub auto-merge.
- A coding issue is Done only on evidence-backed accepted delivery/authorized merge; any linked Work validation and parent milestone must be separately accepted.

## Review and handoff

Before review, post **REVIEW HANDOFF** in Linear and move the issue to **In Review**. Include the acceptance checklist, exact test results, PR/commit links and SHAs, relevant source URLs and versions/dates, screenshots/audio/benchmarks or redacted logs, security/privacy/consent and licensing impact, limitations, rollback path and the next reviewer action. Read back the saved handoff and status. Never mark an issue **Done** until a reviewer accepts it and merged code/evidence are verified; then post **CLOSEOUT** with the merged SHA and read back the closeout.

Keep all work tracking in Linear. Update existing issues for discovered work, and link new issues instead of leaving hidden TODOs in code or documentation.
