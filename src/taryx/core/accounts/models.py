from django.db import models


class Account(models.Model):
    reference = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=200)

    def __str__(self) -> str:
        return f"{self.reference} {self.name}"


class SupplyPoint(models.Model):
    class MarketState(models.TextChoices):
        NONE = "none"
        PENDING = "pending"
        REGISTERED = "registered"

    nmi = models.CharField("NMI", max_length=10, unique=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="supply_points")
    # Written only by the validating core consumer — never by the
    # counterparty-facing adapter code directly (decision 005).
    market_state = models.CharField(
        max_length=16, choices=MarketState.choices, default=MarketState.NONE
    )
    # Correlation of the transfer currently pending on this point —
    # the per-correlation dedup that stops a stale outbox delivery
    # from reapplying an old completion over a newer transfer.
    pending_transfer_id = models.UUIDField(null=True)

    def __str__(self) -> str:
        return self.nmi


class MeterChannel(models.Model):
    class Direction(models.TextChoices):
        IMPORT = "import"
        EXPORT = "export"

    supply_point = models.ForeignKey(SupplyPoint, on_delete=models.CASCADE, related_name="channels")
    suffix = models.CharField(max_length=4)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    uom = models.CharField(max_length=8, default="kWh")
    interval_minutes = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["supply_point", "suffix"], name="uniq_channel_suffix")
        ]

    def __str__(self) -> str:
        return f"{self.supply_point.nmi}:{self.suffix}"


class TariffAgreement(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="tariff_agreements")
    tariff_code = models.CharField(max_length=32)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "effective_from"],
                name="uniq_agreement_account_from",
            )
        ]

    def __str__(self) -> str:
        return f"{self.account.reference}:{self.tariff_code} v{self.version}"
