"""AKShare SW2021 first-level constituents, aggregated Eastmoney main-money flow.

Snapshots are actual collection times, not fabricated minute history.
"""
import json
import os
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
        if len(valid)/len(codes) < .90: raise ValueError('Insufficient stock coverage: '+m['name']+' '+str(len(valid))+'/'+str(len(codes))+' missing='+','.join(sorted(codes-values.keys())))
        output.append(dict(code=m['code'], name=m['name'], value=sum(valid)/1e8,
                           covered=len(valid), total=len(codes)))
    return output


def main():
    import akshare as ak
    import requests
    original = requests.sessions.Session.request
    def bounded(self, method, url, **kwargs):
        kwargs['timeout'] = 25
        return original(self, method, url, **kwargs)
    requests.sessions.Session.request = bounded
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    calendar = (getattr(ak,'calendar_trade_date_hist_sina',None) or ak.tool_trade_date_hist_sina)()['trade_date'].astype(str).tolist()
    from completed_session import completed_target
    day = os.environ.get('DAILY_TARGET_DATE') or completed_target(now,calendar)
    # The bulk main-money service is a current-session feed, not a historical selector.
    # Never label current intraday flows as a previous completed session.
    if day != now.date().isoformat() or now.hour < 18:
        raise ValueError("AkShare批量主力资金仅可核验当日收盘；目标日历史个股资金尚未齐，保留原行业日期")
    path = ROOT/'sw-industry-flow.json'
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    membership_path = ROOT/'sw-flow-members.json'
    cached = json.loads(membership_path.read_text(encoding='utf-8')) if membership_path.exists() else {}
    if cached.get('date') == day:
        members = cached['members']
    else:
        listing = (getattr(ak,'index_first_info_sw',None) or ak.sw_index_first_info)()
        listing = listing[listing['行业名称'] != '综合']
        if len(listing) != 30: raise ValueError('Incomplete SW industry classification')
        def one(r):
            code = str(r['行业代码']).split('.')[0]
            last = None
            for attempt in range(2):
                try:
                    frame = ak.index_component_sw(symbol=code)
                    if frame.empty: raise ValueError('Empty SW constituent response')
                    return dict(code=code, name=str(r['行业名称']), stocks=[str(c).split('.')[0].zfill(6) for c in frame['证券代码']])
                except Exception as exc: last = exc
            # AKShare's Legulegu composition endpoint also accepts first-level
            # .SI index codes; same SW code, never an Eastmoney sector mapping.
            frame = (getattr(ak,'index_third_cons_sw',None) or ak.sw_index_third_cons)(symbol=code+'.SI')
            column = next((c for c in frame if '代码' in str(c)), None)
            if frame.empty or column is None: raise ValueError('Missing SW constituents: '+code) from last
            return dict(code=code, name=str(r['行业名称']), stocks=[str(c).split('.')[0].zfill(6) for c in frame[column]])
        with ThreadPoolExecutor(max_workers=1) as pool:
            members = list(pool.map(one, listing.to_dict('records')))
        # Retain validated public classification for future retries even if the
        # separate stock-flow service is unavailable during this run.
        if len(members) != 30 or any(not m['stocks'] for m in members):
            raise ValueError('Incomplete SW membership cache')
        temporary = membership_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(date=day, members=members), ensure_ascii=False), encoding='utf-8')
        temporary.replace(membership_path)
    stocks = (getattr(ak,'stock_fund_flow_individual_rank_em',None) or ak.stock_individual_fund_flow_rank)(indicator='今日')
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
            history = (getattr(ak,'stock_fund_flow_individual_hist_em',None) or ak.stock_individual_fund_flow)(stock=code, market=market)
            current = history[history['日期'].astype(str).str[:10] == day]
            value = float(current.iloc[-1]['主力净流入-净额']) if len(current) else float('nan')
            if math.isfinite(value): return {'代码': code, '今日主力净流入-净额': value}
        except Exception: pass
        return None
    with ThreadPoolExecutor(max_workers=1) as pool:
        extra = [r for r in pool.map(supplement, sorted(missing)) if r is not None]
    if extra: stocks = pd.concat([stocks, pd.DataFrame(extra)], ignore_index=True)
    rows = aggregate(members, stocks)
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    stamp = now.strftime('%H:%M') if now.date().isoformat() == day else '收盘快照'
    points = old.get('snapshots', [])
    points = [p for p in points if not (p['date'] == day and p['time'] == stamp)]
    points.append(dict(date=day, time=stamp, rows=rows))
    days = sorted({p['date'] for p in points})[-20:]
    points = [p for p in points if p['date'] in days]
    value = dict(available=True, asOf=day, collectedAt=now.isoformat(), classification='申万2021一级行业（剔除综合）',
        source='AKShare申万成分股＋东方财富个股主力净流入汇总', snapshots=points,
        note='按采集当日申万成分股等金额求和，不使用指数权重。覆盖率至少90%；未返回数值的股票不计入，非全覆盖时为已覆盖股票小计，图中以*标记。仅保留真实采样时点，非连续分钟数据；多日累计使用各交易日最后一次采样值，不承诺为收盘终值。')
    for p, obj in [(membership_path, dict(date=day, members=members)), (path,value)]:
        tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(p)
    print('SW industry snapshot '+day+' industries='+str(len(rows)))


if __name__ == '__main__':
    from akshare_request_policy import install
    install()
    main()
