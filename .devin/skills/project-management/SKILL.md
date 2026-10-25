---
name: project-management
description: Maintain Taryx's Markdown roadmap, tasks, decisions, blockers, and work journal per docs/project/documentation-guide.md. Use for meaningful Taryx work and after implementation, investigation, planning decisions, or documentation updates.
allowed-tools:
  - read
  - grep
  - glob
  - edit
  - exec
---

# Project management and documentation

Keep Taryx's durable project records aligned with actual work. This is an in-session workflow, not a background watcher or scheduled task.

## Establish the source of truth

- Read the root `AGENTS.md` instructions and `docs/project/documentation-guide.md`. The guide owns record locations, templates, task/blocker formats, statuses, timezone, and update rules — follow it exactly.
- Read only the roadmap, active tasks, and specifications/decisions relevant to the work. Reconcile records with code, verification output, and the current conversation.
- Treat `docs/initial-discussion/` as preserved background proposals. Their titles and embedded suggestions do not establish acceptance; reconcile them with user agreements and link them from canonical records.
- Inspect actual files and repository state before updating records; documentation may lag reality.

## Update after meaningful work

Before the final response following implementation, a substantive investigation, an accepted planning decision, or a documentation deliverable:

1. Update the affected task in `docs/project/backlog.md` with actual status, completion evidence, remaining work, and the next concrete action. Reuse its `TAR-XXX` ID. Add a task for newly identified work only when useful under the guide's conventions; do not invent historical IDs or manufacture a ticket for every minor edit.
2. Update feature specifications for changed behaviour and `docs/project/architecture.md` for changed technical design. Keep proposed, accepted, implemented, and verified states distinct; recommendations are not acceptance.
3. Record material obstacles and unresolved questions in `docs/project/blockers.md` with affected tasks, impact, evidence, and an unblock action. Resolve existing records when evidence supports it.
4. Update milestone status in `docs/project/roadmap.md` only when its exit criteria warrant it. Preserve agreed scope and sequencing.
5. Add one concise journal entry for the completed work unit or meaningful partial outcome in `docs/project/journal/YYYY-MM.md`, following the guide's format. Include verification performed, limitations, and task/commit/PR links when available. Mark uncommitted work honestly. Read the system clock (`date -u`) for the UTC timestamp and record LLM model and coding agent as separate fields; write `Unknown (not recorded)` rather than guessing.
6. Check consistency and references among affected files. Briefly mention material documentation updates in the final response.

Update only affected records. If an answer is purely explanatory, a status check reveals no change, or the same outcome has already been recorded, make no documentation edit. If repeating this workflow for the same work unit, amend the existing entry rather than append a duplicate. Documentation updates do not themselves trigger another round of journaling.

## Evidence and scope

- A task is Done only when acceptance criteria and required verification are satisfied. Report failed, skipped, or unavailable checks; do not claim that a commit, deployment, or test occurred without evidence.
- Keep status in the backlog, milestone progress in the roadmap, reasoning in decisions, and historical outcomes in the journal. Prefer links to duplicate explanations.
- Preserve completed records and decision history. Supersede outdated decisions rather than silently rewriting their original reasoning.
- Do not overwrite unrelated work, bootstrap every missing document during routine closeout, or rewrite the backlog based on guesses. If a required record cannot be updated, state the specific limitation and next action.
- Status icons and other non-BMP characters are corrupted by the `edit`/`write` tools; apply those changes with scripted writes and verify the bytes — see `docs/agent-notes/emoji-corruption.md`.
- This workflow does not authorise commits, pushes, messages, external tracker mutations, or scheduled automations. Preserve the user's existing authorisation scope.
