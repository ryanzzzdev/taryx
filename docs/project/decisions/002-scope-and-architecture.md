# 002 — Retail core with explicit integration boundaries

Date: 2026-10-25
Status: Accepted
Acceptance source: User agreed the reviewed concept and selected Taryx; detailed initial sequence and local delivery choices are selected within the current request to plan the project.

## Context

The portfolio needs a distinct retail/transactional system aligned with Kraken's public design principles. Earlier suggestions overstated exact production equivalence and split ingestion merely to increase service count.

## Decision

Keep accounts, metering, pricing, billing and migration in a Django modular monolith with client/territory/core boundaries. Deploy independent Celery worker pools using RabbitMQ. Use separate client instances with isolated databases and credentials. Separate the legacy calculator, owned market adapter and external counterparty simulator. Use React/TypeScript and Graphene for an operator-facing product.

Sequence billing/corrections, migration, client/integration extension, then operational verification and Kubernetes delivery. Docker Compose and kind are the initial environments. Use one Australian territory and synthetic fixtures; billing subledger, not wholesale settlement, is the core domain.

## Alternatives

A shared-database tenant architecture is viable but a different tenancy choice. A standalone meter service adds consistency overhead without a demonstrated need. A whole utility OS or multi-country regulatory implementation overwhelms the initial evidence budget. A bare calculator would omit the operational migration problem.

## Consequences and follow-up

One core transaction boundary simplifies financial integrity, while process/service boundaries still demonstrate failure recovery. Logical client isolation on shared local infrastructure does not imply independent availability. No exact Kraken clone or regulatory certification is claimed. Freeze outstanding domain/integration profiles through the [open gates](../blockers.md); reconsider extraction only with measured evidence or a new ownership requirement.
