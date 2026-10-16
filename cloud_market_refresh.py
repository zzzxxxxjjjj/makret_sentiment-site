"""Verifiable cloud replacements. No Wind terminal or workbook is queried."""
from __future__ import annotations
import json, os, ssl, urllib.request
from datetime import date,datetime,timedelta
from pathlib import Path
import pandas as pd
import rqdatac as rq
from rqdatac_fund import fund
from rqdata_connection import initialize_rqdata
from rqdata_trading_day import completed_trading_date
BASE=Path(__file__).resolve().parent
CHANGES=[
 '中期情绪云端版v2：万得全A改为中证全指000985；10年国开债收益率改为中债10年国债收益率；偏债混合基金指数改为上证国债指数000012。七因子算法与等权合成保持一致，历史按新口径重算，不拼接旧模型。',
 '基金发行：募集份额改为股票型公募基金（含股票指数型）新成立数量，主代码去重，近20个交易日累计，单位只。',
 '基金仓位：日频估算改为普通股票型基金定期报告的净资产加权股票比例，季频披露、每日检查，非每日估算。',
 '原万得全A换手率改为RQData全A等权日换手率；原机构净买入概览改为机构买入额MA5，买入额不代表净流入。',
 '陆股通成交总额MA5使用港交所沪股通与深股通官方总成交额，百万人民币除以100换算为亿元；不使用已停止披露的北向净买入。'
]
def read(name):
 try:return json.loads((BASE/name).read_text(encoding='utf-8-sig'))
 except (OSError,ValueError):return {}
def records(df,field,scale=1):
 if df is None or df.empty:return []
 result=[]
 for key,row in df.iterrows():
  dt=next((v for v in (key if isinstance(key,tuple) else [key]) if isinstance(v,(date,datetime,pd.Timestamp))),None)
  if dt is None:continue
  value=row[field]
  if pd.notna(value):result.append({'date':str(dt)[:10],'value':round(float(value)*scale,6)})
 return sorted(result,key=lambda x:x['date'])
def merge(old,new):return sorted({p['date']:p for p in [*old,*new]}.values(),key=lambda p:p['date'])
def fund_counts(meta,dates):
 selected=meta[meta.fund_type.isin(['Stock','StockIndex'])].copy()
 codes=selected.order_book_id.astype(str).tolist();mapping={}
 for i in range(0,len(codes),500):
  related=fund.get_related_code(codes[i:i+500])
  if related is not None:
   for row in related.to_dict('records'):mapping[str(row['related_code'])]=str(row['main_code'])
 selected['primary']=selected.order_book_id.astype(str).map(lambda c:mapping.get(c,c))
 selected['established']=pd.to_datetime(selected.establishment_date,errors='coerce')
 births=selected.groupby('primary').established.min().dropna()
 days=[pd.Timestamp(d) for d in dates]; output=[]
 # Map calendar establishment dates to the first trading session on or after establishment.
 import bisect
 buckets=[0]*len(days)
 for birth in births:
  pos=bisect.bisect_left(days,birth)
  if pos<len(days):buckets[pos]+=1
 for i,dt in enumerate(days):
  if i>=19:output.append({'date':str(dt.date()),'value':sum(buckets[i-19:i+1])})
 return output

def parse_hkex(text,expected):
 raw=text.strip()
 if not raw.startswith('tabData ='):raise ValueError('Unexpected HKEX response')
 channels=json.loads(raw.split('=',1)[1].strip().rstrip(';'))
 totals=[]
 for market in ('SSE Northbound','SZSE Northbound'):
  item=next((x for x in channels if x.get('market')==market and x.get('date')==expected),None)
  if not item or item.get('tradingDay')!=1:return None
  table=next(x['table'] for x in item['content'] if x.get('style')==1)
  if table['schema'][0][0]!='Total Turnover':raise ValueError('HKEX schema changed')
  totals.append(float(table['tr'][0]['td'][0][0].replace(',','')))
 return round(sum(totals)/100,6)
def hkex_history(dates,previous):
 cache=BASE/'.rqdata-cache'/'hkex';cache.mkdir(parents=True,exist_ok=True)
 import certifi
 context=ssl.create_default_context(cafile=certifi.where())
 output=list(previous)
 for dt in dates[-24:]:
  key=str(dt)[:10];path=cache/(key+'.json')
  if path.exists():item=json.loads(path.read_text());value=item.get('value')
  else:
   url='https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_'+key.replace('-','')+'e.js'
   request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
   try:
    with urllib.request.urlopen(request,context=context,timeout=25) as response:value=parse_hkex(response.read().decode('utf-8-sig'),key)
   except Exception:
    if key==str(dates[-1])[:10]:raise
    continue
   if value is not None:path.write_text(json.dumps({'date':key,'value':value}),encoding='utf-8')
  if value is not None:output=merge(output,[{'date':key,'value':value}])
 return output

def main():
 initialize_rqdata();target=os.environ.get('RQDATA_AS_OF') or completed_trading_date(rq).isoformat()
 old=read('cloud-market-inputs.json');oldseries=old.get('inputs',{})
 start=(date.fromisoformat(target)-timedelta(days=8)).isoformat() if old.get('asOf') else '2015-01-01'
 print('Cloud inputs: index valuations, prices and government yield',flush=True)
 valuation=rq.index_indicator('000985.XSHG',start_date=start,end_date=target,fields=['pe_ttm','dividend_yield_ttm'])
 prices=rq.get_price(['000985.XSHG','000012.XSHG'],start_date=start,end_date=target,fields=['close'],expect_df=True)
 curve=rq.get_yield_curve(start_date=start,end_date=target,tenor='10Y')
 incoming={'pe':records(valuation,'pe_ttm'),'dividend':records(valuation,'dividend_yield_ttm',100),'yield':records(curve,'10Y',100)}
 for code,name in [('000985.XSHG','equity'),('000012.XSHG','bond')]:incoming[name]=records(prices.xs(code,level='order_book_id'),'close')
 inputs={key:merge(oldseries.get(key,[]),points) for key,points in incoming.items()}
 if any(not points or points[-1]['date']!=target for points in inputs.values()):raise ValueError('Cloud medium inputs not complete for '+target)
 dates=rq.get_trading_dates('2015-01-01',target)
 print('Cloud inputs: public fund establishment metadata',flush=True)
 meta=fund.all_instruments(); counts=fund_counts(meta,dates)
 print('Cloud inputs: HKEX official northbound turnover',flush=True)
 errors=[]
 try:north=hkex_history(dates,old.get('northboundDaily',[]))
 except Exception as exc:
  north=old.get('northboundDaily',[])
  errors.append('港交所成交额暂未取得；保留实际旧日期，等待重试')
  print(errors[-1],flush=True)
 ma=[{'date':p['date'],'value':round(sum(x['value'] for x in north[i-4:i+1])/5,4)} for i,p in enumerate(north) if i>=4]
 output={'asOf':target,'modelVersion':'cloud-v2','methodologyChanges':CHANGES,'source':'RQData / 中债 / 港交所官方统计','inputs':inputs,'fundEstablishment20D':counts,'northboundDaily':north,'northboundMA5':ma,'sourceErrors':errors}
 path=BASE/'cloud-market-inputs.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(output,ensure_ascii=False),encoding='utf-8');tmp.replace(path)
 print(json.dumps({'asOf':target,'fundLast':counts[-1],'northboundLast':ma[-1] if ma else None}))
if __name__=='__main__':main()
