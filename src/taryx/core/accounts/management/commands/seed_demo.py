from django.core.management.base import BaseCommand

from taryx.core.accounts.seed import seed_demo_data


class Command(BaseCommand):
    help = "Seed deterministic demo accounts, NMIs, channels and tariff agreements."

    def handle(self, *args, **options):
        accounts = seed_demo_data()
        for account in accounts:
            channels = sum(s.channels.count() for s in account.supply_points.all())
            self.stdout.write(
                f"{account.reference}: {account.name} "
                f"({account.supply_points.count()} NMI, {channels} channels)"
            )
