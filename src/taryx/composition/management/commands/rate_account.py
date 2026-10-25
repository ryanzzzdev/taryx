from datetime import date

from django.core.management.base import BaseCommand, CommandError

from taryx.core.accounts.models import Account
from taryx.core.pricing.engine import RatingError
from taryx.core.pricing.services import rate_account
from taryx.territories.au_nem.tariffs import GST_RATE, POLICY_IDENTITY, TARIFFS


class Command(BaseCommand):
    help = "Rate an account over [start, end) NEM days and persist the pinned run."

    def add_arguments(self, parser):
        parser.add_argument("reference", help="account reference, e.g. ACC-001")
        parser.add_argument("start", type=date.fromisoformat)
        parser.add_argument("end", type=date.fromisoformat)

    def handle(self, *args, **options):
        try:
            account = Account.objects.get(reference=options["reference"])
        except Account.DoesNotExist:
            raise CommandError(f"unknown account {options['reference']}") from None
        try:
            run = rate_account(
                account,
                options["start"],
                options["end"],
                tariffs=TARIFFS,
                gst_rate=GST_RATE,
                policy_identity=POLICY_IDENTITY,
            )
        except RatingError as exc:
            raise CommandError(f"{exc.code}: {exc}") from None
        self.stdout.write(
            f"run {run.id}: {run.lines.count()} lines, "
            f"net {run.net}, gst {run.gst}, total {run.total} "
            f"(digest {run.input_digest[:12]}…)"
        )
