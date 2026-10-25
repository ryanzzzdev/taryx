from pathlib import Path
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Barrier, current_thread
from unittest.mock import patch
import pytest
from django.db import close_old_connections
from taryx.core.accounts.seed import seed_demo_data
from taryx.core.accounts.models import MeterChannel
from taryx.core.metering.nem12 import parse_nem12, Nem12Error
from taryx.core.metering.ingestion import ingest_nem12_content, channel_coverage
from taryx.core.metering.models import CurrentInterval, IntervalRecord
from taryx.core.metering import ingestion
F=Path(__file__).resolve().parents[3] / 'tests/fixtures/nem12'
def fixture(n): return (F/n).read_text()
def lines300(s): return [l for l in s.splitlines() if l.startswith('300,')]
def change(s,func):
 lines=s.splitlines()
 for i,l in enumerate(lines):
  if l.startswith('300,'):
   row=l.split(',');func(row);lines[i]=','.join(row)
 return '\n'.join(lines)+'\n'

def test_standard_quality_method():
 s=change(fixture('day2_est.nem12'),lambda r:r.__setitem__(-5,'E52'))
 parse_nem12(s)

def test_standard_400_ranges():
 s=fixture('day5_var.nem12')
 rows=[r for r in s.splitlines() if not r.startswith('400,')]
 rows.insert(-1,'400,1,24,A,,')
 rows.insert(-1,'400,25,48,E52,,')
 parse_nem12('\n'.join(rows))

@pytest.mark.parametrize('value',['-0.5','NaN','Infinity','1e2'])
def test_invalid_numeric_is_rejected(value):
 s=change(fixture('day1_base.nem12'),lambda r:r.__setitem__(2,value))
 with pytest.raises(Nem12Error):parse_nem12(s)

def test_truncated_300_stable_error():
 rows=fixture('day1_base.nem12').splitlines()
 rows[2]='300'
 with pytest.raises(Nem12Error):parse_nem12('\n'.join(rows))

@pytest.mark.django_db(transaction=True)
def test_newer_revision_clears_obsolete_conflict():
 seed_demo_data()
 for n in ['day1_rev2.nem12','day1_conflict.nem12']:
  ingest_nem12_content((F/n).read_bytes(),n)
 s=change(fixture('day1_rev2.nem12'),lambda r:(r.__setitem__(-1,'20260310000000'),r.__setitem__(-2,'20260310000000')))
 ingest_nem12_content(s.encode(),'newer')
 ch=MeterChannel.objects.get(supply_point__nmi='4102000001',suffix='E1')
 cov=channel_coverage(ch,date(2026,3,2),date(2026,3,3))
 assert cov.complete, cov

@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_batches_are_noops():
 seed_demo_data();barrier=Barrier(2);original=ingestion.parse_nem12
 def parse(s):
  out=original(s);barrier.wait(timeout=10);return out
 def run():
  close_old_connections()
  try:return ingest_nem12_content((F/'day1_base.nem12').read_bytes(),'concurrent').batch.status
  finally:close_old_connections()
 with patch.object(ingestion,'parse_nem12',parse),ThreadPoolExecutor(max_workers=2) as ex:
  futures=[ex.submit(run) for _ in range(2)]
  outcomes=[]
  for f in futures:
   try:outcomes.append(f.result(timeout=20))
   except Exception as e:outcomes.append(type(e).__name__)
 assert sorted(outcomes)==['duplicate','published'],outcomes

@pytest.mark.django_db(transaction=True)
def test_concurrent_revisions_do_not_regress_current():
 seed_demo_data();ingest_nem12_content((F/'day1_base.nem12').read_bytes(),'base')
 low_read=Event();high_done=Event();original=ingestion.select_current
 # One-channel, one-day files so both publishers affect exactly the same keys.
 base=fixture('day1_base.nem12').splitlines()
 second=next(i for i,r in enumerate(base) if i>1 and r.startswith('200,'))
 base='\n'.join(base[:second]+['900'])
 def revision(value,stamp):
  def edit(r):
   r[2:50]=[value]*48;r[-1]=stamp;r[-2]=stamp
  return change(base,edit).encode()
 def select(records):
  result=original(records)
  if current_thread().name.endswith('_0') and not low_read.is_set():
   low_read.set();assert high_done.wait(15)
  return result
 def low():
  close_old_connections()
  try:return ingest_nem12_content(revision('0.6','20260305000000'),'low')
  finally:close_old_connections()
 def high():
  close_old_connections()
  try:
   assert low_read.wait(10)
   return ingest_nem12_content(revision('0.8','20260306000000'),'high')
  finally:high_done.set();close_old_connections()
 with patch.object(ingestion,'select_current',select),ThreadPoolExecutor(max_workers=2) as ex:
  a=ex.submit(low);b=ex.submit(high);a.result(timeout=25);b.result(timeout=25)
 vals=set(CurrentInterval.objects.filter(channel__suffix='E1').values_list('value',flat=True))
 from decimal import Decimal
 assert vals=={Decimal('0.8')},vals
