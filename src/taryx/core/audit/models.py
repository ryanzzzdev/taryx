"""Append-only audit trail for consequential operator actions.

Entries record actor, action, target and machine-readable detail. The
trail is observational, not financial — it carries no balance or
immutability trigger requirements of its own (billing documents enforce
those separately).
"""

from django.db import models


class AuditEntry(models.Model):
    actor = models.CharField(max_length=64)
    action = models.CharField(max_length=64)
    target = models.CharField(max_length=200, blank=True)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


def record(actor: str, action: str, target: str = "", **detail) -> AuditEntry:
    """Persist one audit entry. Callers wrap this in the action's own
    transaction when the entry must commit or roll back with it."""
    return AuditEntry.objects.create(actor=actor, action=action, target=target, detail=detail)
