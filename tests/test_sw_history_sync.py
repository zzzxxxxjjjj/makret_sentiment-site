import copy,unittest
from datetime import date,timedelta
from types import SimpleNamespace
from unittest.mock import patch
from sw_history_sync import synchronize
from sw_flow_api import history as get_history

class WindowTests(unittest.TestCase):
 def setUp(self):
  self.dates=[];d=date(2026,9,1)
  while len(self.dates)<23:
   if d.weekday()<5:self.dates.append(d.isoformat())
   d+=timedelta(days=1)
  self.rows=lambda v:[dict(code=str(801000+i),name="industry"+str(i),covered=10,total=10,value=v+i) for i in range(30)]
  self.original=dict(available=True,asOf=self.dates[19],days=[dict(date=d,rows=self.rows(i)) for i,d in enumerate(self.dates[:20])])
 def close(self,i,source="AKShare / Eastmoney"):
  return dict(date=self.dates[i],rows=self.rows(i),completedSession=True,source=source)
 def test_advances_only_with_consecutive_twenty_sessions(self):
  old=copy.deepcopy(self.original)
  out,archive,status=synchronize(self.original,dict(snapshots=[self.close(20),self.close(21)]),self.dates,self.dates[21])
  self.assertTrue(status["complete"]);self.assertEqual(out["asOf"],self.dates[21])
  self.assertEqual([d["date"] for d in out["days"]],self.dates[2:22])
  self.assertEqual(len(archive["days"]),22);self.assertEqual(self.original,old)
 def test_gap_does_not_become_zero_or_skip_a_session(self):
  out,archive,status=synchronize(self.original,dict(snapshots=[self.close(21)]),self.dates,self.dates[21])
  self.assertFalse(status["complete"]);self.assertEqual(status["missingDates"],[self.dates[20]])
  self.assertEqual(out["asOf"],self.dates[19]);self.assertEqual(status["latestObservedDate"],self.dates[21])
  self.assertNotIn(self.dates[20],{d["date"] for d in archive["days"]})
 def test_different_main_money_classification_is_not_spliced(self):
  out,_,status=synchronize(self.original,dict(snapshots=[self.close(20,"iFind"),self.close(21,"iFind")]),self.dates,self.dates[21])
  self.assertEqual(out["asOf"],self.dates[19]);self.assertEqual(len(status["missingDates"]),2)
 def test_intraday_record_is_not_a_close(self):
  point=self.close(20);point["completedSession"]=False
  out,_,_=synchronize(self.original,dict(snapshots=[point]),self.dates,self.dates[20])
  self.assertEqual(out["asOf"],self.dates[19])
 def test_archive_is_not_trimmed_when_outside_display_window(self):
  future=self.close(22)
  out,archive,_=synchronize(self.original,{},self.dates,self.dates[21],dict(days=[future]))
  self.assertIn(self.dates[22],{d["date"] for d in archive["days"]})
  self.assertEqual(out["asOf"],self.dates[19])
 def test_date_rollback_is_rejected(self):
  with self.assertRaises(ValueError):synchronize(self.original,{},self.dates,self.dates[18])

class AdapterTests(unittest.TestCase):
 def test_new_symbol_parameter(self):
  provider=SimpleNamespace(stock_fund_flow_individual_hist_em=lambda symbol,market:(symbol,market))
  self.assertEqual(get_history(provider,"600036","sh"),("600036","sh"))
 def test_legacy_stock_parameter(self):
  provider=SimpleNamespace(stock_individual_fund_flow=lambda stock,market:(stock,market))
  self.assertEqual(get_history(provider,"000001","sz"),("000001","sz"))

if __name__=="__main__":unittest.main()
