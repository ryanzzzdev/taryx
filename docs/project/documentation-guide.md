# Taryx documentation guide

Created: 2026-10-25
Scope: Project planning, task tracking, decisions, verification evidence, and work records in Taryx.

## Purpose and source of truth

Use Markdown to preserve what we intend to build, what is agreed, what comes next, what is blocked, and what has actually been verified. This workflow adapts Cateniq's conventions to Taryx's single-repository boundary. Taryx owns its records independently; Cateniq and Voltix are references, not shared trackers.

Canonical documents live in `docs/project/`, relative to the Taryx root. The repository README is the entry point. Do not maintain another project README or duplicate backlog elsewhere.

If preserved locally, `docs/initial-discussion/` files are background discussions and proposals. The original planning chats currently live outside this repository; the README and canonical planning records capture the reconciled direction without depending on those local files. Preserve them as source material. Their titles, including “Final,” do not establish current acceptance. During planning, reconcile them with the user's agreements and later review findings, then link from the canonical specifications. Do not silently promote every suggestion into an accepted requirement.

## File layout and ownership

```text
README.md                         Introduction, verified setup, documentation links
AGENTS.md                         Scoped agent workflow instructions
.devin/skills/project-management/ Portable project-management skill
docs/initial-discussion/          Preserved background proposals and conversations
docs/agent-notes/                  Tooling notes and agent workarounds (non-canonical)
docs/project/
  documentation-guide.md         Process, templates, and record ownership
  roadmap.md                     Milestones, scope, dependencies, exit criteria
  backlog.md                     Canonical task records and status
  architecture.md                Current design and acceptance/implementation status
  blockers.md                    Obstacles and unresolved decision gates
  features/*.md                  Behaviour and acceptance specifications, when needed
  decisions/001-short-title.md    Significant decisions and their reasoning
  evidence/<topic>/              Sanitised verification findings, when needed
                                 (one folder per review unit: m1/, m2/, m3/...)
  journal/YYYY-MM.md             Historical work outcomes and verification
```

The root `README.md` preserves motivation, portfolio context and source links. Canonical architecture, feature contracts and task records own evolving implementation details; link to them rather than maintaining a second plan in the concept document.

Create feature specifications and evidence documents only when they have useful content. This setup does not require empty future directories or a preselected implementation backlog.

| Record | Owns | Update when |
| --- | --- | --- |
| `README.md` | Introduction, setup, navigation | Setup or documentation locations change; do not duplicate task status here |
| `documentation-guide.md` | Workflow and templates | The process or tracking ownership changes |
| `roadmap.md` | Milestone scope, dependencies, exit criteria, progress | Scope or sequence changes, work begins, or exit criteria pass |
| `backlog.md` | Task IDs, priorities, status, acceptance and completion evidence | Work is refined, started, blocked, completed, reopened, or dropped |
| `architecture.md` | Boundaries, components, interfaces, persistence and deployment design | Design is accepted or implementation changes it |
| `blockers.md` | Questions, impact, evidence, unblock actions and resolutions | An obstacle is identified, investigated, or resolved |
| `features/*.md` | Behaviour, inputs, outputs, rules, failure cases and acceptance | Before implementation and when agreed behaviour changes |
| `decisions/*.md` | Context, choice, alternatives, consequences and acceptance source | A significant choice is proposed, accepted, rejected, or superseded |
| `evidence/<topic>/` | Reproducible checks, observations and limitations | Verification needs detail beyond a task's short completion evidence |
| `journal/YYYY-MM.md` | Dated outcomes, checks, model/agent attribution | A meaningful work unit concludes or reaches a useful partial outcome |

Prefer links over repeated explanations. Task status belongs in tasks, milestone status in the roadmap, reasoning in decisions, and historical outcomes in the journal.

## Roadmap conventions

Taryx milestones live in the roadmap and are established through project planning. Do not copy Cateniq's or Voltix's milestones or automatically adopt the sequence in an initial discussion document.

For each agreed milestone record:

- Outcome and included scope.
- Exclusions and dependencies.
- Observable exit criteria and linked tasks/evidence.
- Status: `Planned`, `In progress`, or `Complete`.

Detail the upcoming milestone and immediate dependencies; keep later work broad. Mark completion only when exit criteria are satisfied. Distinguish local verification, hosted CI, native service verification, and release readiness where relevant. If a gate is deferred, explicitly record the accepted scope change and follow-up; do not silently claim it passed.

## Task records

Initially keep task bodies in `backlog.md`. Assign sequential IDs starting at `TAR-001`; never reuse an ID. IDs identify tasks, not priority.

Maintain a compact index in ascending ID order, using a leading status icon and a link to each task. Append new task links at the end. Task sections own the status word; index icons mirror it. Put delivery order and next-work context in `Delivery notes`, not in index ordering.

Use explicit anchors for stable links:

```markdown
<a id="tar-xxx"></a>

## TAR-XXX — Short outcome-oriented title

- Repository: taryx
- Area: documentation | workspace | metering | pricing | billing | migration | integration | portal | verification | deployment
- Milestone: agreed milestone, or Not assigned
- Priority: High | Normal | Low
- Status: Backlog 📋 | Ready 🟢 | In progress 🚧 | Blocked ⛔ | Done ✅ | Dropped 🗑️
- Depends on: task IDs, or None
- References: specification and decision links

### Outcome

Describe the concrete deliverable or behaviour.

### Done when

- Observable acceptance criterion.
- Relevant verification requirement.

### Completion evidence

Actual checks and results, including failures or checks not run.
Link commits/PRs when known. Otherwise identify changed files and uncommitted state.

### Notes

Material context, blocker link, next action, or reason for reopening/dropping.
```

| State | Icon | Meaning |
| --- | --- | --- |
| Backlog | 📋 | Identified work needing refinement or prioritisation |
| Ready | 🟢 | Scope and acceptance are clear; dependencies satisfied |
| In progress | 🚧 | Actively underway; keep the active set small |
| Blocked | ⛔ | A specific obstacle prevents progress; link its blocker |
| Done | ✅ | Acceptance and required verification satisfied, with evidence |
| Dropped | 🗑️ | Removed from scope deliberately, with a recorded reason |

Write the icon after the status word in task sections, for example `Status: Done ✅`. Update the index icon whenever status changes. Several status icons are non-BMP (4-byte UTF-8) characters that the file-edit tools corrupt on write; apply icon changes with scripted writes and verify the bytes per [the emoji-corruption note](../agent-notes/emoji-corruption.md).

Prefer tasks reviewable in a focused session. Split by meaningful outcome, not file count. Retain completed records. Required verification pending means the task is not Done. Reopen with a reason or create a follow-up for new scope. Minor edits need not manufacture a task.

If the backlog becomes unwieldy, move bodies to `tasks/TAR-XXX-short-title.md` and retain the backlog as an index. Preserve IDs and links; do not maintain duplicate bodies.

## Blockers and open questions

Use sequential stable IDs such as `BLK-001`. Record:

- Identification date and the concrete question or obstacle.
- Status: `Open` or `Resolved`.
- Affected tasks/milestones and practical impact.
- Whether it blocks current work or can be investigated alongside it.
- Evidence, attempted approaches, and relevant links.
- Next action and who or what can resolve it.
- Resolution and date when resolved.

Do not mark the whole project blocked because one task is blocked. Future planning decisions are not failed implementation attempts. Keep evidence and resolution here; tasks link to them. Record a lasting design choice in a decision record when warranted.

## Decision records

Use numbered files such as `001-markdown-project-tracking.md` for material architecture, correctness, scope, or maintenance choices. Routine implementation details do not require a decision record.

Each record contains title, date, status (`Proposed`, `Accepted`, `Rejected`, `Superseded`), context, decision, alternatives, consequences, follow-up, and relevant links. Accepted records must identify their acceptance source: explicit user agreement or a selection within delegated authority. Recommendations alone are not acceptance.

When replacing a decision, preserve its original reasoning, mark it Superseded, and link to its replacement. Update the current specification or architecture separately. Accepted design is not proof of implementation or verification.

## Verification evidence

Record the command or procedure, environment, inputs/workload, observed result, and limitations. Link detailed findings from the affected task when useful. Distinguish passing, failing, skipped, and unavailable checks. Keep synthetic/simulated results distinct from hardware observations, and local results distinct from hosted CI or deployment results.

Do not claim guarantees broader than the evidence. Keep secrets and unsanitised sensitive responses out of all records. Avoid committing bulky generated outputs when a concise reproducible procedure and findings suffice.

## Session workflow

### Before work

1. Read this guide, roadmap, and backlog to identify the current outcome and next task.
2. Read relevant specifications, architecture sections, decisions, and blockers.
3. Inspect actual files and repository state; documentation may lag.
4. Confirm acceptance criteria/dependencies and mark the task In progress when beginning it.

### During work

1. Stay within the authorised scope; record useful newly discovered work separately.
2. Update specifications when agreed behaviour changes.
3. Record material decisions, blockers, and actual verification results.
4. Preserve unrelated changes. When several agents contribute, coordinate task/file ownership and reconcile their evidence before marking the overall task Done.

### Before ending meaningful work

1. Update affected tasks with status, evidence, remaining work, and the next action.
2. Update affected architecture/specifications and blockers.
3. Change milestone status only when its exit criteria warrant it.
4. Add one concise journal entry for the work unit, or amend its existing entry.
5. Check links, status/index consistency, and contradictions across changed records.

Apply this after implementation, substantive investigation, accepted planning decisions, or documentation deliverables without a separate reminder. Pure explanations and unchanged status checks need no edits. Documentation closeout does not trigger another journal entry about itself.

When an authorised commit occurs, include related records in the same commit as the change they describe. Record changed files or a branch/PR in the journal rather than trying to include its own commit SHA. Reserve standalone `Records:` commits for record-only corrections. This workflow does not itself authorise commits, pushes, external tracker changes, publication, or scheduled automation.

### At milestone boundaries

Review exit criteria, evidence, outstanding tasks, and blockers. Mark completion only when supported, then refine the next milestone. Preserve explicit verification gaps rather than describing local completion as release readiness.

## Journal format and time

Use monthly files named for the UTC entry date. Read the system clock, for example `date -u`, rather than estimating or converting local time manually. Journal headings use `YYYY-MM-DD HH:MM UTC`. Ordinary planning dates may use the user's local date (Australia/Sydney); label times explicitly when ambiguity matters.

```markdown
## YYYY-MM-DD HH:MM UTC — Short work outcome

- LLM model: Reliable session-reported model; note unknown variant details.
- Coding agent: Agent/application; version only if known.
- Tasks: TAR-XXX, or None for work without a task.
- Completed: Concrete outcome or meaningful partial result.
- Verification: Checks performed and actual outcomes, including limitations.
- Remaining: Next action or links to unfinished tasks/blockers.
- Changes: Commit/PR references, or changed files if uncommitted.
```

Every entry includes separate LLM model and coding agent fields. Do not infer model identity from the agent name, available-model lists, or defaults. If only the family is known, record it and say the exact variant is unavailable. Use `Unknown (not recorded)` where no reliable evidence exists. List multiple contributors and their roles when relevant.

Keep entries short; do not copy transcripts or entire acceptance checklists. Correct factual errors without erasing the history of what was known at the time. Do not duplicate this journal in another location.

## Maintenance

The project-root `AGENTS.md` activates this workflow through the `project-management` skill, with a repository-carried copy at `.devin/skills/project-management/SKILL.md`. If it is unavailable, read this guide and restore the repository copy; do not introduce machine-local dependencies. It is a session routine, not a background watcher. Reconcile interrupted work at the next session.

Update only affected records. Preserve discussion sources and completed history. If an external tracker is adopted later, migrate task ownership and stop maintaining a second Markdown task tracker; retain specifications, architecture, decisions, and operational documentation in the repository and update this guide.
