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
def test_conflict_after_rating_blocks_issue():
 a,r=setup('day1_rev2.nem12');op=admit(a,r)
 rows=(F/'day1_conflict.nem12').read_text().splitlines()
 second=next((i for i,row in enumerate(rows) if i>1 and row.startswith('200,')),len(rows)-1)
 rows=rows[:second]+['900']
 for i,row in enumerate(rows):
  if row.startswith('300,'):
   fields=row.split(',');fields[2:50]=['0.9']*48;rows[i]=','.join(fields)
 ingest_nem12_content(('\n'.join(rows)).encode(),'conflict-e1-only')
 result=process_operation(op.operation_id,digest_resolver=digest_resolver)
 assert result.status!='complete', 'Issued despite open quarantine created after rating'
 assert not Invoice.objects.exists()

@pytest.mark.django_db(transaction=True)
def test_changed_inputs_during_issuance_block_commit():
 a,r=setup();op=admit(a,r)
 def resolver(*args):
  digest=digest_resolver(*args)
  def change():
   close_old_connections()
   try:ingest('day1_rev1.nem12')
   finally:close_old_connections()
  with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(change).result(timeout=15)
  return digest
 result=process_operation(op.operation_id,digest_resolver=resolver)
 assert result.status!='complete', 'Input revision committed after digest check but before issuance'

@pytest.mark.django_db(transaction=True)
def test_net_credit_invoice_can_be_posted():
 seed_demo_data();lines=(F/'day1_base.nem12').read_text().splitlines();export=False
 for i,line in enumerate(lines):
  if line.startswith('200,'):export=line.split(',')[4]=='B1'
  if line.startswith('300,') and export:
   row=line.split(',');row[2:50]=['10']*48;lines[i]=','.join(row)
 ingest_nem12_content('\n'.join(lines).encode(),'high-export')
 a=Account.objects.get(reference='ACC-001');r=rate_account(a,DAY,END,**KW)
 assert r.total<0
 result=process_operation(admit(a,r).operation_id,digest_resolver=digest_resolver)
 assert result.status=='complete'

@pytest.mark.django_db(transaction=True)
def test_posted_rating_lines_are_immutable():
 a,r=setup();process_operation(admit(a,r).operation_id,digest_resolver=digest_resolver)
 with pytest.raises(DbError),transaction.atomic():
  RatingLine.objects.filter(run=r,element='import').update(quantity=999,amount=999)

@pytest.mark.django_db(transaction=True)
def test_cannot_append_to_posted_journal():
 a,r=setup();op=process_operation(admit(a,r).operation_id,digest_resolver=digest_resolver)
 journal=JournalEntry.objects.get(invoice=op.invoice)
 with pytest.raises(DbError),transaction.atomic():
  Posting.objects.create(journal=journal,account_code='1100',debit=1)
  Posting.objects.create(journal=journal,account_code='4000',credit=1)

@pytest.mark.django_db(transaction=True)
def test_retry_original_graphql_request_after_rerating():
 a,r=setup();seed_operator_identities();c=Client();c.login(username='operator',password='taryx-operator')
 query='mutation{billAccount(reference:"ACC-001",periodStart:"2026-03-02",periodEnd:"2026-03-03",operationId:"stable-request"){ok code operation{operationId}}}'
 def request():return c.post('/graphql',data=json.dumps({'query':query}),content_type='application/json').json()['data']['billAccount']
 with patch('taryx.interfaces.graphql.schema.process_billing_operation.delay'):
  first=request();assert first['ok']
  rate_account(a,DAY,END,**KW)
  retry=request()
 assert retry['ok'],retry
 assert retry['operation']==first['operation']
