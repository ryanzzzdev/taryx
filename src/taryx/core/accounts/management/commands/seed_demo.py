from django.core.management.base import BaseCommand

from taryx.core.accounts.seed import seed_demo_data, seed_operator_identities


class Command(BaseCommand):
    help = (
        "Seed deterministic demo accounts, NMIs, channels, "
        "tariff agreements and operator identities."
    )

    def handle(self, *args, **options):
        accounts = seed_demo_data()
        for account in accounts:
            channels = sum(s.channels.count() for s in account.supply_points.all())
            self.stdout.write(
                f"{account.reference}: {account.name} "
                f"({account.supply_points.count()} NMI, {channels} channels)"
            )
        for user in seed_operator_identities():
            role = user.groups.first()
            self.stdout.write(f"user {user.username}: role {role.name if role else '?'}")
