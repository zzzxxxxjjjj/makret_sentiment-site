"""Free Eastmoney ETF turnover + shares snapshot; no invented fund-flow values."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "etf-shares-history.json"
HISTORY_KEEP = 400  # ~1.5y of trading days


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
        shares = number(r.get('最新份额'))
        close = number(r.get('最新价'))
        rows.append(dict(code=code, name=str(r['名称']), amount=amount / 1e8,
                         change=number(r.get('涨跌幅')), asOf=day,
                         shares=shares, close=close))
    if len(rows) < 100 or len({r['code'] for r in rows}) != len(rows):
        raise ValueError('ETF coverage incomplete or duplicated')
    return dict(available=True, generatedAt=datetime.now(timezone.utc).isoformat(),
                asOf=max(r['asOf'] for r in rows), source='东方财富 / AKShare fund_etf_spot_em', rows=rows)


def update_history(value):
    """Append today's share snapshot so net subscription can be derived over time."""
    as_of = value['asOf']
    entry = {
        'date': as_of,
        'shares': {r['code']: r.get('shares') for r in value['rows']},
        'close': {r['code']: r.get('close') for r in value['rows']},
    }
    history = {'entries': []}
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            history = {'entries': []}
    history.setdefault('entries', [])
    history['entries'] = [e for e in history['entries'] if e.get('date') != as_of]
    history['entries'].append(entry)
    history['entries'] = history['entries'][-HISTORY_KEEP:]
    tmp = HISTORY_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(history, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(HISTORY_FILE)


if __name__ == '__main__':
    import akshare as ak
    import requests
    original = requests.sessions.Session.request
    def bounded(self, method, url, **kwargs):
        kwargs.setdefault('timeout', 30)
        return original(self, method, url, **kwargs)
    requests.sessions.Session.request = bounded
    value = build(ak.fund_etf_spot_em())
    path = ROOT / 'etf-market.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('asOf', '') > value['asOf']:
        raise ValueError('Refusing date rollback')
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(path)
    update_history(value)
    print('Eastmoney ETF snapshot: ' + value['asOf'] + ' rows=' + str(len(value['rows'])))
