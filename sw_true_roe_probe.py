"""Retry AKShare real statement-based ordinary ROE, not PB/PE."""
import json
import math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import akshare as ak
import requests

original=requests.sessions.Session.request
def bounded(self,method,url,**kwargs):
    kwargs['timeout']=20
    return original(self,method,url,**kwargs)
requests.sessions.Session.request=bounded


def column(frame,names):
    for name in names:
        if name in frame:return name
    raise ValueError('Required parent-company field missing; candidates='+str([str(c) for c in frame if '母公司' in str(c)]))


def fetch_report(code,symbol):
    for attempt in range(3):
        try:return ak.stock_financial_report_sina(stock=code,symbol=symbol)
        except requests.exceptions.RequestException:
            if attempt==2:raise


def probe(code):
    try:
        profit=fetch_report(code,'利润表')
        balance=fetch_report(code,'资产负债表')
        pc=column(profit,['归属于母公司所有者的净利润','归属于母公司股东的净利润','归属于母公司的净利润'])
        ec=column(balance,['归属于母公司所有者权益合计','归属于母公司股东权益合计','归属于母公司所有者权益','归属于母公司股东权益','归属于母公司股东的权益'])
        for frame in [profit,balance]:
            frame['_date']=pd.to_datetime(frame['报告日'].astype(str),errors='coerce')
            frame.set_index('_date',inplace=True)
        current=max(set(profit.index)&set(balance.index))
        previous=current-pd.offsets.QuarterEnd(1)
        prior=current.replace(year=current.year-1)
        annual=pd.Timestamp(current.year-1,12,31)
        p=float(profit.loc[current,pc])
        ttm=p if current.month==12 else p+float(profit.loc[annual,pc])-float(profit.loc[prior,pc])
        e0,e1=float(balance.loc[current,ec]),float(balance.loc[previous,ec])
        if not all(math.isfinite(v) for v in [ttm,e0,e1]) or e0+e1<=0:raise ValueError('Invalid ordinary ROE inputs')
        print(json.dumps(dict(code=code,status='numeric_inputs_available',report=str(current.date()),profitField=pc,equityField=ec,
            ordinaryRoeTtmPercent=ttm*2/(e0+e1)*100,profitRows=len(profit),balanceRows=len(balance),
            disclosureDates=('公告日期' in profit and '公告日期' in balance)),ensure_ascii=True),flush=True)
        return True
    except Exception as exc:
        print(json.dumps(dict(code=code,status='failed',errorType=type(exc).__name__,message=str(exc)[:500]),ensure_ascii=True),flush=True)
        return False


if __name__=='__main__':
    members=json.loads(Path('sw-flow-members.json').read_text(encoding='utf-8'))['members']
    codes=['sh600519','sh600036','sz300750']
    for industry in members:
        code=industry['stocks'][0]
        codes.append(('sh' if code.startswith('6') else 'sz')+code)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(probe,dict.fromkeys(codes)))
    print(json.dumps(dict(sampled=len(results),passed=sum(results),productionApproved=False)),flush=True)
    if not all(results):raise SystemExit('Financial input sample verification incomplete')

    try:
        dates=ak.index_analysis_week_month_sw(symbol='month')['date'].tolist()
        selected=dates[-1]
        pb=ak.index_analysis_monthly_sw(symbol='一级行业',date=selected.strftime('%Y%m%d'))
        expected={m['code'] for m in members}
        pb['code']=pb['指数代码'].astype(str).str.replace(r'\\.0$','',regex=True).str.zfill(6)
        valid=pb[pb['code'].isin(expected)&(pd.to_numeric(pb['市净率'],errors='coerce')>0)]
        print(json.dumps(dict(pbMonthlyDate=str(selected),pbIndustries=valid['code'].nunique(),monthlyDates=len(dates),productionApproved=False)),flush=True)
        if valid['code'].nunique()!=30:raise ValueError('Incomplete SW PB universe')
    except Exception as exc:
        print(json.dumps(dict(pbProbe='failed',errorType=type(exc).__name__,message=str(exc)[:300])),flush=True)
        raise
