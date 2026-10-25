"""Deterministic demo seed: inspectable accounts, NMIs, channels, agreements."""

from datetime import date

from taryx.core.accounts.models import (
    Account,
    MeterChannel,
    SupplyPoint,
    TariffAgreement,
)


def seed_demo_data() -> list[Account]:
    specs: list[
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
                ("T-FLAT-FIT-V2", date(2026, 1, 15), None),
            ],
        ),
    ]
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
