import json, unittest
from datetime import datetime
import pandas as pd
from unittest.mock import patch
from cloud_market_refresh import parse_hkex, records, fund_counts
class CloudMarketTests(unittest.TestCase):
 def test_hkex_two_channels_million_to_yi_and_holiday(self):
  def channel(market,value):return {'market':market,'date':'2026-10-15','tradingDay':1,'content':[{'style':1,'table':{'schema':[['Total Turnover']], 'tr':[{'td':[[value]]}]}}]}
  rows=[channel('SSE Northbound','100,000'),channel('SZSE Northbound','200,000')]
  self.assertEqual(parse_hkex('tabData = '+json.dumps(rows)+';','2026-10-15'),3000)
  rows[1]['tradingDay']=0
  self.assertIsNone(parse_hkex('tabData = '+json.dumps(rows),'2026-10-15'))
  with self.assertRaises(ValueError):parse_hkex('alert(1)','2026-10-15')
 def test_fractional_dividend_and_yield_conversion(self):
  df=pd.DataFrame({'dividend':[.017]},index=pd.to_datetime(['2026-10-15']))
  self.assertEqual(records(df,'dividend',100),[{'date':'2026-10-15','value':1.7}])
 def test_fund_share_classes_deduped_and_twenty_trading_day_window(self):
  meta=pd.DataFrame({'fund_type':['Stock','StockIndex','Bond'],'order_book_id':['a','b','c'],'establishment_date':['2026-01-03','2026-01-05','2026-01-05']})
  mapping=pd.DataFrame({'related_code':['a','b'],'main_code':['a','a']})
  dates=pd.bdate_range('2025-12-01','2026-02-27').date
  with patch('cloud_market_refresh.fund.get_related_code',return_value=mapping):out=fund_counts(meta,dates)
  self.assertEqual(next(p['value'] for p in out if p['date']=='2026-01-05'),1)
  self.assertEqual(out[-1]['value'],0)

 def test_replacement_does_not_stitch_legacy_values(self):
  import tempfile
  from pathlib import Path
  from cloud_display import apply_cloud_display
  with tempfile.TemporaryDirectory() as tmp:
   new=[{'date':'2026-10-15','value':1}]
   cloud={'modelVersion':'cloud-v2','asOf':'2026-10-15','inputs':{'equity':new},'fundEstablishment20D':new,'northboundMA5':new,'methodologyChanges':['changed']}
   Path(tmp,'cloud-market-inputs.json').write_text(json.dumps(cloud))
   payload={'cards':[],'series':[{'id':'new-equity-fund-shares','points':[{'date':'2020-01-01','value':999}]}]}
   result=apply_cloud_display(payload,tmp)
   series=next(s for s in result['series'] if s['id']=='new-equity-fund-shares')
   self.assertEqual(series['points'],new)
   self.assertEqual(series['unit'],'只')
   self.assertEqual(result['methodologyChanges'],['changed'])
