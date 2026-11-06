"""Free Eastmoney ETF turnover snapshot; no invented fund-flow values."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build(frame):
    rows = []
    def number(v):
        try:
            x = float(v)
            return x if math.isfinite(x) else None
        except (ValueError, TypeError):
            return None
    for r in frame.to_dict('records'):
        code = str(r.get('代码', '')).zfill(6)
        amount = number(r.get('成交额'))
        day = str(r.get('数据日期', ''))[:10]
        if len(code) != 6 or not code.isdigit() or amount is None or amount < 0 or len(day) != 10:
            continue
        rows.append(dict(code=code, name=str(r['名称']), amount=amount/1e8,
                         change=number(r.get('涨跌幅')), asOf=day))
    if len(rows) < 100 or len({r['code'] for r in rows}) != len(rows):
        raise ValueError('ETF coverage incomplete or duplicated')
    return dict(available=True, generatedAt=datetime.now(timezone.utc).isoformat(),
                asOf=max(r['asOf'] for r in rows), source='东方财富 / AKShare fund_etf_spot_em', rows=rows)


if __name__ == '__main__':
    import akshare as ak
    import requests
    original = requests.sessions.Session.request
    def bounded(self, method, url, **kwargs):
        kwargs.setdefault('timeout', 30)
        return original(self, method, url, **kwargs)
    requests.sessions.Session.request = bounded
    value = build(ak.fund_etf_spot_em())
    path = ROOT/'etf-market.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('asOf','') > value['asOf']:
        raise ValueError('Refusing date rollback')
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(path)
    print('Eastmoney ETF snapshot: '+value['asOf']+' rows='+str(len(value['rows'])))
