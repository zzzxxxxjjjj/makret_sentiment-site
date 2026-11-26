"""Free Eastmoney ETF turnover + shares snapshot; no invented fund-flow values."""
import json
import math
import os
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
        history = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
    history.setdefault('entries', [])
    # A realtime snapshot must not discard verified exchange units or their provenance.
    saved = next((e for e in history['entries'] if e.get('date') == as_of), {})
    verified = saved.get('verifiedUnits', {})
    for code in verified:
        entry['shares'][code] = saved['shares'][code]
    entry['verifiedUnits'] = verified
    entry['close'] = {**saved.get('close', {}), **{k:v for k,v in entry['close'].items() if v is not None}}
    history['entries'] = [e for e in history['entries'] if e.get('date') != as_of]
    history['entries'].append(entry)
    history['entries'].sort(key=lambda entry: entry['date'])
    tmp = HISTORY_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(history, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(HISTORY_FILE)


if __name__ == '__main__':
    from akshare_request_policy import install
    install()
    import akshare as ak
    import requests
    original = requests.sessions.Session.request
    def bounded(self, method, url, **kwargs):
        kwargs.setdefault('timeout', 30)
        return original(self, method, url, **kwargs)
    requests.sessions.Session.request = bounded
    path = ROOT / 'etf-market.json'
    target=os.environ.get('DAILY_TARGET_DATE')
    if not target:
        from completed_session import completed_target
        from zoneinfo import ZoneInfo
        calendar=json.loads((ROOT/"data-freshness.json").read_text(encoding="utf-8"))["tradingCalendar"]
        target=completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),calendar)
    try:
        value = build(ak.fund_etf_spot_em())
        if target and value['asOf']!=target:raise ValueError('AKShare ETF target date mismatch')
    except Exception as exc:
        print('AKShare ETF failed: '+type(exc).__name__+'; switching to Baostock',flush=True)
        if not target:raise ValueError('Verified DAILY_TARGET_DATE required for fallback') from exc
        previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        try:
            from baostock_etf_fallback import collect
            value=collect(previous,target)
        except Exception as bao_error:
            print("Baostock ETF failed: "+type(bao_error).__name__+"; switching to iFind",flush=True)
            from ifind_etf_fallback import collect
            value=collect(previous,target)
        value['fallbackReason']=type(exc).__name__
    if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('asOf', '') > value['asOf']:
        raise ValueError('Refusing date rollback')
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(path)
    if value.get('sharesAvailable',True):update_history(value)
    print('ETF snapshot: ' + value['asOf'] + ' rows=' + str(len(value['rows'])))
