# Problem: autonomous Devin–Codex implement/review loop

## Goal

Run a small demo project (<10 milestones) end-to-end with **two autonomous
coding agents and zero human message-passing**:

- **Devin** (inside Devin Desktop, the VS Code-based IDE) — does all
  implementation and all git commits
- **Codex** (inside the ChatGPT Codex desktop app) — acts as independent
  reviewer

The user should not have to relay "Devin has done M3, can you review" /
"Codex reviewed, can you resolve" between the two apps.

## The workflow being automated

The loop that already works manually today:

1. Devin implements a milestone, commits, writes exit-review evidence.
2. Codex reviews, writes findings to
   `docs/project/evidence/m{N}-independent-review.md` plus preserved
   pytest probes, and updates the affected project records.
3. Devin resolves findings, folds probes into the test suite, commits.
4. Codex re-reviews → repeat 3–4 until the review is clean.
5. Devin proceeds to the next milestone.

Every message the user currently relays carries zero information —
everything needed is already in the repo (review docs, probe files,
commit history). The user is pure plumbing.

## Hard rules

- **Ownership of writes**: Devin does all git commits; Codex never
  commits. Codex's output is working-tree changes (review docs, probes,
  record updates) that Devin reviews and commits as the first step of
  each remediation turn ("commit the docs first").
- **Push is always manual**: neither agent runs `git push`.
- **Mutual exclusion**: exactly one agent is active at a time. While
  Devin implements or remediates, Codex waits and does nothing; while
  Codex reviews, Devin waits and does nothing. The handoff itself is the
  lock — there is no concurrent editing of the shared working tree.
- Existing conventions are preserved: docs committed before remediation,
  preserved probes kept green, records updated per the project's
  documentation guide.

## Constraints and observed reality

- The two agents run in **separate desktop apps** on the same machine,
  sharing one working tree and git history.
- The working protocol is already **file-native**: Codex writes markdown
  findings + runnable pytest probes; Devin writes remediation addenda +
  commits. The repo is effectively already the message bus.
- Both agents can run shell commands, edit files, and run tests on the
  same machine.
- Desired: **event-driven handoff**, not naive polling — though a
  lightweight watcher that fires on file/commit events is acceptable if
  it is the practical option.

## The actual questions

1. **Handoff mechanism**: how does the active agent signal the idle one
   that its turn has begun? Options to evaluate:
   - Each agent invokes the other's **CLI** as a subprocess (headless
     `codex` invocation, `devin` CLI) — agent A literally starts agent
     B's turn.
   - A **filesystem convention + watcher** (e.g. inotify on a `handoff/`
     directory, or a git post-commit hook) that spawns the next turn.
   - A shared **message queue / MCP server** both agents connect to.
   - Which of these does each product actually support today?
2. **Termination discipline**: how does the loop know "all green, move
   on"? Need an agreed signal — e.g. Codex writes `verdict: APPROVED` in
   the review doc; Devin only proceeds to the next milestone on that
   marker.
3. **Turn boundary detection**: how does the waiting side know the
   active side is *finished* (as opposed to mid-turn)? A turn-complete
   marker file, process exit of a headless invocation, or watcher event?
4. **Orchestration ownership**: who drives the loop — Devin's campaign
   mode calling Codex for reviews, Codex supervising Devin, or a thin
     third-party orchestrator script holding the state machine?
5. **Safety gates**: what still requires a human (already decided: all
   pushes)? How is the mutual-exclusion guarantee enforced — convention
   only, or a real lock the orchestrator holds?

## Desired outcome

A concrete architecture for the handshake — ideally the simplest thing
that works on this machine, e.g.: Devin finishes M4 → writes
`handoff/review-request.md` → a watcher spawns headless `codex` on that
file → Codex appends findings and a verdict marker → the watcher spawns
Devin's remediation turn → repeat until `verdict: APPROVED` → next
milestone. With explicit answers on what each tool supports natively vs
what needs a small glue script.

## Note from Devin

The repo-as-message-bus part is already solved in practice — the missing
pieces are only **trigger delivery** (who wakes whom, and how a turn's
end is signalled) and the **stop signal**. If either tool supports
headless invocation, a ~50-line watcher/orchestrator script probably
does the whole job; the harder questions are capability verification and
the safety gates listed above.

See also `multi-agent-orchestrator-research.md` — findings from reading
the takt and ccbridge sources (2026-10-25), with the concrete borrowings
mapped onto this design.

Adopted (2026-11-08): the simplified variant — Devin drives the loop
in-session, invoking the existing Codex review thread via
`codex exec resume`. See `codex-review-loop.md`.
