# Research: what takt and ccbridge do, and what to borrow

Companion to `multi-agent-handoff-problem.md`. Source read on 2026-10-25
from shallow clones of `github.com/nrslib/takt` and
`github.com/marko3190/ccbridge` (HEAD at clone time; not pinned).

## TL;DR

Both projects independently implement the "thin orchestrator over headless
CLI agents" design proposed in the problem doc. The interesting material is
not the state machine (which is simple) but the **contracts, gates, and
failure handling** around it. The highest-value borrowings for the
Devin–Codex duet:

1. ccbridge's `needs_input` typed human-gate protocol.
2. takt's stable `finding_id` lifecycle and post-remediation review-scope rules.
3. takt's "judge picks a rule number" pattern for any semantic routing.
4. System steps: the engine, not an agent, runs the objective gates.
5. ccbridge's subprocess-runner details (stdin prompt, kill grace, raw logs).

## ccbridge (~5k lines of JS)

Fixed four-role pipeline: planner → critic → executor → reviewer, driven by
`src/orchestrator.mjs`. Two workflows: `execution` (plan/critique loop, then
execute/review loop) and `analysis` (analyze/challenge loop).

### State and resumability

- One `state.json` per run under `.runs/<runId>/`, rewritten after **every**
  stage transition. Any kill/crash resumes mid-loop via `ccbridge resume`.
- Per-round artifacts: `plan.round-N.json`, `critique.round-N.json`,
  `execution.round-N.json`, `review.round-N.json`, plus `summary.json` at
  the end. Raw agent I/O goes to `raw/<role>-<op>.{stdout,stderr}.log`.
- Bounded loops: `maxPlanRounds`, `maxReviewRounds` in config. Exhausted
  review rounds end the run as `review_changes_requested` — then a human
  runs `ccbridge continue`, which just bumps `maxReviewRounds` by one and
  re-enters at `execute`. Cheap escape valve, worth copying.

### Human-gate protocol (borrowable)

Every agent operation's output schema is wrapped in:

```text
{ response_type: "result" | "needs_input",
  result: <operation schema> | null,
  input_request: { summary, questions[] } | null }
```

Questions are typed (`text` / `single_select` / `multi_select`, with
`required`, `min_select`, `max_select`, `options[]`). On `needs_input` the
orchestrator writes `pending-input.json`, sets `status: waiting_for_user`,
and exits cleanly; `ccbridge answer` validates the answers against the
question types and resumes. This is a much richer version of "escalate to
human" than a bare exit code — the agent states *what* it needs in a
structured way and the run pauses, resumable, instead of dying.

### Verdict contract

`reviewSchema`: `verdict: pass | changes_requested` +
`blocking_findings[]` / `non_blocking_findings[]` (each finding:
`id, title, details, file`). The executor self-reports
`files_changed[]`, `tests_run[]` (command/result/summary), and
`plan_deviations[]`. Plans carry `revision_notes[]` tracking each
critique issue as `new | addressed | deferred` — a lightweight finding
lifecycle, though takt's is richer.

### Subprocess runner (`providers/cli-shared.mjs`)

- Prompt passed on **stdin**, not argv (avoids arg-length and quoting issues).
- Timeout (default 15 min) → SIGTERM, then SIGKILL after 5 s grace.
- 10 s heartbeat progress events; stdout/stderr captured to files regardless
  of outcome.
- Codex invocation: `codex --ask-for-approval never exec --cd <ws>
  --output-schema <file> --output-last-message <file> --sandbox read-only`.
  Note the reviewer gets `read-only` sandbox — findings can't leak into the
  working tree. We need `workspace-write` for our Codex (it writes review
  docs), but the flag is per-role configurable.
- `parseStructuredOutput` unwraps defensively (`structured_output`,
  `result`, `content[]`, bare JSON) — model CLIs do not always return the
  shape the flag promises.

## takt (large TypeScript CLI)

A general YAML workflow engine (`WorkflowEngine`, EventEmitter-driven).
Far bigger than needed — but several mechanisms transfer.

### Routing rules: judge picks a number, never free text

Each step has an ordered rule list. Evaluation order (verified in
`src/core/workflow/evaluation/` + CLAUDE.md):

1. `when(expr)` — **deterministic** expressions over declared effect
   results, e.g. `when(effect.sync.sync_with_root.success == true)`.
2. `[STEP:N]` tags the step was instructed to emit.
3. Natural-language `condition:` strings — an AI judge call returns
   `{step: N, reason}` (schema in `builtins/schemas/judgment.json`): the
   judge selects the **index** of the matching declared transition.
   It cannot invent a next state; unmatchable rules fail fast, no
   silent default.

This is the right pattern for any place we'd otherwise parse a verdict out
of prose: enumerate the legal outcomes, make the model pick a number.

### System steps — the engine does the objective work

`mode: system` steps execute engine-level effects (`pr_status`,
`sync_with_root`, `resolve_conflicts_with_ai`, `commit_and_push`,
`wait_ci`, `caccia` for CodeRabbit). Git operations, CI polling, and
status checks are orchestrator code, not agent turns — direct validation
of putting pytest/HEAD checks in our script rather than in prompts.

### Three-phase agent steps

A normal step runs up to three phases on the same provider session:

1. **Work** — step's `allowed_tools`; `Write` is removed if the step
   defines a report output contract.
2. **Report** — `Write` only; the agent must emit the declared report
   files (facets/output-contracts/*.md are report skeletons with slots).
3. **Status judgment** — a *separate, isolated, strict-readonly, no-MCP,
   no-session* call with a required output schema
   (`setupIsolatedStructured` in `src/infra/providers/codex.ts`). The
   judgment never runs inside the worker's own session and can't touch
   the tree.

Per-phase tool restriction enforced by the provider, not the prompt —
stronger than asking nicely.

### Loop control

- `max_steps: 75` per run — global runaway budget independent of any
  per-loop cap. Borrow this even if per-loop caps exist.
- `loop_monitors`: when a step repeats past `threshold`, a judge
  (`persona: supervisor`) reviews the trajectory against explicit
  conditions — "progress exists and reports converge → continue",
  "assumptions must change → replan", "no feasible path → ABORT".
  Judge-based convergence detection instead of (or alongside) a hard
  round cap. For a two-step fix/review cycle this is probably overkill,
  but the *conditions* are good prompt material for an escalation
  decision.
- `LoopDetector`/`CycleDetector` also catch mechanical repeats without
  judge calls.

### Review discipline (the best single borrowing)

`builtins/en/workflows/rules/peer-review-scope.md` encodes review-scope
rules worth adapting near-verbatim into the Codex review prompt:

- **Finding lifecycle**: stable IDs `CODE-NEW-*`, `CODE-PERSIST-*`,
  `CODE-RESOLVED-*`, `CODE-REOPENED-*` carried across rounds in the
  report contract; "findings without `finding_id` are invalid". Our
  markdown review docs currently have free-form findings — adopting
  stable IDs makes "did round N+1 actually fix round N's findings"
  mechanically checkable, including by the orchestrator.
- **Post-remediation scope limit**: re-reviews inspect only unresolved
  findings, completed repairs, and paths directly affected by repairs —
  "do not restart general discovery in unchanged areas". Directly
  counters the classic failure where re-review round 3 invents new
  findings and the loop never converges.
- **Same-cause consolidation**: only merge findings sharing cause +
  violated condition; if re-reviews keep surfacing same-cause violations
  elsewhere, the earlier impact analysis was incomplete — that's
  *non-convergence evidence*, not a fresh finding.
- **Pre-existing-diff exclusion**: don't report diffs that predate the
  task unless they intersect the change's blast radius.

### Isolation note worth recording

takt deliberately uses `git clone --reference <repo> --dissociate` rather
than `git worktree`, because Claude Code follows the `.git`-file `gitdir:`
pointer back into the main repo and breaks isolation. Irrelevant to our
single-tree design, but worth knowing if we ever add a parallel variant:
agent tools defeat real worktrees.

### Sessions

Within a run, steps sharing persona+provider+model resume the same
provider session (cheaper context); `session: refresh` or provider
fallback breaks it. Map to `codex exec resume --last` / `devin -c` if we
want warm context across rounds — though stateless turns keep the audit
story simpler.

## What to deliberately skip

- **The YAML DSL itself.** takt's engine is ~an order of magnitude more
  machinery than a two-role fixed loop needs. Borrow mechanisms, not the
  framework.
- **Multi-provider abstraction.** We have exactly two providers; a
  provider interface is premature.
- **Worktree parallelism / fan-out.** Our serial single-tree model is a
  deliberate choice, not a missing feature.
- **Interactive question UI.** ccbridge's `answer` CLI is nice but our
  escalation path can be "stop, print pending-input.json, human
  intervenes" — same file protocol, less code.
- **Faceted prompt library** (personas/policies/knowledge as separate
  assets). The *idea* — policy docs the reviewer must enforce — maps
  onto our existing `docs/` conventions anyway.

## Proposed concrete shape

Folding the borrowings back into the problem doc's sketch:

```text
duet.py --milestone N
  state.json per run (handoff/runs/mN/), rewritten per stage   [ccbridge]
  per stage:
    spawn agent via stdin prompt, timeout→SIGTERM→SIGKILL      [ccbridge]
    tee stdout/stderr to runs/mN/raw/                          [ccbridge]
    objective gates run as system steps:                       [takt]
      after devin turn: git status clean, pytest
      after codex turn: HEAD unchanged, verdict.json parses
    codex exec --output-schema verdict.schema.json             [verified on
              --sandbox workspace-write -C $REPO                  this machine]
    verdict: {verdict: pass|changes_requested,                 [ccbridge shape]
              findings[{id, title, file, severity}]}
    review prompt embeds takt's scope rules + finding_id lifecycle
    bounded: maxRounds per milestone + maxSteps global budget  [takt]
    exhaustion → pending-input.json, clean exit,               [ccbridge]
               `duet.py continue` bumps round budget
```

## Open verification items

- `devin` CLI not installed on this machine; `devin -p` headless is
  documented but unverified locally. Provider-side question remains the
  blocker.
- `codex exec --output-schema` exists in 0.153.4 but semantics (does the
  schema constrain the file write, or just the final message?) need one
  empirical run.
- Whether `codex exec resume` / `codex queue` can address desktop-app
  threads via the shared app-server — only matters if we want the
  desktop session in the loop rather than fresh headless turns.
