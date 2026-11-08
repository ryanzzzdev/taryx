# Devin-driven Codex review loop (simplified process)

Status: pilot convention, agreed 2026-11-08.
Predecessors: `multi-agent-handoff-problem.md` (problem framing),
`multi-agent-orchestrator-research.md` (what takt/ccbridge do).

## Purpose

Run a milestone's implement/review cycle with one human "go" message
instead of the user relaying "Devin has done M{N}, can you review" /
"Codex reviewed, can you resolve" between the two desktop apps.

Devin (this Devin Desktop session) is the loop driver. Codex runs as a
synchronous subprocess invoked through its CLI against the **existing**
review thread, so review context accumulates across milestones.

## Actors and mechanism

- **Implementer / driver**: Devin, inside this Devin Desktop session.
  Implements, commits, remediates, and invokes the reviewer.
- **Reviewer**: Codex thread `Taryx project review`
  (`01a16e5a-546f-7850-8796-1484463b943f`), invoked headlessly via
  `codex exec resume <thread-id>` from `/usr/lib/chatgpt/resources/codex`.
- **Mutual exclusion**: structural — while `codex exec` runs, Devin is
  blocked waiting on the subprocess. One active agent at a time.
- **Turn boundary**: the `codex exec` process exit.

### Hard thread rule

`codex exec resume` fails with `thread ... already has an active writer`
if the Codex app holds the thread open. During a loop run, do **not** open
`Taryx project review` in the Codex desktop app. On a lock conflict Devin
stops and asks rather than retrying.

## The loop

For each milestone M{N}, after implementation and its commit:

1. **Review invocation** — Devin runs:

   ```bash
   /usr/lib/chatgpt/resources/codex exec resume \
     01a16e5a-546f-7850-8796-1484463b943f \
     "M{N} implementation is committed at <sha>. Review per our
      conventions: write findings to
      docs/project/evidence/m{N}-independent-review.md plus runnable
      pytest probes, and update affected project records. Do not commit.
      End your reply with exactly one of:
      verdict: APPROVED | verdict: CHANGES_REQUESTED" \
     -o docs/project/evidence/m{N}-verdict-r{R}.txt
   ```

   Long reviews run as a backgrounded exec; Devin polls until exit.
   Record `git rev-parse HEAD` before the call.

2. **Gate checks on exit** — Devin verifies:

   - HEAD unchanged (Codex never commits — checked, not trusted).
   - The verdict file exists and ends with a verdict marker.
   - If either fails, the turn counts as incomplete, not approved.

3. **Commit the docs first** — Codex's working-tree output (review doc,
   probes, record updates) is reviewed by Devin and committed as the
   first step of remediation, per the existing convention.

4. **Remediation** — if `CHANGES_REQUESTED`: Devin resolves findings,
   folds probes into the test suite, commits, then re-invokes step 1
   for the next round. The resumed thread carries prior-round context.

5. **Termination** — proceed to the next milestone only on
   `verdict: APPROVED` **and** the preserved probes green.

6. **Escalation** — stop to the user after **3 rounds** without
   approval, or on any ambiguous state (lock conflict, unparsable
   verdict, Codex blocked needing input). Do not loop indefinitely.

## Standing rules (unchanged)

- Devin makes every commit; Codex makes none.
- `git push` is always manual — never prompted, never run by the loop.
- Review docs, preserved probes, and record updates follow
  `docs/project/documentation-guide.md`.

## Known limitations

- **Thread lock**: app-open thread breaks `exec resume` (above).
- **Permission profile (observed, round 1)**: the thread runs
  read-only with `approval_policy: never` — findings arrive in the
  verdict file via `-o` but Codex cannot write review docs, probes or
  record updates into the tree. Devin writes the remediation addendum
  and record updates itself; if authored docs are required, create a
  dedicated review thread with a writable profile or fall back to
  per-round `codex exec -C $REPO --sandbox workspace-write` (stateless).
- **Context growth**: resumed threads compact over many milestones; if
  the reviewer loses conventions, pin the review prompt text above or
  fall back to stateless rounds with the review doc as the contract.
- **No independent check on Devin**: the loop verifies Codex's output
  mechanically (HEAD, verdict file, probes) but Devin's own gates are
  self-enforced. Human review of commits before push remains the
  backstop.
- **`codex queue --thread` exists** for injecting messages while the
  app holds the thread, but delivery is async — not used by this loop.

## Human touchpoints per milestone

1. "Go on M{N}" — one message starts the whole cycle.
2. Escalations, if any (round cap, lock, blocked reviewer).
3. Review the commits and push manually when satisfied.
