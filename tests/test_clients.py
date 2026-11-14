"""Client policy isolation: two retailers, one image, distinct policies.

Cross-database/broker isolation is exercised by the deployment tests;
here the policy-selection contract is verified: startup configuration
chooses the client, identical inputs price differently, and demo seeds
use deliberately overlapping identifiers.
"""

from datetime import date
from pathlib import Path

import pytest

from taryx.core.accounts.seed import seed_demo_data
from taryx.core.metering.ingestion import ingest_nem12_content
from taryx.core.pricing.services import rate_account
from taryx.territories.au_nem.tariffs import GST_RATE

DAY = date(2026, 3, 2)
NEXT = date(2026, 3, 3)


def _policy(client: str, monkeypatch):
    from taryx.composition import policy as resolver

    monkeypatch.setenv("TARYX_CLIENT", client)
    resolver.selected_client_id.cache_clear()
    resolver.policy.cache_clear()
    module = resolver.policy()
    yield module
    resolver.selected_client_id.cache_clear()
    resolver.policy.cache_clear()


@pytest.fixture
def aurora(monkeypatch):
    yield from _policy("aurora_energy", monkeypatch)


@pytest.fixture
def southgrid(monkeypatch):
    yield from _policy("southgrid_retail", monkeypatch)


def test_default_client_is_aurora(monkeypatch):
    from taryx.composition import policy as resolver

    monkeypatch.delenv("TARYX_CLIENT", raising=False)
    resolver.selected_client_id.cache_clear()
    resolver.policy.cache_clear()
    assert resolver.selected_client_id() == "aurora_energy"
    assert resolver.policy().CLIENT_NAME == "Aurora Energy"


def test_unknown_client_fails_at_startup(monkeypatch):
    from taryx.composition import policy as resolver

    monkeypatch.setenv("TARYX_CLIENT", "not_a_client")
    resolver.selected_client_id.cache_clear()
    resolver.policy.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="unknown TARYX_CLIENT"):
            resolver.policy()
    finally:
        resolver.selected_client_id.cache_clear()
        resolver.policy.cache_clear()


def test_policies_price_identical_inputs_differently(db, aurora, southgrid, tmp_path):
    """The same seeded account, NEM12 file and period produce different
    totals and digests under each client's catalogue."""
    seed_demo_data()
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "nem12" / "day1_base.nem12"
    ).read_bytes()
    ingest_nem12_content(fixture, "day1_base.nem12")
    from taryx.core.accounts.models import Account

    account = Account.objects.get(reference="ACC-001")
    runs = {}
    for module in (aurora, southgrid):
        runs[module.CLIENT_ID] = rate_account(
            account,
            DAY,
            NEXT,
            tariffs=module.TARIFFS,
            gst_rate=GST_RATE,
            policy_identity=module.POLICY_IDENTITY,
        )
    a, b = runs["aurora_energy"], runs["southgrid_retail"]
    assert a.total != b.total
    assert a.input_digest != b.input_digest
    assert a.policy_identity != b.policy_identity


def test_southgrid_demo_specs_overlap_aurora_identifiers(db, aurora, southgrid):
    """Distinct businesses under deliberately overlapping references and
    NMIs — a cross-client lookup would resolve a valid-looking ID."""
    aurora_accounts = {a.reference for a in seed_demo_data()}
    southgrid_accounts = {a.reference for a in seed_demo_data(southgrid.DEMO_SPECS)}
    assert aurora_accounts == southgrid_accounts
    names = {a.reference: a.name for a in seed_demo_data(southgrid.DEMO_SPECS)}
    assert names["ACC-001"] != "Meridian Heights Bakery"
