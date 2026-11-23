"""AKShare-only rotation, fixed SW2021 universe of 30 (excluding composite)."""
import json
import os
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

ROOT=Path(__file__).resolve().parent


def calculate(prices, benchmark, calendar):
    if prices.shape[1]!=30:raise ValueError('Expected exactly 30 SW industries')
    prices=prices.reindex(pd.to_datetime(calendar))
    returns=prices.pct_change(5,fill_method=None)
    ranks=returns.rank(axis=1,ascending=False,method='average')
    changes=(ranks-ranks.shift(1)).abs()
    valid=returns.notna().all(axis=1)&returns.shift(1).notna().all(axis=1)
    values=changes.sum(axis=1).where(valid).dropna()
    points=[]
    for day,value in values.items():
        if day in benchmark.index and pd.notna(benchmark.loc[day]):
            points.append(dict(date=str(day.date()),value=round(float(value),2),indexClose=float(benchmark.loc[day]),industries=30))
    if len(points)<50:raise ValueError('Insufficient common SW history')
    return points


def main():
    import akshare as ak
    import requests
    original=requests.sessions.Session.request
    def bounded(self,method,url,**kwargs):
        kwargs['timeout']=(5,15)
        return original(self,method,url,**kwargs)
    requests.sessions.Session.request=bounded
    members=json.loads((ROOT/'sw-flow-members.json').read_text(encoding='utf-8'))['members']
    if len(members)!=30 or any(m['name']=='综合' for m in members):raise ValueError('Invalid SW universe')
    now=datetime.now(ZoneInfo('Asia/Shanghai'));limit=now.date() if now.hour>=18 else now.date()-timedelta(days=1)
    pinned=os.environ.get('DAILY_TARGET_DATE')
    if pinned:
        from datetime import date
        requested=date.fromisoformat(pinned)
        if requested>limit:raise ValueError('Requested date is not completed')
        limit=requested
    calendar=[str(d) for d in (getattr(ak,'calendar_trade_date_hist_sina',None) or ak.tool_trade_date_hist_sina)()['trade_date'] if str(d)<=limit.isoformat()]
    target=calendar[-1]
    from ifind_client import Client
    from threading import Lock
    fallback=Client()
    fallback_lock=Lock()
    provenance={}
    def one(m):
        last=None
        for _ in range(1):
            try:
                df=ak.index_hist_sw(symbol=m['code'],period='day')
                s=pd.Series(pd.to_numeric(df['收盘'],errors='coerce').to_numpy(),index=pd.to_datetime(df['日期']))
                if s.index.duplicated().any():raise ValueError('Duplicated SW price dates')
                s=s.sort_index().loc[:target]
                if str(s.index[-1])[:10]!=target:raise ValueError('Stale SW close: '+m['name'])
                provenance[m['code']]='AKShare / 申万'
                print('AKShare verified '+m['code']+' '+str(s.index[-1])[:10],flush=True)
                return m['code'],s
            except Exception as exc:
                last=exc
                print('AKShare fallback '+m['code']+' '+type(exc).__name__,flush=True)
        if not os.environ.get('IFIND_REFRESH_TOKEN'):
            raise RuntimeError('SW price fetch failed: '+m['name']) from last
        from datetime import date
        observations={}
        # Bound requests by calendar year to avoid large provider timeouts.
        for year in range(max(2015,limit.year-5),limit.year+1):
            first=str(date(year,1,1))
            last_day=min(target,str(date(year,12,31)))
            with fallback_lock:
                data=fallback.post('cmd_history_quotation',{'codes':m['code']+'.SL','indicators':'close',
                    'startdate':first,'enddate':last_day,'functionpara':{'Fill':'Omit'}})
            table=next((t for t in data.get('tables',[]) if t.get('thscode')==m['code']+'.SL'),None)
            if not table:raise ValueError('Missing matching iFind SW code: '+m['code']+' '+str(year))
            dates=table.get('time') or []
            closes=(table.get('table') or {}).get('close') or []
            if len(dates)!=len(closes):raise ValueError('Mismatched iFind history: '+m['code'])
            observations.update(zip(dates,closes))
        table={'time':sorted(observations),'table':{'close':[observations[d] for d in sorted(observations)]}}
        values=pd.to_numeric(pd.Series((table.get('table') or {}).get('close',[])),errors='coerce')
        dates=pd.to_datetime(table.get('time') or [])
        if len(values)!=len(dates):raise ValueError('Mismatched iFind dates and values')
        series=pd.Series(values.to_numpy(),index=dates).sort_index().loc[:target]
        if series.index.duplicated().any() or series.empty or str(series.index[-1])[:10]!=target or series.isna().any() or (series<=0).any():
            raise ValueError('Incomplete iFind SW history: '+m['code'])
        provenance[m['code']]='iFind / '+m['code']+'.SL'
        print('iFind verified '+m['code']+' '+str(series.index[-1])[:10],flush=True)
        return m['code'],series
    with ThreadPoolExecutor(max_workers=2) as pool:prices=pd.DataFrame(dict(pool.map(one,members)))
    start=max(str(prices.index.min().date()),str(limit.replace(year=limit.year-10)))
    raw=(getattr(ak,'index_hist_csindex',None) or ak.stock_zh_index_hist_csindex)(symbol='000985',start_date=start.replace('-',''),end_date=target.replace('-',''))
    benchmark=pd.Series(pd.to_numeric(raw['收盘'],errors='coerce').to_numpy(),index=pd.to_datetime(raw['日期'])).sort_index()
    sessions=[d for d in calendar if start<=d<=target]
    points=calculate(prices,benchmark,sessions)
    if points[-1]['date']!=target:raise ValueError('Rotation history does not reach target')
    payload=dict(priceSources=provenance,asOf=target,generatedAt=now.isoformat(),source='AKShare优先 / iFind同代码后备 / 申万2021一级行业指数（剔除综合） / 中证全指',industryCount=30,
        classification='SW2021',benchmark=dict(code='000985',name='中证全指',unit='点'),points=points,
        method='固定30个申万一级行业；按近5交易日涨跌幅降序排名，与上一交易日排名比较，绝对名次变动加总；并列用平均名次。只有前后两日30行业均完整的观察才计算。页面取每周最后观测，再算4周移动平均。历史从官方实际共同可用日期起，不拼接中信口径。')
    path=ROOT/'akshare-sw-industry-rotation.json'
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        if old.get('asOf','')>target:raise ValueError('Refusing rotation date rollback')
        merged={p['date']:p for p in old.get('points',[])}
        merged.update({p['date']:p for p in points})
        payload['points']=[merged[d] for d in sorted(merged)]
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(path)
    print(json.dumps(dict(asOf=target,first=points[0]['date'],points=len(points),industries=30)))


if __name__=='__main__':main()
