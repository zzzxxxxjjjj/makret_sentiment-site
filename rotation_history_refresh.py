"""Ten-year CITICS level-1 rotation strength and CSI All Share comparison."""
from __future__ import annotations
import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
import pandas as pd
from rqdata_connection import initialize_rqdata
from rqdata_trading_day import completed_trading_date, CHINA_TIME

BASE_DIR = Path(__file__).resolve().parent
INDUSTRIES = {
    f'CI005{i:03d}.INDX': name for i, name in enumerate([
        '石油石化','煤炭','有色金属','电力及公用事业','钢铁','基础化工','建筑','建材','轻工制造','机械',
        '电力设备及新能源','国防军工','汽车','商贸零售','消费者服务','家电','纺织服装','医药','食品饮料',
        '农林牧渔','银行','非银行金融','房地产','交通运输','电子','通信','计算机','传媒','综合','综合金融'], 1)
    if name != '综合'
}
BENCHMARK = '000985.XSHG'

def ten_year_start(as_of):
    return as_of.replace(year=as_of.year-10, day=min(as_of.day, 28)) if as_of.month == 2 else as_of.replace(year=as_of.year-10)

def calculate(prices, calendar, as_of):
    """Use all 29 industries on both adjacent market sessions; ties share rank."""
    wide = prices.pivot_table(index='date', columns='order_book_id', values='close', aggfunc='last').sort_index()
    sessions = pd.DatetimeIndex(pd.to_datetime(calendar))
    wide = wide.reindex(sessions)
    returns = wide.reindex(columns=list(INDUSTRIES)).pct_change(5, fill_method=None) * 100
    benchmark = wide[BENCHMARK]
    points = []
    first_available = {code:wide[code].first_valid_index() for code in INDUSTRIES}
    for i in range(1,len(sessions)):
        stamp=sessions[i]
        if stamp.date() < ten_year_start(as_of) or stamp.date() > as_of or pd.isna(benchmark.loc[stamp]):
            continue
        previous, current = returns.iloc[i-1], returns.iloc[i]
        # Only compare the same historical industry universe on both days.
        expected = [code for code in INDUSTRIES if first_available[code] is not None and first_available[code] <= sessions[max(0,i-6)]]
        if len(expected)<28 or previous[expected].isna().any() or current[expected].isna().any():
            continue
        changes = current[expected].rank(ascending=False,method='average')-previous[expected].rank(ascending=False,method='average')
        value=changes.abs().sum()
        points.append({'date':stamp.date().isoformat(),'value':round(float(value),2),'indexClose':round(float(benchmark.loc[stamp]),4),'industries':len(expected)})
    if not points or points[-1]['date'] != as_of.isoformat():
        raise ValueError('Rotation or CSI All Share did not reach target trading date')
    return points

def refresh(output, as_of=None):
    import rqdatac as rq
    initialize_rqdata()
    as_of = as_of or completed_trading_date(rq)
    cache = BASE_DIR/'.rqdata-cache/rotation-prices.pkl.gz'
    cache.parent.mkdir(exist_ok=True)
    first = ten_year_start(as_of) - timedelta(days=30)
    prior = pd.DataFrame()
    if cache.exists():
        prior = pd.read_pickle(cache, compression='gzip')
        if not prior.empty:
            first = max(first, pd.to_datetime(prior['date']).max().date()-timedelta(days=18))
    raw = rq.get_price([*INDUSTRIES,BENCHMARK],start_date=first,end_date=as_of,fields=['close'],frequency='1d',expect_df=True)
    incoming = raw.reset_index().rename(columns={'datetime':'date','order_book_ids':'order_book_id'})
    incoming['date'] = pd.to_datetime(incoming['date']).dt.normalize()
    combined = pd.concat([prior,incoming],ignore_index=True).drop_duplicates(['date','order_book_id'],keep='last')
    combined = combined.sort_values(['date','order_book_id'])
    calendar = rq.get_trading_dates(ten_year_start(as_of)-timedelta(days=30),as_of)
    points = calculate(combined,calendar,as_of)
    combined.to_pickle(cache, compression='gzip')
    values = [p['value'] for p in points[-250:]]
    latest = values[-1]
    payload = {'asOf':points[-1]['date'],'generatedAt':datetime.now(CHINA_TIME).isoformat(timespec='seconds'),
        'source':'RQData / 中信一级行业指数 / 中证全指 000985.XSHG','industryCount':len(INDUSTRIES),
        'method':'每个交易日按中信29个一级行业指数近5个交易日涨跌幅降序排名，比较上一交易日排名，排名变动绝对值加总；并列涨跌幅使用平均名次。剔除综合；历史按当时有完整行情的行业，连续两日使用同一行业集合重排，当前29个行业。',
        'benchmark':{'code':BENCHMARK,'name':'中证全指','unit':'点'},'value':latest,
        'percentile250D':round((sum(v<latest for v in values)+.5*sum(v==latest for v in values))/len(values)*100,1),
        'points':points}
    output.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'asOf':payload['asOf'],'start':points[0]['date'],'points':len(points),'industries':len(INDUSTRIES)},ensure_ascii=False))
    return payload

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=BASE_DIR/'rqdata-industry-rotation.json')
    parser.add_argument('--as-of',type=date.fromisoformat)
    args=parser.parse_args()
    refresh(args.output,args.as_of)
