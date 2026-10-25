"""Deterministic migration demo seed — one legacy cohort, one control."""

from datetime import date

from django.db import transaction
from django.utils import timezone

from taryx.core.accounts.models import Account
from taryx.core.migration.models import Cohort, CohortMembership


def seed_migration_cohort() -> Cohort:
    """Legacy Cohort A: ACC-001 (FIT defect exposure) and ACC-003
    (heritage policy), evaluated on 2026-03-02. ACC-002 is untouched —
    it remains on the new engine throughout (control)."""
    cohort, _ = Cohort.objects.update_or_create(
        name="Legacy Cohort A",
        defaults={
            "routing_mode": Cohort.Mode.LEGACY_ONLY,
            "routing_revision": 1,
            "eval_period_start": date(2026, 3, 2),
            "eval_period_end": date(2026, 3, 3),
            "eval_frozen_at": timezone.now(),
        },
    )
    members = Account.objects.filter(reference__in=["ACC-001", "ACC-003"])
    elsewhere = {
        m.account_id
        for m in CohortMembership.objects.filter(account__in=members).exclude(cohort=cohort)
    }
    if elsewhere:
        refs = [a.reference for a in members if a.id in elsewhere]
        raise ValueError(f"accounts already belong to another cohort: {refs}")
    # Membership changes are gate-affecting: serialize with cutover's
    # final gate re-read via the shared advisory lock.
    from taryx.core.migration.services import _gate_lock

    with transaction.atomic():
        _gate_lock(cohort.id, using="default")
        cohort.members.set(members)
    return cohort
