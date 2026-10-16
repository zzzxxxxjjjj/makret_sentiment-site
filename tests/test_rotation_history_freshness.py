import tempfile, unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch
import json
import pandas as pd
import rotation_history_refresh as rotation
import rqdata_history_cache as cache
from data_freshness import build_report

class RotationHistoryTests(unittest.TestCase):
 def frame(self):
  dates=pd.bdate_range(end='2026-10-15',periods=30)
  rows=[{'date':dt,'order_book_id':code,'close':100.} for dt in dates for code in [*rotation.INDUSTRIES,rotation.BENCHMARK]]
  return pd.DataFrame(rows),dates
 def test_unchanged_tied_returns_have_zero_rotation(self):
  frame,dates=self.frame()
  result=rotation.calculate(frame,dates,date(2026,10,15))
  self.assertTrue(all(p['value']==0 for p in result))
  self.assertEqual(result[-1]['industries'],29)
 def test_two_industries_leave_tied_middle(self):
  frame,dates=self.frame()
  codes=list(rotation.INDUSTRIES)
  frame.loc[(frame.date==dates[-1]) & (frame.order_book_id==codes[0]),'close']=110.
  frame.loc[(frame.date==dates[-1]) & (frame.order_book_id==codes[1]),'close']=90.
  self.assertEqual(rotation.calculate(frame,dates,date(2026,10,15))[-1]['value'],28.)
 def test_missing_benchmark_never_claims_target_date(self):
  frame,dates=self.frame()
  frame=frame[~((frame.date==dates[-1]) & (frame.order_book_id==rotation.BENCHMARK))]
  with self.assertRaisesRegex(ValueError,'target trading date'):
   rotation.calculate(frame,dates,date(2026,10,15))

class HistoryCacheTests(unittest.TestCase):
 def test_daily_fetch_uses_overlap_and_refreshes_revised_values(self):
  class Provider:
   def __init__(self):self.calls=[]
   def get_price(self, ids, start_date, end_date, **kw):
    self.calls.append((start_date,end_date))
    index=pd.MultiIndex.from_product([ids,pd.date_range(start_date,end_date)],names=['order_book_id','date'])
    return pd.DataFrame({'close':float(len(self.calls))},index=index)
  with tempfile.TemporaryDirectory() as temporary, patch.object(cache,'CACHE',Path(temporary)):
   rq=Provider()
   cache.history(rq,'get_price',['A'],date(2026,1,1),date(2026,10,14),fields=['close'])
   data=cache.history(rq,'get_price',['A'],date(2026,1,1),date(2026,10,15),fields=['close'])
   self.assertGreater(rq.calls[-1][0],date(2026,10,1))
   self.assertEqual(data.loc[('A',pd.Timestamp('2026-10-15')),'close'],2.)
   self.assertFalse(data.index.duplicated().any())

class FreshnessTests(unittest.TestCase):
 def test_top_level_date_does_not_hide_late_industry_margin_data(self):
  from rqdata_daily_update import snapshot_current
  value={'asOf':'2026-10-15','industries':[{'name':'银行','valuationAsOf':'2026-10-15','series':[{'date':'2026-10-15','netFlow':0,'marginActivity':None,'amountShare':3}]}]}
  self.assertFalse(snapshot_current('rqdata-industry-sentiment.json',value,'2026-10-15'))
  value['industries'][0]['series'][0]['marginActivity']=0
  self.assertTrue(snapshot_current('rqdata-industry-sentiment.json',value,'2026-10-15'))

 def test_series_tail_and_slowest_industry_control_readiness(self):
  with tempfile.TemporaryDirectory() as temporary:
   directory=Path(temporary)
   (directory/'broad-sentiment-page-cache.json').write_text(json.dumps({'payload':{'asOf':'2026-10-15','series':[{'id':'financing-net','points':[{'date':'2026-10-14','value':1}]}]}}))
   (directory/'rqdata-industry-sentiment.json').write_text(json.dumps({'asOf':'2026-10-15','industries':[{'name':'A','series':[{'date':'2026-10-14','netFlow':0,'marginActivity':1,'amountShare':1}]}]}))
   report=build_report('2026-10-15',directory)
   self.assertFalse(report['allDailyCurrent'])
   self.assertEqual(next(e for e in report['entries'] if e['id']=='netFlow')['asOf'],'2026-10-14')
   self.assertTrue(any(e['id']=='financing-net' for e in report['laggingDaily']))

if __name__=='__main__':unittest.main()
