from datetime import date

from django.core.management.base import BaseCommand, CommandError

from taryx.composition.tasks import process_billing_operation
from taryx.core.accounts.models import Account
from taryx.core.billing.services import AdmissionError, admit_issue
from taryx.core.pricing.models import RatingRun


class Command(BaseCommand):
    help = "Admit a billing operation (idempotent) and enqueue issuance."

    def add_arguments(self, parser):
        parser.add_argument("reference")
        parser.add_argument("start", type=date.fromisoformat)
        parser.add_argument("end", type=date.fromisoformat)
        parser.add_argument("--op", required=True, help="operator idempotency key")
        parser.add_argument("--run", type=int, help="rating run id (default: latest)")

    def handle(self, *args, **options):
        try:
            account = Account.objects.get(reference=options["reference"])
        except Account.DoesNotExist:
            raise CommandError(f"unknown account {options['reference']}") from None
        runs = RatingRun.objects.filter(
            account=account,
            period_start=options["start"],
            period_end=options["end"],
        )
        run = runs.get(pk=options["run"]) if options["run"] else runs.order_by("-id").first()
        if run is None:
            raise CommandError("no rating run for this account and period — rate first")
        try:
            op = admit_issue(account, options["start"], options["end"], run, options["op"])
        except AdmissionError as exc:
            raise CommandError(f"{exc.code}: {exc}") from None
        try:
            process_billing_operation.delay(op.operation_id)
            self.stdout.write(f"{op.operation_id}: admitted ({op.status}), enqueued")
        except Exception as exc:  # broker may be down; outbox retains intent
            self.stderr.write(
                f"{op.operation_id}: admitted ({op.status}), enqueue failed "
                f"({exc}); pending in outbox"
            )
