"""Derive daily net subscription (净申赎) for Huijin key ETFs from Eastmoney share history.

RQData only covers the primary share classes; many Huijin ETFs lack units history there.
Eastmoney publishes a '最新份额' (latest shares) column for every ETF, so we track it daily
(etf_market_refresh.py -> etf-shares-history.json) and compute net subscription = share_change * close.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "etf-shares-history.json"

# 汇金重点ETF（与用户提供的 Excel 品种一致）
TARGET = [
    '510300', '510310', '510330', '159919', '510050', '510100', '510180', '510230',
    '515800', '159901', '159915', '159952', '159977', '588000', '588080', '588050',
    '510500', '512500', '159922', '512100', '159845', '560010', '159629',
]


def number(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def compute():
    if not HISTORY_FILE.exists():
        return dict(available=False, asOf=None,
                    generatedAt=datetime.now(timezone.utc).isoformat(),
                    source='东方财富 最新份额 推算', rows=[])
    history = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
    entries = sorted(history.get('entries', []), key=lambda e: e['date'])
    if len(entries) < 2:
        as_of = entries[-1]['date'] if entries else None
        return dict(available=True, asOf=as_of,
                    generatedAt=datetime.now(timezone.utc).isoformat(),
                    source='东方财富 最新份额 推算',
                    note='历史份额积累中，暂无法计算净申赎', rows=[])
    today = entries[-1]
    prev1 = entries[-2]
    prev5 = entries[-6] if len(entries) >= 6 else None
    rows = []
    for code in TARGET:
        s_t = number(today['shares'].get(code))
        c_t = number(today['close'].get(code))
        if s_t is None or c_t is None:
            rows.append(dict(code=code, shares=s_t, flow1D=None, flow5D=None))
            continue
        flow1D = None
        if code in prev1['shares'] and number(prev1['shares'][code]) is not None:
            flow1D = (s_t - number(prev1['shares'][code])) * c_t / 1e8
        flow5D = None
        if prev5 is not None and code in prev5['shares'] and number(prev5['shares'][code]) is not None:
            flow5D = (s_t - number(prev5['shares'][code])) * c_t / 1e8
        rows.append(dict(code=code, shares=s_t,
                         flow1D=round(flow1D, 3) if flow1D is not None else None,
                         flow5D=round(flow5D, 3) if flow5D is not None else None))
    return dict(available=True, asOf=today['date'],
                generatedAt=datetime.now(timezone.utc).isoformat(),
                source='东方财富 最新份额 推算', rows=rows)


if __name__ == '__main__':
    value = compute()
    path = ROOT / 'etf-net-subscription.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(path)
    n = sum(1 for r in value['rows'] if r.get('flow1D') is not None)
    print('ETF net-subscription (Eastmoney shares): asOf=' + str(value.get('asOf')) +
          ' with_flow=' + str(n) + '/' + str(len(value['rows'])))
