"""Rebuild descriptive timing observations; missing evidence never becomes a vote.

v2 restores daily observation updates, not unvalidated portfolio recommendations.
Thresholds follow signal-study/signal-rules.json: +/-0.4, module +/-0.25,
minimum two families and 60% coverage. No parameter fitting.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build(payload):
    series = {s['id']: s.get('points', []) for s in payload['series']}
    calendar = sorted({p['date'] for p in series.get('allshare-close', [])
                       if isinstance(p.get('value'), (int, float))})
    if not calendar:
        raise ValueError('Missing benchmark calendar')
    target = calendar[-1]
    # Only completed weeks: a following session establishes the previous week's end.
    weeks = {}
    for day in calendar:
        weeks.setdefault(datetime.fromisoformat(day).isocalendar()[:2], []).append(day)
    keys = list(weeks)
    decision = weeks[keys[-2]][-1] if len(keys) > 1 else None

    def points(key):
        return sorted([p for p in series.get(key, []) if p['date'] <= target
                       and isinstance(p.get('value'), (int, float))
                       and not isinstance(p['value'], bool) and math.isfinite(p['value'])],
                      key=lambda p: p['date'])

    def factor(key, name, mode='score', direction=1):
        ps = points(key)
        result = {'id': key, 'name': name, 'asOf': ps[-1]['date'] if ps else None,
                  'score': None, 'vote': None}
        if not ps or ps[-1]['date'] != target:
            result['reason'] = '数据尚未到核验日'
            return result
        value = ps[-1]['value']
        if mode == 'rank':
            if len(ps) < 252:
                result['reason'] = '不足252个历史观测'
                return result
            hist = [p['value'] for p in ps[-756:]]
            value = 100 * (sum(v < value for v in hist) + .5 * sum(v == value for v in hist)) / len(hist)
        score = direction * (value / 50 - 1)
        result.update(score=score, vote=1 if score >= .4 else -1 if score <= -.4 else 0)
        return result

    groups = [
        ('情绪', [factor('rqdata-above-ma20-breadth', '20日均线上方广度'),
                   factor('market-turnover', '全A换手率（反向拥挤观察）', 'rank', -1)]),
        ('资金流', [factor('broad-etf-flow', '宽基ETF净流入', 'rank'),
                    factor('financing-net', '融资净流入', 'rank')]),
        ('风格', []), ('期权波动率', []),
        ('期货期权持仓', [factor('pcr-oi-ma3-sz50', '50ETF持仓PCR', 'rank'),
                          factor('pcr-oi-ma3-hs300', '300ETF持仓PCR', 'rank')]),
    ]
    rows = []
    for name, factors in groups:
        valid = [f['vote'] for f in factors if f['vote'] is not None]
        # The two PCR contracts belong to one signal family; never count twice.
        enough = name not in ('风格', '期权波动率', '期货期权持仓') and len(valid) >= 2 and len(valid) / len(factors) >= .6
        mean = sum(valid) / len(valid) if enough else None
        rows.append({'name': name, 'vote': None if mean is None else 1 if mean >= .25 else -1 if mean <= -.25 else 0,
                     'factors': factors, 'reason': '' if enough else '独立信号族或数据覆盖不足；暂不投票'})
    styles = []
    for key, name in [('hs300-close', '大盘 · 沪深300'), ('csi1000-close', '中小盘 · 中证1000'),
                      ('star50-close', '成长代理 · 科创50'), ('dividend-close', '价值代理 · 红利')]:
        ps = points(key)
        current = len(ps) >= 121 and ps[-1]['date'] == target
        styles.append({'name': name, 'asOf': ps[-1]['date'] if ps else None,
                       'momentum120': ps[-1]['value'] / ps[-121]['value'] - 1 if current else None})
    return {'available': True, 'version': 'observations-v2', 'asOf': target,
            'generatedAt': datetime.now(timezone.utc).isoformat(), 'lastDecisionDate': decision,
            'moduleVotes': rows, 'styles': styles, 'compositeMean': None,
            'notes': ['v2重建于2026-11-04，与旧快照不拼接；每日更新实际观察值。',
                      '方向阈值沿用研究规则：标准分≥0.4为+1、≤−0.4为−1；模块均值阈值±0.25，至少两个独立信号族且覆盖60%。',
                      '历史分位使用最近最多756个观测，至少252个；不同ETF的PCR属于同一信号族。',
                      '风格仅展示120日实际涨跌；缺少估值及风格资金流时不生成原50/30/20综合分。成长代理未包含创业板。',
                      '当前研究没有正式准入的方向信号；观察票不代表经过验证的买卖信号，暂不生成总方向及仓位。',
                      '周度日期取已有下一周行情确认的上周最后交易日；不代表成交或已执行调仓。']}


def refresh(root=ROOT):
    payload = json.loads((root / 'broad-sentiment-page-cache.json').read_text(encoding='utf-8-sig'))['payload']
    value = build(payload)
    path = root / 'position-advice.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return value


if __name__ == '__main__':
    print(json.dumps({'asOf': refresh()['asOf'], 'version': 'observations-v2'}))
