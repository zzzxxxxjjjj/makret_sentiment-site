"""Layout-compatible research reconstruction. Never overwrite on missing inputs."""
import copy
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
VERSION = 'reconstructed-v3'
ETFS = ['510300.XSHG', '512100.XSHG', '588000.XSHG', '159915.XSHE', '515080.XSHG', '511360.XSHG']
INDICES = ['000300.XSHG', '000852.XSHG', '000688.XSHG', '399006.XSHE', '000922.XSHG']
GROUPS = [('large', '大盘', '沪深300', [0]), ('small', '中小盘', '中证1000', [1]),
          ('growth', '成长', '科创50＋创业板', [2, 3]), ('value', '价值代理', '中证红利', [4])]
NAMES = ['沪深300', '中证1000', '科创50', '创业板', '中证红利', '短融信用债']


def rank(values, inverse=False):
    v = pd.Series(values).dropna().tail(756)
    if len(v) < 126 or not np.isfinite(v).all():
        raise ValueError('Historical percentile needs 126 finite observations')
    score = float(((v < v.iloc[-1]).sum() + .5 * (v == v.iloc[-1]).sum()) / len(v) * 100)
    return 100 - score if inverse else score


def discrete(score):
    return 1 if score >= 70 else -1 if score <= 30 else 0


def vote(scores):
    if len(scores) < 2 or not all(math.isfinite(float(s)) for s in scores):
        raise ValueError('Module needs two complete independent families')
    mean = sum(discrete(s) for s in scores) / len(scores)
    return 1 if mean >= .25 else -1 if mean <= -.25 else 0


def require(s, end, minimum=1):
    s = s.loc[:end]
    if len(s) < minimum or str(s.index[-1])[:10] != end or s.isna().any().any():
        raise ValueError('Missing/stale observations through ' + end)
    if not np.isfinite(s.to_numpy()).all():
        raise ValueError('Nonfinite source data')
    return s


def risk_weights(cov, budgets):
    # Coordinate descent for .5*x'Cx - sum(b*log(x)); positive definite shrinkage.
    x = np.ones(len(budgets))
    for _ in range(2000):
        old = x.copy()
        for i in range(len(x)):
            off = cov[i] @ x - cov[i, i] * x[i]
            x[i] = (-off + np.sqrt(off * off + 4 * cov[i, i] * budgets[i])) / (2 * cov[i, i])
        if np.max(np.abs(x - old)) < 1e-10:
            break
    w = x / x.sum()
    rc = w * (cov @ w) / (w @ cov @ w)
    if np.max(np.abs(rc - budgets / budgets.sum())) > 1e-5:
        raise ValueError('Risk budget did not converge')
    return w


def build(template, data, target, decision):
    p = require(data['prices'], target, 253)
    pe = require(data['pe'], target, 126)
    flows = require(data['flows'], target, 146)
    styles = []
    for sid, name, proxy, ix in GROUPS:
        # Equal-weight average of component scores, not mixed-price averages.
        mom = float(np.mean([rank(p[ETFS[i]].pct_change(120)) for i in ix]))
        val = float(np.mean([rank(pe[INDICES[i]].where(pe[INDICES[i]] > 0), True) for i in ix]))
        flow = float(np.mean([rank(flows[ETFS[i]].rolling(20).sum()) for i in ix]))
        styles.append(dict(id=sid, name=name, proxy=proxy, score=.5*mom+.3*val+.2*flow,
                           momentum=mom, valuation=val, flow=flow,
                           momentum120=float(np.mean([p[ETFS[i]].iloc[-1]/p[ETFS[i]].iloc[-121]-1 for i in ix])),
                           vol60=float(np.mean([p[ETFS[i]].pct_change().tail(60).std()*np.sqrt(252) for i in ix]))))
    styles.sort(key=lambda s: (-s['score'], s['id']))
    for i, s in enumerate(styles):
        s['rank'] = i + 1
    dp = require(p, decision, 253)
    b = require(data['breadth'], decision)
    turnover = require(data['turnover'], decision, 126)
    funding = require(data['funding'], decision, 146)
    pcr = require(data['pcr'], decision, 126)
    iv = require(data['iv'], decision)
    positions = require(data['positions'], decision)
    # IV is a risk veto within research, never described as an up-probability.
    rv = float(require(data['etf50'], decision, 61).pct_change().tail(60).std()*np.sqrt(252))
    implied = float(iv.iloc[-1])
    if not .01 < implied < 3 or rv <= 0:
        raise ValueError('Invalid volatility input')
    iv_vote = -1 if implied > 1.2*rv else 1 if implied < .8*rv else 0
    modules = [
        dict(name='情绪', vote=vote([float(b.iloc[-1]), rank(turnover, True)])),
        dict(name='资金流', vote=vote([rank(funding.rolling(20).sum()), rank(require(flows, decision, 146).sum(axis=1).rolling(20).sum())])),
        dict(name='风格', vote=vote([rank(dp[c].pct_change(120)) for c in ETFS[:5]])),
        dict(name='期权波动率', vote=iv_vote),
        dict(name='期货期权持仓', vote=vote([rank(pcr, True), float(np.clip(50+float(positions.iloc[-1])*1000, 0, 100))])),
    ]
    mean = sum(m['vote'] for m in modules)/5
    signal = int(np.sign(mean))
    returns = dp[ETFS].pct_change().tail(126).dropna()
    if len(returns) != 126:
        raise ValueError('Incomplete covariance window')
    covariance = returns.cov().to_numpy()
    covariance = .75*covariance + .25*np.diag(np.diag(covariance)) + np.eye(6)*1e-12
    models = []
    group_map = {s[0]: s[3] for s in GROUPS}
    for mid, title in [('multidimensional', '多维度风险平价'), ('rotation', '多维度＋风格轮动')]:
        decision_scores = []
        for sid, _, _, ix in GROUPS:
            score = np.mean([.5*rank(dp[ETFS[i]].pct_change(120))
                + .3*rank(require(pe, decision, 126)[INDICES[i]].where(pe[INDICES[i]] > 0), True)
                + .2*rank(require(flows, decision, 146)[ETFS[i]].rolling(20).sum()) for i in ix])
            decision_scores.append((sid, score))
        decision_scores.sort(key=lambda s: (-s[1], s[0]))
        selected = [s[0] for s in decision_scores[:2]] if mid == 'rotation' else []
        indices = sorted(i for sid in selected for i in group_map[sid]) if selected else list(range(5))
        indices = indices+[5] if signal > 0 else [5]
        budget = np.ones(len(indices))
        if mid == 'rotation' and signal > 0:
            budget = np.array([1/len(group_map[next(s for s in selected if i in group_map[s])]) if i != 5 else 1 for i in indices])
        w = np.zeros(6)
        w[indices] = risk_weights(covariance[np.ix_(indices, indices)], budget)
        scale = min(1, .2/w[:5].sum() if w[:5].sum() else 1, .8/w[5] if w[5] else 1)
        w *= scale
        rc = w*(covariance @ w)/(w @ covariance @ w)
        assets = [dict(name=NAMES[i], etf=ETFS[i].split('.')[0], kind='credit' if i==5 else 'equity', weight=float(w[i]), riskShare=float(rc[i])) for i in range(6)]
        cash = float(1-w.sum())
        assets.append(dict(name='现金', etf=None, kind='cash', weight=cash, riskShare=None))
        models.append(dict(id=mid, name=title, posture='重建研究方案', signal=signal,
                           equity=float(w[:5].sum()), credit=float(w[5]), cash=cash, assets=assets,
                           selectedStyles=selected, riskRule='126日协方差、25%对角收缩；整体缩放满足权益20%与信用债80%上限，余量留现金。'))
    out = copy.deepcopy(template)
    out.update(available=True, asOf=target, generatedAt=datetime.now(timezone.utc).isoformat(),
               mode=VERSION, lastDecisionDate=decision, styles=styles, models=models,
               moduleVotes=modules, compositeMean=mean,
               source='RQData行情、指数PE、ETF份额、50ETF期权隐波、IF会员持仓；重建研究版，非旧模型原样复算')
    out['notes'] = [
        '重建研究版v3（2026-11-04）：旧计算程序缺失；保持原页面和50/30/20评分结构，以下规则为公开固定的新实现，未宣称已通过收益有效性验证。',
        '风格：120日动量历史分位50%＋指数PE正值历史反向分位30%＋代理ETF20日净申赎流历史分位20%；分位回看最多756日，至少126个有效观测。成长组两只ETF分项等权。',
        '情绪=20日均线上方广度与反向换手拥挤；资金=20日融资净流入与五只代理ETF净流入；风格=五只ETF绝对动量历史分位等权。',
        '普通因子分数≥70投+1、≤30投−1，否则0；模块票均值≥0.25为+1、≤−0.25为−1，否则0。五维等权，总均值大于0才允许权益参与。',
        '波动率为50ETF近月平值认购和认沽隐波均值，对比60日实现波动：高于1.2倍为−1、低于0.8倍为+1，其余0；属于风险预算规则，不是经验证的方向预测因子。',
        '持仓：50ETF持仓PCR反向历史分位，与IF主力前20会员净多持仓/全合约持仓强度（50＋1000×比值，截断0—100）合成；持仓不等于新增资金。',
        '最近完整周最后交易日形成研究目标；风格轮盘每日重算。轮动目标使用决策日评分前两组，不使用其后的评分选组。',
        '126日协方差加入25%对角收缩；主方案六标的等风险预算，轮动方案两组风格与信用债等组风险预算；整体缩放满足权益≤20%、信用债≤80%，余量现金。',
        '数据不足或校验失败时保留上一次有效快照和原日期；更新状态单独披露。研究目标不代表实际成交。红利是价值代理，不是纯价值。']
    return out


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def dated(raw, field, code=None):
    if raw is None or raw.empty:
        raise ValueError('Empty provider response: ' + field)
    df = raw.reset_index()
    if code and 'order_book_id' in df:
        df = df[df.order_book_id.astype(str) == code]
    day = next((k for k in ['date', 'datetime', 'trading_date'] if k in df), None)
    if day is None or field not in df:
        raise ValueError('Unexpected provider schema: ' + field)
    out = pd.Series(pd.to_numeric(df[field], errors='coerce').to_numpy(), index=pd.to_datetime(df[day]).dt.normalize())
    if out.index.duplicated().any():
        raise ValueError('Duplicated provider dates')
    return out.sort_index()


def fetch(rq, target, decision):
    start = (pd.Timestamp(target)-pd.Timedelta(days=1600)).date()
    raw = rq.get_price(ETFS+['510050.XSHG'], start_date=start, end_date=target, fields='close', adjust_type='pre')
    prices = pd.DataFrame({c: dated(raw, 'close', c) for c in ETFS})
    etf50 = dated(raw, 'close', '510050.XSHG')
    pe = pd.DataFrame({c: dated(rq.index_indicator(c, start_date=start, end_date=target, fields=['pe_ttm']), 'pe_ttm') for c in INDICES})
    units = rq.etf.get_daily_units(ETFS[:5], start, target)
    plain = rq.get_price(ETFS[:5], start_date=start, end_date=target, fields='close', adjust_type='none')
    flows = pd.DataFrame({c: dated(units, 'units', c).diff()*dated(plain, 'close', c) for c in ETFS[:5]}).iloc[1:]
    payload = json.loads((ROOT/'broad-sentiment-page-cache.json').read_text(encoding='utf-8-sig'))['payload']
    series = {s['id']: s['points'] for s in payload['series']}
    def source(key):
        pts = series.get(key, [])
        return pd.Series([p['value'] for p in pts], index=pd.to_datetime([p['date'] for p in pts]), dtype=float).sort_index()
    # Daily inputs already published by the main data pipeline; never forward-fill.
    contracts = rq.all_instruments(type='Option')
    contracts = contracts[(contracts.underlying_order_book_id == '510050.XSHG') &
        (pd.to_datetime(contracts.listed_date) <= pd.Timestamp(decision)) &
        (pd.to_datetime(contracts.de_listed_date) >= pd.Timestamp(decision)+pd.Timedelta(days=7))].copy()
    contracts['expiry'] = pd.to_datetime(contracts.de_listed_date)
    contracts = contracts[contracts.expiry == contracts.expiry.min()]
    spot = require(etf50, decision, 61).iloc[-1]
    ids = []
    for side in ['C', 'P']:
        side_rows = contracts[contracts.option_type == side].copy()
        if side_rows.empty:
            raise ValueError('Incomplete ATM option pair')
        side_rows['distance'] = (pd.to_numeric(side_rows.strike_price)-spot).abs()
        ids.append(side_rows.sort_values(['distance', 'order_book_id']).iloc[0].order_book_id)
    greek = rq.options.get_greeks(ids, start_date=decision, end_date=decision, fields=['iv'])
    iv_values = [require(dated(greek, 'iv', c), decision).iloc[-1] for c in ids]
    iv = pd.Series([np.mean(iv_values)], index=pd.to_datetime([decision]))
    dominant = rq.futures.get_dominant('IF', start_date=decision, end_date=decision)
    contract = str(dominant.iloc[-1])
    net = []
    for side in ['long', 'short']:
        ranks = rq.futures.get_member_rank(contract, start_date=decision, end_date=decision, rank_by=side)
        if ranks is None or len(ranks) < 20:
            raise ValueError('Incomplete IF member rankings')
        ranks = ranks.reset_index().sort_values('rank').head(20)
        if ranks['volume'].isna().any():
            raise ValueError('Missing IF member position')
        net.append(float(ranks.volume.sum()))
    oi = require(dated(rq.get_price(contract, start_date=decision, end_date=decision, fields='open_interest'), 'open_interest'), decision).iloc[-1]
    if oi <= 0:
        raise ValueError('Invalid futures open interest')
    return dict(prices=prices, pe=pe, flows=flows, etf50=etf50,
                breadth=source('rqdata-above-ma20-breadth'), turnover=source('market-turnover'),
                funding=source('financing-net'), pcr=source('pcr-oi-ma3-sz50'), iv=iv,
                positions=pd.Series([(net[0]-net[1])/oi], index=pd.to_datetime([decision])))


def main():
    from rqdata_connection import initialize_rqdata, safe_error
    from rqdata_trading_day import completed_trading_date
    checked = datetime.now(timezone.utc).isoformat()
    target = None
    try:
        import rqdatac as rq
        initialize_rqdata()
        target = completed_trading_date(rq).isoformat()
        days = rq.get_trading_dates(pd.Timestamp(target)-pd.Timedelta(days=25), pd.Timestamp(target)+pd.Timedelta(days=10))
        sessions = pd.Series(pd.to_datetime(days), index=pd.to_datetime(days))
        ends = sessions.groupby(sessions.index.to_period('W-FRI')).max()
        decision = str(ends[ends <= pd.Timestamp(target)].max().date())
        template = json.loads((ROOT/'position-advice.json').read_text(encoding='utf-8-sig'))
        value = build(template, fetch(rq, target, decision), target, decision)
        if value['asOf'] < template['asOf']:
            raise ValueError('Snapshot date rollback refused')
        atomic(ROOT/'position-advice.json', value)
        atomic(ROOT/'position-update-status.json', dict(ok=True, checkedAt=checked, targetDate=target, asOf=target, modelVersion=VERSION))
        print('Position snapshot updated: '+target)
    except Exception as exc:
        # No raw provider exception is published; credential-safe class only.
        previous = json.loads((ROOT/'position-advice.json').read_text(encoding='utf-8-sig'))
        atomic(ROOT/'position-update-status.json', dict(ok=False, checkedAt=checked, targetDate=target,
            asOf=previous.get('asOf'), modelVersion=VERSION,
            message='数据获取或校验失败；已保留上一次有效结果及其实际日期。', errorType=type(exc).__name__))
        print('Position update failed: '+safe_error(exc))
        raise


if __name__ == '__main__':
    main()
