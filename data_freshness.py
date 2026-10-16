"""Publish per-metric actual dates and verify the next-session 09:30 target."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from rqdata_trading_day import CHINA_TIME
BASE_DIR=Path(__file__).resolve().parent
NON_DAILY={'stock-fund-position':'quarterly','a-share-new-accounts':'monthly'}

def read(directory,name):
    try:
        return json.loads((Path(directory)/name).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):
        return {}

def last_date(points,field='value'):
    return max((p.get('date','') for p in points if isinstance(p,dict) and p.get(field) is not None),default=None)

def build_report(target, directory=BASE_DIR, errors=None, calendar=None):
    page=read(directory,'broad-sentiment-page-cache.json').get('payload',{})
    entries=[]
    def add(key,label,as_of,frequency='daily',source=''):
        entries.append({'id':key,'label':label,'asOf':as_of,'frequency':frequency,
                        'current':bool(as_of and as_of>=target) if frequency=='daily' else None,'source':source})
    # Audit displayed daily series, excluding superseded Excel aliases.
    obsolete={'breadth-sentiment','sentiment-cycle','institutional-net-buy','sh-composite-close-excel','windall-close-excel'}
    for series in page.get('series',[]):
        if not isinstance(series,dict) or series.get('id') in obsolete:
            continue
        sid=series.get('id','')
        add(sid,series.get('name',sid),last_date(series.get('points',[])),NON_DAILY.get(sid,'daily'),series.get('source',''))
    for card in page.get('cards',[]):
        if not isinstance(card,dict) or card.get('id') in {'breadth-sentiment','sentiment-cycle'}:continue
        sid=card.get('id','')
        add('card-'+sid,card.get('title',sid)+'（概览）',card.get('asOf'),NON_DAILY.get(sid,'daily'),card.get('source',''))
    cycle=page.get('cycleComparison',{})
    add('cycle-composite','短期情绪合成',last_date(cycle.get('points',[]),'sentiment'))
    industry=read(directory,'rqdata-industry-sentiment.json')
    rows=industry.get('industries',[])
    for metric,label in [('netFlow','一级行业主力资金'),('marginActivity','一级行业杠杆资金'),('amountShare','一级行业成交额占比')]:
        dates=[last_date(row.get('series',[]),metric) for row in rows if row.get('name')!='综合']
        # Slowest industry determines whether the entire module is ready.
        as_of=min(dates) if dates and all(dates) else None
        add(metric,label,as_of,source='RQData')
    valuation_dates=[row.get('valuationAsOf') for row in rows if row.get('name')!='综合']
    add('industry-pb-roe','行业PB-ROE分位',min(valuation_dates) if valuation_dates and all(valuation_dates) else None,source='RQData')
    children=[child for row in rows for child in row.get('children',[])]
    child_dates=[child.get('asOf') for child in children]
    add('second-industry-flow','二级行业资金流向',min(child_dates) if child_dates and all(child_dates) else None,source='RQData')
    rotation=read(directory,'rqdata-industry-rotation.json')
    add('industry-rotation','行业轮动强度与中证全指',rotation.get('asOf'),source='RQData')
    for filename,label,freq in [('rqdata-fund-exposure.json','公募行业超配','weekly'),('macro-tracking.json','宏观月度指标','monthly')]:
        payload=read(directory,filename);add(filename,label,payload.get('asOf'),freq,payload.get('source',''))
    daily=[e for e in entries if e['frequency']=='daily']
    lagging=[e for e in daily if not e['current']]
    return {'targetDate':target,'checkedAt':datetime.now(CHINA_TIME).isoformat(timespec='seconds'),
            'deadlineTime':'09:30','timezone':'Asia/Shanghai','allDailyCurrent':bool(daily) and not lagging,
            'dailyCount':len(daily),'currentDailyCount':len(daily)-len(lagging),'laggingDaily':lagging,
            'entries':entries,'errors':errors or [],'tradingCalendar':calendar or [],
            'methodologyChanges':page.get('methodologyChanges',[]),
            'note':'日频指标以前一交易日为更新目标；周频、月频、季频按各自披露周期保留实际日期。未到齐的数据不会标为已全部更新。'}

def write_report(target, directory=BASE_DIR, errors=None, calendar=None):
    report=build_report(target,directory,errors,calendar)
    (Path(directory)/'data-freshness.json').write_text(json.dumps(report,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--target')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    report=read(BASE_DIR,'data-freshness.json') if args.check else write_report(args.target)
    print(json.dumps({key:report.get(key) for key in ['targetDate','allDailyCurrent','dailyCount','currentDailyCount','laggingDaily']},ensure_ascii=True))
    if args.check and not report.get('allDailyCurrent'):
        raise SystemExit(1)
