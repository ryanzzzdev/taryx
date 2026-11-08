# Codex review-loop audit

Date: 2026-11-08. Status: investigation and recommendations, not an adopted replacement.
Related: [pilot convention](codex-review-loop.md), [TAR-019](../project/backlog.md#tar-019).

## Evidence and limits

Inspected `/usr/lib/chatgpt/resources/codex` version `0.153.4` with top-level,
`exec`, `exec resume`, and `exec fork` help. Resume and fork both expose
`--output-schema`, `--json`, and `-o`. Exec exposes `--approve-for-me`;
resume's own help does not expose that flag, `-C`, or `-s` (put exec-level
options before the subcommand). No model invocation, permission escalation,
DB probe, or complete review round was run during this audit.

Official references consulted:
- [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Sandbox and approvals](https://learn.chatgpt.com/docs/agent-approvals-security)
- [Permission profiles](https://learn.chatgpt.com/docs/permissions)
- [Managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration)

## Permission corrections

Sandbox/filesystem/network access, approval policy, and approval reviewer are
separate controls. `--approve-for-me` selects workspace-write plus automatic
review of approval requests. It does not grant unrestricted host access.
`approval_policy=never` means no approval requests, not approval of everything.
The pilot's resumed workspace-write / approval-never result establishes neither
retained automatic escalation nor equivalence to interactive approvals.
The journal identifies the write probes as `/tmp` writes; those do not establish
writes to repository evidence paths, correct cwd, or PostgreSQL access.

A dedicated thread provides ownership, not privileges. The current interactive
review session itself has a managed profile with repository and temporary paths
writable and narrower protected paths; managed does not mean read-only.
Do not infer from that label alone that all configuration overrides are ignored.
Admin-enforced requirements constrain allowed settings, and named permission
profiles must not be mixed with legacy sandbox configuration. Exact override
precedence for the historical app thread remains unverified.

The bypass flag disables Codex sandboxing/confirmations where permitted; it does
not override OS/container/admin restrictions. Remove the claim that it provides
full permission regardless of profile. It is not required for the ordinary loop.
The legacy workspace network toggle enables broader command networking, not
only localhost:55432. Actual DB access must be tested on create and resume.

## Recommended loop changes

1. Use a fresh reviewer session per milestone, resume for remediation rounds,
   and keep durable findings outside conversation history. Fork copies context;
   it is not a clean independent opinion or a new Git worktree.
2. Capture exact UUID, CLI/model settings, base SHA, candidate SHA, round ID,
   contract version, and effective permissions. Re-send acceptance scope and
   unresolved finding IDs each round. Avoid `--last` in automation.
3. Prefer a separate reviewer checkout/worktree and disposable test database.
   If sharing a checkout, enforce a repository lock through actual child exit.
   A waiting driver does not exclude other processes; background polling does
   not itself enforce mutual exclusion. An exec-origin thread is not immune
   to a second writer attaching. App visibility alone is not a portable lock rule.
4. Replace a final Markdown marker with schema-constrained JSON including
   APPROVED, CHANGES_REQUESTED, and BLOCKED, reviewed SHA, findings, checks,
   verification gaps, and artifact paths. Keep human review Markdown separately.
   Validate JSON and semantic gates outside the model. Schema is not evidence.
5. Require successful process/turn completion and a fresh per-run result;
   reject stale files, mismatched SHA, incomplete checks, and unexpected writes.
   Check staged, unstaged, and untracked changes as well as HEAD. An unchanged
   HEAD does not prove the reviewed source stayed unchanged.
6. Preserve review/probes before remediation, but inspect allowed paths and
   probe contents. Run checks against the reviewed candidate without silent
   production-code fixes. Re-run required project gates after remediation;
   preserved reviewer probes alone are insufficient. Keep round history.
7. Enforce maximum rounds, total wall time, timeout/cancellation, and recovery
   state in a small deterministic wrapper. Distinguish infrastructure failures
   from requested code changes. Never blindly replay an ambiguous interrupted run.

## Remaining verification

On the pinned CLI, test create and resume against a disposable review workspace:
actual repository artifact write, correct git root/candidate SHA, DB connection,
structured final output, interrupted-run recovery, and (if needed) a benign,
explicitly authorized approval-requiring action. Inspect effective approval
policy/reviewer instead of assuming creation flags remain effective forever.
TAR-019 remains In progress; recommendations above are not implementation proof.
