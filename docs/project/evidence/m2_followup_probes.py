from pathlib import Path
from datetime import date
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import json
import pytest
from django.db import close_old_connections, transaction, Error as DbError
from django.test import Client
from taryx.core.accounts.seed import seed_demo_data, seed_operator_identities
from taryx.core.accounts.models import Account
from taryx.core.metering.ingestion import ingest_nem12_content
from taryx.core.pricing.services import rate_account
from taryx.core.pricing.models import RatingLine
from taryx.core.billing.services import admit_issue, process_operation
from taryx.core.billing.models import Invoice, Posting, JournalEntry
from taryx.composition.tasks import digest_resolver
from taryx.territories.au_nem.tariffs import TARIFFS,GST_RATE,POLICY_IDENTITY
F=Path(__file__).resolve().parents[3] / 'tests/fixtures/nem12'
DAY=date(2026,3,2);END=date(2026,3,3)
KW=dict(tariffs=TARIFFS,gst_rate=GST_RATE,policy_identity=POLICY_IDENTITY)
def ingest(n):return ingest_nem12_content((F/n).read_bytes(),n)
def setup(n='day1_base.nem12'):
 seed_demo_data();ingest('day1_base.nem12');ingest(n);a=Account.objects.get(reference='ACC-001')
 return a,rate_account(a,DAY,END,**KW)
def admit(a,r,key='review'):return admit_issue(a,DAY,END,r,key)


@pytest.mark.django_db(transaction=True)
def test_no_append_rating_evidence():
 a,r=setup();process_operation(admit(a,r).operation_id,digest_resolver=digest_resolver)
 line=r.lines.first();line.pk=None;line.sequence=999
 with pytest.raises(DbError),transaction.atomic():line.save(force_insert=True)

@pytest.mark.django_db(transaction=True)
def test_tariff_window_changes_digest():
 from dataclasses import replace
 from datetime import time
 from taryx.core.pricing.services import compute_input_digest
 a,r=setup()
 changed={code:replace(spec,import_bands=tuple(replace(b,window=(time(1),time(2))) for b in spec.import_bands)) for code,spec in TARIFFS.items()}
 other=compute_input_digest(a,DAY,END,tariffs=changed,gst_rate=GST_RATE,policy_identity=POLICY_IDENTITY)
 assert other!=r.input_digest,'Band time windows are missing from snapshot/digest'
