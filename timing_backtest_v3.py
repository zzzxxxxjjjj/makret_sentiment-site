# -*- coding: utf-8 -*-
"""
双周期择时 v3：四象限仓位框架（取代 v1/v2 的零散 ΔW 规则）
================================================================
设计要点（按用户要求）：
  1) 四象限仓位框架：按"慢线绝对位置 × 快线绝对位置"分四类。
     - 慢线（中期情绪 M）采用 3 年滚动窗口归一化为分位 L∈[0,1]
       （解决 v1 全样本标定下"2022 后性价比中枢下行"的漂移问题）。
     - 快线（短期情绪 S）为项目已有的 0-100 绝对分，直接 F=S/100∈[0,1]。
     - 以 (L,F) 为坐标，对 4 个角点目标仓位做双线性插值，得到连续目标权重；
       角点本身即"四象限"的四类立场。
  2) 死区/滞后调仓：信号变化超阈值才调仓，默认 |Δtarget| ≥ 5pp 才再平衡
     （周频检查 + 5pp 死区，压低无意义的微抖动换手）。
  3) 纪律夹紧 [W_MIN, W_MAX]，绝不满仓/空仓；现金/债券作空仓部分。

对比对象：买入持有 / v1 双周期（基线）/ v2b 硬上下限 / 仅中期 / v3 四象限。
数据源：broad-sentiment-page-cache.json（本地缓存，共同区间 2022-2026，样本受限，仅整合验证）。
"""
import json, math
from datetime import date, timedelta

CACHE = r"C:\Users\DELL\Documents\Codex\2026-07-17/http-127-0-0-1-codex\ifind-market-sentiment-site\broad-sentiment-page-cache.json"
OUT = r"C:\Users\DELL\Documents\Codex\2026-07-17/http-127-0-0-1-codex\ifind-market-sentiment-site\timing_backtest_v3_results.json"

W_MIN, W_MAX = 20.0, 95.0
COST_ONEWAY = 0.0010
REBALANCE_EVERY = 5          # 周频检查
REBAL_THRESHOLD = 5.0        # 死区：目标仓位与当前仓位差 ≥5pp 才调仓
SLOW_WIN_CAL_DAYS = 1095     # 慢线 3 年滚动窗口（日历日）
SLOW_WIN_MIN_DAYS = 252      # 最少 1 年历史才给信号

# 四象限角点目标仓位（%权益）—— 慢线行 × 快线列
#           快线低(F≈0)   快线高(F≈1)
# 慢线低(L≈0):   20           40
# 慢线高(L≈1):   65           90
W_LOW_FLOW,  W_LOW_FHIGH  = 20.0, 40.0
W_HIGH_FLOW, W_HIGH_FHIGH = 65.0, 90.0

def pdate(s): return date.fromisoformat(s[:10])

def load():
    d = json.load(open(CACHE, encoding="utf-8"))["payload"]
    eq, short = {}, {}
    for pt in d["cycleComparison"]["points"]:
        if pt.get("windAll") is not None:
            eq[pdate(pt["date"])] = float(pt["windAll"])
        diag = pt.get("diagnostics") or {}
        short[pdate(pt["date"])] = {
            "s": pt.get("sentiment"), "phase": pt.get("phase"),
            "div": diag.get("priceBreadthDivergence"), "b60": diag.get("breadth60Confirmation"),
            "topRisk": diag.get("topRisk"), "bottomRepair": diag.get("bottomRepair")}
    series = {s["id"]: s for s in d.get("series", [])}
    def mk(sid):
        return {pdate(p["date"]): p.get("value") for p in series.get(sid, {}).get("points", [])}
    med = {"composite": mk("medium-term-sentiment"), "erp": mk("medium-erp-score"),
           "position": mk("medium-position-score"), "fin60": mk("medium-financing-balance-change-60d-score"),
           "breadth60": mk("medium-breadth60-score")}
    return eq, short, med

def ffill(m, asof):
    val = None
    for dt in sorted(m):
        if dt <= asof and m[dt] is not None: val = m[dt]
        if dt > asof: break
    return val

def daily_series(m, eq_dates):
    """把可能非日频的序列前填成与 eq 对齐的日频序列。"""
    s = {}
    for dt in eq_dates:
        s[dt] = ffill(m, dt)
    return s

def slow_pct(med_daily, dt):
    """慢线 3 年滚动窗口分位：当前 M 在 [dt-3y, dt] 中的百分位排名 ∈[0,1]。"""
    lo = dt - timedelta(days=SLOW_WIN_CAL_DAYS)
    vals = [v for d, v in med_daily.items() if lo <= d <= dt and v is not None]
    if len(vals) < SLOW_WIN_MIN_DAYS:
        return None
    cur = med_daily.get(dt)
    if cur is None:
        return None
    below = sum(1 for v in vals if v < cur)
    return below / len(vals)

def bilinear(L, F):
    """四象限双线性插值 → 目标权益仓位(%)。"""
    w = (W_LOW_FLOW * (1 - L) * (1 - F)
         + W_LOW_FHIGH * (1 - L) * F
         + W_HIGH_FLOW * L * (1 - F)
         + W_HIGH_FHIGH * L * F)
    return max(W_MIN, min(W_MAX, w))

def quadrant_label(L, F):
    sl = "慢高" if L >= 0.5 else "慢低"
    fl = "快高" if F >= 0.5 else "快低"
    return f"{sl}+{fl}"

def v3_target(med_daily, short, dt):
    L = slow_pct(med_daily, dt)
    sig = short.get(dt)
    S = sig.get("s") if sig else None
    if L is None or S is None:
        return None, None, None
    F = max(0.0, min(1.0, S / 100.0))
    return bilinear(L, F), L, F

# ---------- v1 基线（零散 ΔW）与 v2b 对照，复用 v2 逻辑 ----------
def calibrate_base(med, train_dates):
    vals = sorted(v for v in (ffill(med["composite"], dt) for dt in train_dates) if v is not None)
    return vals[int(0.05 * len(vals))], vals[int(0.95 * len(vals))]

def med_base_weight(med, dt, p5, p95):
    M = ffill(med["composite"], dt)
    if M is None: return None
    base = 40.0 + (M - p5) / (p95 - p5) * 45.0 if p95 > p5 else 50.0
    fin60 = ffill(med["fin60"], dt); pos = ffill(med["position"], dt); erp = ffill(med["erp"], dt)
    if fin60 is not None and fin60 < 20: base -= 3
    if pos is not None and pos > 70: base -= 2
    if erp is not None and erp > 60: base += 2
    return max(W_MIN, min(W_MAX, base))

def short_overlay(short, dt):
    sig = short.get(dt)
    if sig is None or sig["s"] is None: return None
    s, ph, o = sig["s"], sig["phase"], 0.0
    if ph == "bottom": o += 15.0
    elif ph == "rising": o += 5.0
    elif ph == "falling": o -= 10.0
    elif ph == "top": o -= 20.0
    br, tr, div = sig.get("bottomRepair"), sig.get("topRisk"), sig.get("div")
    if br is not None and br >= 55: o += 5.0
    if tr is not None and tr >= 45: o -= 10.0
    if div is not None and div >= 20: o -= 5.0
    if s < 25: o += 10.0
    elif s > 70: o -= 10.0
    return o

def dual_target_v1(med, short, dt, p5, p95):
    wb = med_base_weight(med, dt, p5, p95)
    if wb is None: return None
    ov = short_overlay(short, dt)
    if ov is None: return max(W_MIN, min(W_MAX, wb))
    return max(W_MIN, min(W_MAX, wb + ov))

UP_FLOOR, DOWN_CAP = 75.0, 30.0
def regime(eq, dt):
    dates = [d for d in eq if d <= dt]
    if len(dates) < 60: return "osc"
    wins = [eq[d] for d in dates[-60:]]
    ma20 = sum(wins[-20:]) / 20.0; ma60 = sum(wins) / 60.0
    r = ma20 / ma60 - 1.0
    if r > 0.02: return "up"
    if r < -0.02: return "down"
    return "osc"
eq_global = {}
def target_v2b(med, short, dt, p5, p95):
    wb = med_base_weight(med, dt, p5, p95)
    if wb is None: return None
    rg = regime(eq_global, dt)
    if rg == "up": return max(W_MIN, min(W_MAX, max(wb, UP_FLOOR)))
    if rg == "down": return max(W_MIN, min(W_MAX, min(wb, DOWN_CAP)))
    ov = short_overlay(short, dt)
    tw = wb + ov if ov is not None else wb
    return max(W_MIN, min(W_MAX, tw))

def simulate(eq, weights, dates, rf, rebal_thr=REBAL_THRESHOLD):
    dates = sorted(dates)
    ret = {dates[i]: eq[dates[i]] / eq[dates[i - 1]] - 1.0 for i in range(1, len(dates))}
    nav = 1.0; pos = 0.0; ns = []; turnover = 0.0
    for i, dt in enumerate(dates):
        if i == 0:
            ns.append((dt, nav)); continue
        r_eq = ret[dt]; r_cash = rf / 252.0
        nav *= (1 + (pos / 100.0 * r_eq + (1 - pos / 100.0) * r_cash))
        if i % REBALANCE_EVERY == 0:
            tw = weights.get(dt)
            if tw is not None and abs(tw - pos) >= rebal_thr:
                traded = abs(tw - pos) / 100.0; turnover += traded
                nav *= (1 - traded * COST_ONEWAY); pos = tw
        ns.append((dt, nav))
    return ns, turnover

def metrics(nav_series, eq, weights, yrs_window):
    dates = [d for d, _ in nav_series]; nav = [v for _, v in nav_series]
    rets = [nav[i] / nav[i - 1] - 1 for i in range(1, len(nav))]
    yrs = len(nav) / 252.0; tot = nav[-1] - 1; ann = (1 + tot) ** (1 / yrs) - 1 if yrs > 0 else 0
    peak = nav[0]; mdd = 0
    for v in nav: peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    mu = sum(rets) / len(rets); sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets))
    sharpe = mu / sd * math.sqrt(252) if sd > 0 else 0
    avg_w = sum((weights.get(d) or 0) for d in dates) / len(dates)
    eq_tot = eq[dates[-1]] / eq[dates[0]] - 1; eq_ann = (1 + eq_tot) ** (1 / yrs) - 1 if yrs > 0 else 0
    rd = ann / abs(mdd) if mdd != 0 else 0
    return {"years": round(yrs, 2), "total_return": round(tot, 4), "annualized": round(ann, 4),
            "max_drawdown": round(mdd, 4), "sharpe": round(sharpe, 2),
            "return_drawdown": round(rd, 3), "avg_equity_weight": round(avg_w, 1),
            "benchmark_annualized": round(eq_ann, 4), "excess_annualized": round(ann - eq_ann, 4)}

def run(eq, short, med, med_daily, dates, p5, p95, rf):
    w_v1 = {dt: dual_target_v1(med, short, dt, p5, p95) for dt in dates}
    w_v2b = {dt: target_v2b(med, short, dt, p5, p95) for dt in dates}
    w_med = {dt: med_base_weight(med, dt, p5, p95) for dt in dates}
    # v3 四象限
    w_v3 = {}; qcount = {}
    for dt in dates:
        tw, L, F = v3_target(med_daily, short, dt)
        w_v3[dt] = tw
        if L is not None:
            q = quadrant_label(L, F); qcount[q] = qcount.get(q, 0) + 1
    nb = {dt: 100.0 for dt in dates}
    nv3, t3 = simulate(eq, w_v3, dates, rf)
    nv1, t1 = simulate(eq, w_v1, dates, rf)
    nv2b, t2b = simulate(eq, w_v2b, dates, rf)
    nm, tm = simulate(eq, w_med, dates, rf)
    nbh, _ = simulate(eq, nb, dates, rf)
    yrs = len(dates) / 252.0
    return {
        "buy_hold": metrics(nbh, eq, nb, yrs),
        "v1_dual(base)": metrics(nv1, eq, w_v1, yrs),
        "v2b_hardFloor": metrics(nv2b, eq, w_v2b, yrs),
        "medium_only": metrics(nm, eq, w_med, yrs),
        "v3_quadrant": metrics(nv3, eq, w_v3, yrs),
        "annualized_turnover": {"v1": round(t1 / yrs, 2), "v2b": round(t2b / yrs, 2),
                                "medium_only": round(tm / yrs, 2), "v3_quadrant": round(t3 / yrs, 2)},
        "v3_quadrant_days": qcount,
    }

def main():
    global eq_global
    eq, short, med = load()
    eq_global = eq
    med_daily = daily_series(med["composite"], sorted(eq))
    all_dates = sorted(eq)
    common = [dt for dt in all_dates if ffill(med["composite"], dt) is not None
              and (short.get(dt) or {}).get("s") is not None]
    p5, p95 = calibrate_base(med, common)
    res = {
        "design": {
            "framework": "四象限双线性仓位：慢线3年滚动分位 L × 快线绝对分 F=S/100",
            "anchors_pct": {"慢低+快低": W_LOW_FLOW, "慢低+快高": W_LOW_FHIGH,
                            "慢高+快低": W_HIGH_FLOW, "慢高+快高": W_HIGH_FHIGH},
            "rebalance": f"周频检查，死区 |Δ|≥{REBAL_THRESHOLD:.0f}pp 才调仓",
            "clamp": [W_MIN, W_MAX], "slow_window_days": SLOW_WIN_CAL_DAYS,
        },
        "calibration_M_p5_p95_full_sample": [round(p5, 1), round(p95, 1)],
        "common_window": {"start": common[0].isoformat(), "end": common[-1].isoformat(),
                          "n": len(common),
                          "note": "本地缓存中周期自2022起；仅整合验证，非正式样本外"},
        "RF_1.8%_cash": run(eq, short, med, med_daily, common, p5, p95, 0.018),
        "RF_3.5%_bond_sleeve": run(eq, short, med, med_daily, common, p5, p95, 0.035),
    }
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
