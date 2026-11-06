"""AKShare SW2021 first-level constituents, aggregated Eastmoney main-money flow.

Snapshots are actual collection times, not fabricated minute history.
"""
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
import math

ROOT = Path(__file__).resolve().parent


def aggregate(members, stocks):
    if len(members) != 30 or any(m['name'] == '综合' for m in members):
        raise ValueError('Expected 30 SW first-level industries excluding composite')
    values = {}
    for r in stocks.to_dict('records'):
        try:
            v = float(r['今日主力净流入-净额'])
            if math.isfinite(v): values[str(r['代码']).zfill(6)] = v
        except (ValueError, TypeError): pass
    output = []
    seen = set()
    for m in members:
        codes = set(m['stocks'])
        if not codes or seen & codes: raise ValueError('Empty or overlapping SW membership')
        seen |= codes
        valid = [values[c] for c in codes if c in values]
        if len(valid)/len(codes) < .95: raise ValueError('Insufficient stock coverage: '+m['name']+' '+str(len(valid))+'/'+str(len(codes))+' missing='+','.join(sorted(codes-values.keys())))
        output.append(dict(code=m['code'], name=m['name'], value=sum(valid)/1e8,
                           covered=len(valid), total=len(codes)))
    return output


def main():
    import akshare as ak
    import requests
    original = requests.sessions.Session.request
    def bounded(self, method, url, **kwargs):
        kwargs.setdefault('timeout', 25)
        return original(self, method, url, **kwargs)
    requests.sessions.Session.request = bounded
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    calendar = ak.tool_trade_date_hist_sina()['trade_date'].astype(str).tolist()
    day = max(d for d in calendar if d <= now.date().isoformat())
    path = ROOT/'sw-industry-flow.json'
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    membership_path = ROOT/'sw-flow-members.json'
    cached = json.loads(membership_path.read_text(encoding='utf-8')) if membership_path.exists() else {}
    if cached.get('date') == day:
        members = cached['members']
    else:
        listing = ak.sw_index_first_info()
        listing = listing[listing['行业名称'] != '综合']
        if len(listing) != 30: raise ValueError('Incomplete SW industry classification')
        def one(r):
            code = str(r['行业代码']).split('.')[0]
            frame = ak.index_component_sw(symbol=code)
            return dict(code=code, name=str(r['行业名称']), stocks=[str(c).split('.')[0].zfill(6) for c in frame['证券代码']])
        with ThreadPoolExecutor(max_workers=4) as pool:
            members = list(pool.map(one, listing.to_dict('records')))
    # ETF spot provides a provider-stamped trading date; do not date old flow as today.
    quote = ak.fund_etf_spot_em()
    provider_day = max(str(d)[:10] for d in quote['数据日期'])
    if provider_day != day: raise ValueError('Provider trading date not current')
    if now.date().isoformat() == day and now.hour < 9: raise ValueError('Before current trading session')
    stocks = ak.stock_individual_fund_flow_rank(indicator='今日')
    import pandas as pd
    numeric = pd.to_numeric(stocks['今日主力净流入-净额'], errors='coerce')
    available = set(stocks.loc[numeric.notna(), '代码'].astype(str).str.zfill(6))
    missing = set()
    for m in members:
        codes = set(m['stocks'])
        if len(codes & available)/len(codes) < .95:
            missing |= codes-available
    if len(missing) > 100: raise ValueError('Bulk stock source incomplete; retry later')
    def supplement(code):
        market = 'sh' if code.startswith('6') else 'bj' if code.startswith(('4','8','9')) else 'sz'
        try:
            history = ak.stock_individual_fund_flow(stock=code, market=market)
            current = history[history['日期'].astype(str).str[:10] == day]
            value = float(current.iloc[-1]['主力净流入-净额']) if len(current) else float('nan')
            if math.isfinite(value): return {'代码': code, '今日主力净流入-净额': value}
        except Exception: pass
        return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        extra = [r for r in pool.map(supplement, sorted(missing)) if r is not None]
    if extra: stocks = pd.concat([stocks, pd.DataFrame(extra)], ignore_index=True)
    rows = aggregate(members, stocks)
    stamp = now.strftime('%H:%M') if now.date().isoformat() == day else '收盘快照'
    points = old.get('snapshots', [])
    points = [p for p in points if not (p['date'] == day and p['time'] == stamp)]
    points.append(dict(date=day, time=stamp, rows=rows))
    days = sorted({p['date'] for p in points})[-20:]
    points = [p for p in points if p['date'] in days]
    value = dict(available=True, asOf=day, collectedAt=now.isoformat(), classification='申万2021一级行业（剔除综合）',
        source='AKShare申万成分股＋东方财富个股主力净流入汇总', snapshots=points,
        note='按采集当日申万成分股等金额求和，不使用指数权重。覆盖率至少95%；未返回数值的股票不计入，非全覆盖时为已覆盖股票小计。仅保留真实采样时点，非连续分钟数据；多日累计使用各交易日最后一次采样值，不承诺为收盘终值。')
    for p, obj in [(membership_path, dict(date=day, members=members)), (path,value)]:
        tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(p)
    print('SW industry snapshot '+day+' industries='+str(len(rows)))


if __name__ == '__main__': main()
