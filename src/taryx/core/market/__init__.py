"""Bounded market integration — the synthetic `taryx-market/1` workflow.

Owns durable transfer-request state (submit → callbacks → terminal
outcome), an inbox deduped on (correlation_id, seq), an exception list
for unknown/malformed inbound events and a market outbox whose consumer
applies the terminal outcome to core — see decision 005.
"""
