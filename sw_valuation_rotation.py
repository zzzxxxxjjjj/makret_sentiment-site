"""Recompute SW2021 valuation and rotation; preserve original financial definitions."""
import json
from pathlib import Path
from datetime import datetime
from rqdata_connection import initialize_rqdata
from rqdata_trading_day import completed_trading_date, CHINA_TIME
import rqdata_industry_refresh as valuation
import rotation_history_refresh as rotation

ROOT=Path(__file__).resolve().parent


def save(name,data):
    p=ROOT/name;tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(p)


def main():
    import rqdatac as rq
    initialize_rqdata();target=completed_trading_date(rq)
    members=json.loads((ROOT/'sw-flow-members.json').read_text(encoding='utf-8'))['members']
    if len(members)!=30 or any(m['name']=='综合' for m in members):raise ValueError('Expected 30 SW first-level industries')
    ids,industry=valuation.valuation_universe_and_industry(target,source='sws_2021')
    values,status=valuation.build_pb_roe_percentiles(ids,industry,target,industry_source='sws_2021')
    rows=[]
    for m in members:
        value=values.get(m['code']) or values.get(m['code']+'.SI')
        if not value:
            # RQData sometimes represents industry codes as numeric values.
            value=next((v for k,v in values.items() if str(k).split('.')[0]==m['code']),None)
        if not value:
            value=next((v for v in values.values() if v.get('industryName')==m['name']),None)
        if not value or value['valuationAsOf']!=target.isoformat() or value.get('valuationSamples',0)<12:
            raise ValueError('Missing current SW valuation history: '+m['name'])
        rows.append(dict(code=m['code'],name=m['name'],**value))
    if status.get('roeFactor')!='return_on_equity_ttm':raise ValueError('Ordinary ROE TTM required')
    save('sw-industry-valuation.json',dict(available=True,classification='sws_2021',asOf=target.isoformat(),industries=rows,
        valuationFactorStatus=status,method='月度财务样本沿用原聚合算法；历史申万2021归属按季度取样，不使用当前成分股回填。PB为总市值/总账面净资产，ROE为账面净资产加权普通ROE(TTM)。'))
    print('SW valuation complete: '+str(len(rows)),flush=True)
    instruments=rq.all_instruments(type='INDX')
    mapping={str(r['order_book_id']).split('.')[0]:str(r['order_book_id']) for r in instruments.to_dict('records')}
    rotation.INDUSTRIES={mapping.get(m['code'],m['code']+'.INDX'):m['name'] for m in members}
    for code in rotation.INDUSTRIES:
        if rq.instruments(code) is None:raise ValueError('SW index unavailable: '+code)
    temp=ROOT/'sw-rotation-working.json'
    payload=rotation.refresh(temp,as_of=target,cache_name='sw2021-rotation-prices.pkl.gz')
    if payload['points'][-1]['industries']!=30:raise ValueError('Latest rotation must cover all30 industries')
    payload.update(classification='sws_2021',source='RQData / 申万2021一级行业指数 / 中证全指000985',industryCount=30,
        method='剔除综合，申万2021一级行业指数近5日收益排序；相邻交易日排名变动绝对值之和。并列平均名次；历史至少28个有完整行情行业，当前30个。前端按周末次观察并作MA4。新口径独立重算，不拼接中信历史。')
    save('sw-industry-rotation.json',payload)
    temp.unlink(missing_ok=True)
    print('SW rotation complete '+payload['asOf'],flush=True)


if __name__=='__main__':main()
