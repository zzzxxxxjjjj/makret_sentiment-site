from pathlib import Path
import sys,json,datetime,concurrent.futures
ROOT=Path(__file__).resolve().parent

import akshare as ak,pandas as pd,requests
original=requests.sessions.Session.request
def bounded(self,method,url,**kw):
 kw.setdefault('timeout',(6,12));return original(self,method,url,**kw)
requests.sessions.Session.request=bounded
INDUSTRY_NAMES = {'801010.SL': '农林牧渔', '801030.SL': '基础化工', '801040.SL': '钢铁', '801050.SL': '有色金属', '801080.SL': '电子', '801110.SL': '家用电器', '801120.SL': '食品饮料', '801130.SL': '纺织服饰', '801140.SL': '轻工制造', '801150.SL': '医药生物', '801160.SL': '公用事业', '801170.SL': '交通运输', '801180.SL': '房地产', '801200.SL': '商贸零售', '801210.SL': '社会服务', '801710.SL': '建筑材料', '801720.SL': '建筑装饰', '801730.SL': '电力设备', '801740.SL': '国防军工', '801750.SL': '计算机', '801760.SL': '传媒', '801770.SL': '通信', '801780.SL': '银行', '801790.SL': '非银金融', '801880.SL': '汽车', '801890.SL': '机械设备', '801950.SL': '煤炭', '801960.SL': '石油石化', '801970.SL': '环保', '801980.SL': '美容护理'}
ASSETS=[('红利','510880'),('大盘·沪深300','510300'),('中盘·中证500','510500'),('小盘·中证1000','512100'),('创业板','159915'),('科创50','588000'),('恒生科技','513180'),('黄金','518880'),('利率债·国债','511010'),('信用债·公司债','511030'),('美债·20年以上（美元）','TLT')]
ASSETS.append(('布伦特原油期货（美元）','OIL'))

def fetch(item):
 name,code,kind=item
 cache=ROOT/'correlation-cache'/f'{code}.json';cache.parent.mkdir(exist_ok=True)
 try:
  if kind=='industry':
   old=ROOT/'factor-research'/'inputs'/'sectors'/f'{code}.json'
   df=pd.DataFrame(json.loads(old.read_text(encoding='utf-8'))['rows']) if old.exists() and datetime.datetime.fromtimestamp(old.stat().st_mtime).date()==datetime.date.today() else ak.index_hist_sw(symbol=code,period='day')
  elif code=='TLT':
   df=ak.stock_us_daily(symbol='TLT',adjust='qfq').rename(columns={'date':'日期','close':'收盘'})
  elif code=='OIL':
   df=ak.futures_foreign_hist(symbol='OIL').rename(columns={'date':'日期','close':'收盘'})
   today=datetime.datetime.now(datetime.timezone.utc).date()
   df=df[pd.to_datetime(df['日期']).dt.date<today]
  else: df=ak.fund_etf_hist_em(symbol=code,start_date='20200101',adjust='qfq')
  date='日期';close='收盘'
  series=pd.Series(pd.to_numeric(df[close],errors='coerce').values,index=pd.to_datetime(df[date]).dt.strftime('%Y-%m-%d')).dropna()
  series=series[~series.index.duplicated()].sort_index();series=series[series>0]
  source='AKShare '+('index_hist_sw' if kind=='industry' else 'stock_us_daily 美元前复权' if code=='TLT' else 'fund_etf_hist_em 前复权')
  if code=='OIL':
   series=series[series.index>='2020-01-01']
   if series.empty: raise ValueError('布伦特原油历史收盘价为空')
   source='AKShare / 新浪财经 OIL 连续期货日收盘价（美元/桶，含换月影响）'
  result={'name':name,'code':code,'kind':kind,'prices':dict(zip(series.index,series.values)),'source':source,'status':'available'}
  cache.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');return result
 except Exception as e:
  if cache.exists(): return json.loads(cache.read_text(encoding='utf-8'))
  if code=='OIL':
   snapshot=ROOT/'correlation-data.json'
   if snapshot.exists():
    for row in json.loads(snapshot.read_text(encoding='utf-8'))['series']:
     if row['code']==code and row['prices']: return row
  return {'name':name,'code':code,'kind':kind,'prices':{},'status':'unavailable','error':str(e)[:180]}
if __name__=='__main__':
 jobs=[(n,c,'asset') for n,c in ASSETS]+[(n,c[:6],'industry') for c,n in INDUSTRY_NAMES.items() if c.endswith('.SL') and n!='综合']
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: rows=list(pool.map(fetch,jobs))
 output={'updatedAt':datetime.datetime.now().isoformat(),'series':rows}
 (ROOT/'correlation-data.json').write_text(json.dumps(output,ensure_ascii=False),encoding='utf-8')
 print([(r['name'],len(r['prices'])) for r in rows])


