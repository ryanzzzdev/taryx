"""Deterministic demo seed: inspectable accounts, NMIs, channels, agreements."""

from datetime import date

from django.contrib.auth.models import Group, User

from taryx.core.accounts.models import (
    Account,
    MeterChannel,
    SupplyPoint,
    TariffAgreement,
)

DEFAULT_SPECS: list[
    tuple[
        str,
        str,
        str,
        list[tuple[str, str]],
        list[tuple[str, date, date | None]],
    ]
] = [
    (
        "ACC-001",
        "Meridian Heights Bakery",
        "4102000001",
        [("E1", "import"), ("B1", "export")],
        [("T-FLAT-FIT", date(2026, 1, 1), None)],
    ),
    (
        "ACC-002",
        "Collins Wharf Grocer",
        "4102000002",
        [("E1", "import")],
        [("T-TOU", date(2026, 1, 1), None)],
    ),
    (
        "ACC-003",
        "Harbour Lane Studio",
        "4102000003",
        [("E1", "import"), ("B1", "export")],
        [
            ("T-FLAT-FIT", date(2026, 1, 1), date(2026, 1, 15)),
            ("T-FLAT-FIT-HERITAGE", date(2026, 1, 15), None),
        ],
    ),
]


def seed_demo_data(specs=None) -> list[Account]:
    specs = DEFAULT_SPECS if specs is None else specs
    accounts = []
    for reference, name, nmi, channels, agreements in specs:
        account, _ = Account.objects.update_or_create(reference=reference, defaults={"name": name})
        supply, _ = SupplyPoint.objects.update_or_create(nmi=nmi, defaults={"account": account})
        for suffix, direction in channels:
            MeterChannel.objects.update_or_create(
                supply_point=supply,
                suffix=suffix,
                defaults={
                    "direction": direction,
                    "uom": "kWh",
                    "interval_minutes": 30,
                },
            )
        for version, (tariff_code, start, end) in enumerate(agreements, start=1):
            TariffAgreement.objects.update_or_create(
                account=account,
                effective_from=start,
                defaults={
                    "tariff_code": tariff_code,
                    "effective_to": end,
                    "version": version,
                },
            )
        accounts.append(account)
    return accounts


# Development-only operator identities (decision 004). Never real customers.
DEMO_USERS = {
    "viewer": "multipass",
    "operator": "multipass",
    "approver": "multipass",
}


def seed_operator_identities() -> list[User]:
    """Seed the viewer/operator/approver groups and one user each."""
    users = []
    for role, password in DEMO_USERS.items():
        group, _ = Group.objects.get_or_create(name=role)
        user, _ = User.objects.get_or_create(username=role)
        user.set_password(password)
        user.groups.set([group])
        user.save()
        users.append(user)
    return users
