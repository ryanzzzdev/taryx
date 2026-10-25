# 001 — Portable Markdown project workflow

Date: 2026-10-25
Status: Accepted
Acceptance source: User explicitly requested Cateniq's agent, project-management and documentation methods for Taryx.

## Context

Planning and implementation need durable records accessible to future agents without a machine-local dependency or external tracker.

## Decision

Adopt Cateniq's root AGENTS instructions, repository-carried `.devin/skills/project-management/SKILL.md`, documentation guide, stable task/blocker IDs, evidence-based milestone exits and monthly UTC journal. Taryx uses TAR task IDs and owns its records independently. README remains the concept and navigation entry point; evolving design lives under `docs/project/`.

## Alternatives

An external tracker adds access requirements; copying Cateniq's tasks/history misrepresents Taryx progress; a second generic journal duplicates ownership.

## Consequences and follow-up

Meaningful work includes records closeout. Completed history is retained; proposals, acceptance, implementation and verification stay distinct. Related records accompany authorised code commits, but this workflow grants no commit/push authority. Follow the [guide](../documentation-guide.md); restore the repository skill if unavailable.
