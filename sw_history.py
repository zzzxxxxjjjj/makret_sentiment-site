"""20 completed sessions, reconstructed using current SW membership, never intraday."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def collect(shard):
    import akshare as ak
    import requests
    original = requests.sessions.Session.request
    def bounded(self, method, url, **kwargs):
        kwargs['timeout'] = 12
        return original(self, method, url, **kwargs)
    requests.sessions.Session.request = bounded
    meta = json.loads((ROOT/'sw-flow-members.json').read_text(encoding='utf-8'))
    members = sorted(meta['members'], key=lambda m:m['code'])
    if len(members) != 30: raise ValueError('Expected 30 SW industries')
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    limit = now.date() if now.hour >= 18 else now.date()-timedelta(days=1)
    calendar = sorted(str(d) for d in ak.tool_trade_date_hist_sina()['trade_date'])
    dates = [d for d in calendar if d <= limit.isoformat()][-20:]
    if len(dates) != 20: raise ValueError('Incomplete calendar')
    group = members[shard::6]
    codes = sorted({c for m in group for c in m['stocks']})
    def one(code):
        market = 'sh' if code.startswith('6') else 'bj' if code.startswith(('4','8','9')) else 'sz'
        for attempt in range(2):
            try:
                df = ak.stock_individual_fund_flow(stock=code, market=market)
                values = {}
                for row in df.to_dict('records'):
                    day = str(row['日期'])[:10]
                    v = float(row['主力净流入-净额'])
                    if day in dates and math.isfinite(v): values[day] = v
                return code, values
            except Exception: pass
        return code, {}
    histories = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one,c) for c in codes]
        for i, future in enumerate(as_completed(futures),1):
            c, values = future.result(); histories[c] = values
            if i % 100 == 0: print(f'Shard {shard}: {i}/{len(codes)}', flush=True)
    output = []
    for day in dates:
        rows = []
        for m in group:
            values = [histories[c][day] for c in m['stocks'] if day in histories[c]]
            covered, total = len(values), len(m['stocks'])
            rows.append(dict(code=m['code'], name=m['name'], covered=covered, total=total,
                             value=sum(values)/1e8 if covered/total >= .90 else None))
        output.append(dict(date=day, rows=rows))
    signature = hashlib.sha256(json.dumps(members,sort_keys=True).encode()).hexdigest()
    write(ROOT/'sw-history-parts'/f'part-{shard}.json',dict(dates=dates,membershipDate=meta['date'],signature=signature,days=output))
    print(f'History shard {shard} complete; stocks={len(codes)}',flush=True)


def merge():
    parts = [json.loads((ROOT/'sw-history-parts'/f'part-{i}.json').read_text(encoding='utf-8')) for i in range(6)]
    if len({p['signature'] for p in parts}) != 1 or any(p['dates'] != parts[0]['dates'] for p in parts):
        raise ValueError('Different history calendars or membership versions')
    days = []
    for i, day in enumerate(parts[0]['dates']):
        rows = [r for p in parts for r in p['days'][i]['rows']]
        if len(rows) != 30 or len({r['code'] for r in rows}) != 30: raise ValueError('Incomplete industries')
        days.append(dict(date=day, rows=rows))
    usable = sum(r['value'] is not None for d in days for r in d['rows'])
    if usable < 540: raise ValueError('Less than 90 percent of industry-days meet coverage; previous history retained')
    write(ROOT/'sw-industry-history.json',dict(available=True,asOf=days[-1]['date'],days=days,
        membershipDate=parts[0]['membershipDate'],collectedAt=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        method='按当前申万2021成分股重构，非历史时点成分；日频主力净流入，非盘中采样。低于90%成分股覆盖的行业日留空，累计曲线遇缺失后不继续累计。',
        coverage=dict(validIndustryDays=usable,totalIndustryDays=600)))
    print(f'20-session SW history: {days[0]["date"]} to {days[-1]["date"]}; usable={usable}/600')


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--shard',type=int,choices=range(6));parser.add_argument('--merge',action='store_true');a=parser.parse_args()
    if a.merge: merge()
    elif a.shard is not None: collect(a.shard)
    else: parser.error('Select --shard or --merge')
