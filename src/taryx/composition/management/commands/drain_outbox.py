from django.core.management.base import BaseCommand

from taryx.composition.tasks import digest_resolver
from taryx.core.billing.services import drain_outbox


class Command(BaseCommand):
    help = "Recover pending outbox events (broker outage or lost tasks)."

    def handle(self, *args, **options):
        ops = drain_outbox(digest_resolver=digest_resolver)
        for op in ops:
            self.stdout.write(f"{op.operation_id}: {op.status}")
        self.stdout.write(f"{len(ops)} operation(s) processed")
