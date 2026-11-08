# Devin-driven Codex review loop (simplified process)

Status: pilot convention, agreed 2026-11-08; revised same day after a
Codex self-audit (`codex-review-loop-audit.md` — its findings are
adopted selectively here; recommendations there are not all binding).
The project-agnostic mechanism now lives in the global
`codex-review-loop` skill (linked from `campaign`); this document is
the Taryx instance — session ids, evidence paths, and observed quirks.
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
- **Reviewer**: a dedicated Codex *exec session* per milestone, invoked
  via `codex exec resume <session-id>` from
  `/usr/lib/chatgpt/resources/codex`. A fresh session is created for
  each milestone and resumed across that milestone's remediation
  rounds — a perpetual thread accumulates bias toward its own earlier
  verdicts and compacts away qualifications, so context beyond one
  milestone lives in the repo (review docs, probes), not the session.
  (The desktop-app thread `Taryx project review`,
  `01a16e5a-546f-7850-8796-1484463b943f`, was evaluated and rejected —
  its managed profile is read-only; see "Reviewer permissions".)
- **Mutual exclusion**: between the two agents, structural — while
  `codex exec` runs, Devin is blocked waiting on the subprocess. This
  is *not* an OS lock: other processes (a human editor, a second
  `codex` attach) can still touch the tree. The git-state gate in step
  2 is what detects outside interference.
- **Turn boundary**: the `codex exec` process exit.

### Hard thread rule

`codex exec resume` fails with `thread ... already has an active writer`
if the session is held open elsewhere — e.g. the thread open in the
Codex desktop app, or another `codex` process attached to it. During a
loop run the review session must not be open anywhere else; on a lock
conflict Devin stops and asks rather than retrying.

## The loop

For each milestone M{N}, after implementation and its commit:

1. **Review invocation** — Devin runs:

   ```bash
   /usr/lib/chatgpt/resources/codex exec -C "$REPO" --approve-for-me \
     resume <session-id> \
     --output-schema docs/project/evidence/verdict.schema.json \
     --json \
     -o docs/project/evidence/m{N}-verdict-r{R}.json \
     "M{N} implementation is committed at <sha>. Review per our
      conventions: write findings to
      docs/project/evidence/m{N}-independent-review.md plus runnable
      pytest probes, and update affected project records. Do not
      commit."
   ```

   Exec-level options (`-C`, `--approve-for-me`, `-c`) go **before**
   `resume` — they are not resume's own options. `--json` tees the
   event stream to stdout (capture it into
   `m{N}-events-r{R}.jsonl`); `--output-schema` constrains the final
   message, which `-o` saves — the verdict is a JSON artifact, not a
   prose marker. The human-readable review lives in the repo files
   Codex writes, not in `-o`.

   The review session is provisioned **once per milestone**, before
   its first round:

   ```bash
   /usr/lib/chatgpt/resources/codex exec -C "$REPO" --approve-for-me \
     -c 'sandbox_workspace_write.network_access=true' \
     "You are the independent reviewer for Taryx milestone M{N}.
      Review conventions live in docs/project/documentation-guide.md
      and docs/agent-notes/. Reply READY." \
     -o docs/project/evidence/m{N}-session-bootstrap.md
   ```

   Record the new session id (from the `--json` event stream or
   `session_index.jsonl`) in `handoff/state` or the journal — never
   use `--last` in automation.

   `--approve-for-me` selects workspace-write plus automatic review of
   approval requests. Verified 2026-11-08: sandboxed file writes work
   on both the create call and later `exec resume` rounds, and the
   audit run itself wrote docs/backlog/journal inside this repo.
   Whether automatic *escalation* (approval requests above the
   sandbox) survives resume is unverified — `approval_policy` drops
   to `never` on resume, which means "cannot ask", not "approve all".
   `network_access=true` enables broad command networking (not just
   localhost) and is needed for the dockerised Postgres on
   localhost:55432 — DB reachability on resume still needs a live
   round.

   Long reviews run as a backgrounded exec; Devin polls until exit.
   Record `git rev-parse HEAD` **and** `git status --porcelain`
   before the call.

2. **Gate checks on exit** — Devin verifies:

   - HEAD unchanged *and* the working tree matches its pre-call state
     except for allowed paths (`docs/`, probe files, `handoff/`).
     An unchanged HEAD does **not** prove the source is unchanged —
     staged, unstaged, and untracked writes must all be checked, and
     unexpected-path writes make the round fail, not approved.
   - The verdict JSON parses against the schema **and** its semantics:
     `reviewed_sha` equals the candidate SHA, verdict ∈
     `APPROVED | CHANGES_REQUESTED | BLOCKED`, required checks are
     present. `APPROVED` with missing checks or a SHA mismatch is
     rejected — schema compliance is not review correctness.
   - A crash, timeout, missing verdict, or unexpected write counts as
     an incomplete round, not an approval.

3. **Commit the docs first** — Codex's working-tree output (review doc,
   probes, record updates) is reviewed by Devin and committed as the
   first step of remediation, per the existing convention.

4. **Remediation** — if `CHANGES_REQUESTED`: Devin resolves findings,
   folds probes into the test suite, commits, then re-invokes step 1
   for the next round. The resumed thread carries prior-round context.

5. **Termination** — proceed to the next milestone only on
   `verdict: APPROVED` in the schema output **and** the preserved
   probes plus required project checks green. `BLOCKED` also ends the
   loop — straight to escalation.

6. **Escalation** — stop to the user after **3 rounds** without
   approval, on `verdict: BLOCKED`, or on any ambiguous state (lock
   conflict, unparsable verdict, unexpected writes, Codex blocked
   needing input). Do not loop indefinitely; an authorized extra round
   is recorded in loop state, not just conversation.

### Interruption and stop state

Quota and other process deaths (usage limits, timeouts, crashes) are
**incomplete rounds** — never approvals, never findings. Codex quota
(5-hour and weekly windows on the ChatGPT plan) is a shared
environmental constraint: a multi-milestone campaign can exhaust a
window mid-round, as happened at foundation R4 on 2026-11-08.

On any interrupted turn:

1. Keep the partial `m{N}-events-r{R}.jsonl` — it records how far the
   turn got, and the `turn.failed` payload carries the error and any
   suggested retry time.
2. Record the stop state in the journal: milestone, session id, round,
   candidate SHA, reason, retry time. This is what makes a later
   session resumable rather than archaeological.
3. Inspect — never blindly keep or discard — working-tree writes the
   died turn made; it may have been mid-review. Commit retained
   partial artifacts labelled as interrupted output.
4. Resume with `codex exec resume <same session id>` after the quota
   window resets — the session's context survives the failed turn.

## Standing rules (unchanged)

- Devin makes every commit; Codex makes none.
- `git push` is always manual — never prompted, never run by the loop.
- Review docs, preserved probes, and record updates follow
  `docs/project/documentation-guide.md`.

## Reviewer permissions

Observed 2026-11-08 (M3 loop, rounds 1–4): the `Taryx project review`
desktop thread runs a **managed restricted** profile — filesystem
read-only, `network: restricted`, `approval_policy: never`, and `cwd`
pinned to an unrelated project directory. It could source-review and
report findings via `-o`, but could not write docs/probes or run the
database tests.

**Why interactive chat feels fully-permitted**: the app thread answers
approval requests through `approvals_reviewer: auto_review` — an
automated reviewer grants scoped elevation per action. That is the
same thing `--approve-for-me` selects on the CLI; it is *not* the
`--dangerously-bypass-approvals-and-sandbox` mode.

**Why `exec resume` on that thread is read-only**: resume inherits the
*session's* profile. "Managed" does not prove every override is
ignored — admin requirements constrain overrides, but exact precedence
for that thread is unverified. The reliable fix is to resume a session
that was *created* with a writable profile.

Verified 2026-11-08 on this machine:

- `codex exec --approve-for-me` → `approval: on-request` (routed to
  auto-review), `sandbox: workspace-write [workdir, /tmp, $TMPDIR]` —
  wrote files and ran commands. The early probes wrote `/tmp` only.
- `codex exec resume <that-session>` → keeps `workspace-write`,
  `approval: never` — wrote files with no flags needed.
- The self-audit run (`codex exec -C taryx --approve-for-me
  -c 'sandbox_workspace_write.network_access=true'`) wrote
  `codex-review-loop-audit.md`, backlog, and journal entries directly
  into this repo — first live *repo* write evidence, not just `/tmp`.
- Still unverified: approval escalation above the sandbox on resume,
  and Postgres connectivity through the resumed session.

Options, in preference order:

1. **Dedicated exec session per milestone (adopted)** — fresh session
   per milestone, resumed across that milestone's rounds.
   Write/exec verified including repo paths. Not an app thread, so the
   writer-lock rule does not apply.
2. **New chat in the Codex "Taryx" project** on a trusted, writable
   project profile — equivalent permissions via the app profile, plus
   the transcript stays in the desktop UI. Writer-lock rule applies.
3. **`--dangerously-bypass-approvals-and-sandbox`** — disables Codex
   sandboxing and confirmations *where permitted*; it does not
   override OS, container, or admin-enforced restrictions. Emergency
   only — not required for the ordinary loop.
4. **Fallback (verified)** — restricted thread + `-o` verdict `.md`
   committed as the review artifact; Devin authors record updates.

## Known limitations

- **Thread lock**: app-open thread breaks `exec resume` (above).
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
