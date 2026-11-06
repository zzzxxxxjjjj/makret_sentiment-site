"""AKShare-only rotation, fixed SW2021 universe of 30 (excluding composite)."""
import json
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
        kwargs['timeout']=25
        return original(self,method,url,**kwargs)
    requests.sessions.Session.request=bounded
    members=json.loads((ROOT/'sw-flow-members.json').read_text(encoding='utf-8'))['members']
    if len(members)!=30 or any(m['name']=='综合' for m in members):raise ValueError('Invalid SW universe')
    now=datetime.now(ZoneInfo('Asia/Shanghai'));limit=now.date() if now.hour>=18 else now.date()-timedelta(days=1)
    calendar=[str(d) for d in ak.tool_trade_date_hist_sina()['trade_date'] if str(d)<=limit.isoformat()]
    target=calendar[-1]
    def one(m):
        last=None
        for _ in range(2):
            try:
                df=ak.index_hist_sw(symbol=m['code'],period='day')
                s=pd.Series(pd.to_numeric(df['收盘'],errors='coerce').to_numpy(),index=pd.to_datetime(df['日期']))
                if s.index.duplicated().any():raise ValueError('Duplicated SW price dates')
                s=s.sort_index().loc[:target]
                if str(s.index[-1])[:10]!=target:raise ValueError('Stale SW close: '+m['name'])
                return m['code'],s
            except Exception as exc:last=exc
        raise RuntimeError('SW price fetch failed: '+m['name']) from last
    with ThreadPoolExecutor(max_workers=2) as pool:prices=pd.DataFrame(dict(pool.map(one,members)))
    start=max(str(prices.index.min().date()),str(limit.replace(year=limit.year-10)))
    raw=ak.stock_zh_index_hist_csindex(symbol='000985',start_date=start.replace('-',''),end_date=target.replace('-',''))
    benchmark=pd.Series(pd.to_numeric(raw['收盘'],errors='coerce').to_numpy(),index=pd.to_datetime(raw['日期'])).sort_index()
    sessions=[d for d in calendar if start<=d<=target]
    points=calculate(prices,benchmark,sessions)
    if points[-1]['date']!=target:raise ValueError('Rotation history does not reach target')
    payload=dict(asOf=target,generatedAt=now.isoformat(),source='AKShare / 申万2021一级行业指数（剔除综合） / 中证全指',industryCount=30,
        classification='SW2021',benchmark=dict(code='000985',name='中证全指',unit='点'),points=points,
        method='固定30个申万一级行业；按近5交易日涨跌幅降序排名，与上一交易日排名比较，绝对名次变动加总；并列用平均名次。只有前后两日30行业均完整的观察才计算。页面取每周最后观测，再算4周移动平均。历史从官方实际共同可用日期起，不拼接中信口径。')
    path=ROOT/'sw-industry-rotation.json';tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(path)
    print(json.dumps(dict(asOf=target,first=points[0]['date'],points=len(points),industries=30)))


if __name__=='__main__':main()
