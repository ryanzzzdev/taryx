"""Deterministic migration demo seed — one legacy cohort, one control."""

from datetime import date

from django.utils import timezone

from taryx.core.accounts.models import Account
from taryx.core.migration.models import Cohort


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
    cohort.members.set(members)
    return cohort
