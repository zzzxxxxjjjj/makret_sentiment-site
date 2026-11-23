"""Validated v2 implicit factor-return snapshot; no changes to timing scores."""
import json
import math
from datetime import timedelta
from pathlib import Path

FACTORS = ['book_to_price','growth','profitability','liquidity','dividend_yield','size','mid_cap',
           'leverage','momentum','beta','residual_volatility','earnings_quality','earnings_variability',
           'investment_quality','longterm_reversal','earnings_yield']


def build_snapshot(frame, sessions):
    dates=[str(d)[:10] for d in sessions][-20:]
    if len(dates)!=20 or dates!=sorted(set(dates)):
        raise ValueError('Expected 20 completed trading sessions')
    observations={str(day)[:10]:row for day,row in frame.iterrows()}
    if len(observations)!=len(frame) or any(d not in observations for d in dates):
        raise ValueError('Factor return dates incomplete or duplicated')
    for day in dates:
        for code in FACTORS:
            value=observations[day].get(code)
            if isinstance(value,bool) or value is None or not math.isfinite(float(value)):
                raise ValueError('Factor return missing or nonfinite')
    periods=[]
    for key,label,ds in [('week','近一周',dates[-5:]),('previousWeek','上一周',dates[-10:-5]),('month','近一月',dates)]:
        periods.append({'id':key,'label':label,'start':ds[0],'end':ds[-1],'count':len(ds),
                        'values':{code:round(sum(float(observations[d][code]) for d in ds)*100,6) for code in FACTORS}})
    return {'available':True,'asOf':dates[-1],'source':'RQData · v2风险模型 · 全市场 · 隐式因子收益',
            'model':'v2','method':'implicit','universe':'whole_market',
            'chart':{'method':'factor-return-sum','unit':'%','periods':periods}}


def main():
    import warnings
    warnings.filterwarnings('ignore',message='Your account will be expired')
    from retired_provider import client as rq
    from rqdata_connection import initialize_rqdata
    from rqdata_trading_day import completed_trading_date
    initialize_rqdata()
    target=completed_trading_date(rq)
    sessions=rq.get_trading_dates(target-timedelta(days=90),target)[-20:]
    if len(sessions)!=20:raise ValueError('Insufficient trading calendar')
    frame=rq.get_factor_return(sessions[0],target,factors=FACTORS,model='v2',method='implicit',universe='whole_market')
    snapshot=build_snapshot(frame,sessions)
    path=Path(__file__).with_name('style-factor-returns.json')
    if path.exists():
        previous=json.loads(path.read_text(encoding='utf-8'))
        if previous.get('asOf','')>snapshot['asOf']:raise ValueError('Refusing factor return rollback')
        if previous==snapshot:
            print('Factor returns unchanged: '+snapshot['asOf']);return
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(snapshot,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf-8')
    temporary.replace(path)
    print(json.dumps({'asOf':snapshot['asOf'],'factors':len(FACTORS),'periods':3},ensure_ascii=True))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        from rqdata_connection import safe_error
        raise SystemExit('Factor returns refresh failed: '+safe_error(exc))
