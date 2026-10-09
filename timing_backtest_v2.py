# -*- coding: utf-8 -*-
"""
双周期择时 v2：引入中银证券《情绪周期择时》的两大核心方法
  1) 趋势前置判断 (regime filter)：万得全A MA20/MA60 - 1，>+2% 上行 / <-2% 下行 / 其余 震荡
     - 上行：抬高慢线卖出阈值（不轻易减仓，捕捉趋势）
     - 下行：压低慢线买入阈值（不轻易加仓，规避接飞刀）
  2) 快线(短期情绪)仅限震荡市使用：上行/下行市忽略短期叠加，避免"上行市过早卖、下行市过早买"
  3) 债券替代现金：RF 用 中证全债 近似收益（默认 3.5%，做敏感度）
数据源：broad-sentiment-page-cache.json（本地缓存，共同区间 2022-2026，样本受限，仅整合验证）
"""
import json, math
from datetime import date

CACHE = r"C:\Users\DELL\Documents\Codex\2026-07-17/http-127-0-0-1-codex\ifind-market-sentiment-site\broad-sentiment-page-cache.json"
OUT = r"C:\Users\DELL\Documents\Codex\2026-07-17/http-127-0-0-1-codex\ifind-market-sentiment-site\timing_backtest_v2_results.json"

W_MIN, W_MAX = 20.0, 95.0
COST_ONEWAY = 0.0010
REBALANCE_EVERY = 5
TRAIN_RATIO = 0.60
REGIME_TILT = 12.0          # 上行+12 / 下行-12 的战略倾斜（对应研报"抬高/压低阈值"）
UP_THR, DOWN_THR = 0.02, -0.02

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

def calibrate_base(med, train_dates):
    vals = [ffill(med["composite"], dt) for dt in train_dates]
    vals = sorted(v for v in vals if v is not None)
    return vals[int(0.05*len(vals))], vals[int(0.95*len(vals))]

def med_base_weight(med, dt, p5, p95):
    M = ffill(med["composite"], dt)
    if M is None: return None
    base = 40.0 + (M-p5)/(p95-p5)*45.0 if p95 > p5 else 50.0
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

# ---- 趋势 regime 过滤（研报 §2.1/§2.2 核心）----
def regime(eq, dt):
    dates = [d for d in eq if d <= dt]
    if len(dates) < 60: return "osc"
    wins = [eq[d] for d in dates[-60:]]
    ma20 = sum(wins[-20:])/20.0; ma60 = sum(wins)/60.0
    r = ma20/ma60 - 1.0
    if r > UP_THR: return "up"
    if r < DOWN_THR: return "down"
    return "osc"

# ---- v2 目标仓位：regime gating ----
def target_v2(med, short, dt, p5, p95, use_short):
    wb = med_base_weight(med, dt, p5, p95)
    if wb is None: return None
    rg = regime(eq_global, dt)
    if rg == "osc":
        if not use_short: return max(W_MIN, min(W_MAX, wb))
        ov = short_overlay(short, dt)
        if ov is None: return max(W_MIN, min(W_MAX, wb))
        return max(W_MIN, min(W_MAX, wb + ov))
    else:
        # 趋势市：战略基线 + regime 倾斜，忽略快线（避免过早反向）
        tilt = REGIME_TILT if rg == "up" else -REGIME_TILT
        return max(W_MIN, min(W_MAX, wb + tilt))

eq_global = {}  # 供 regime() 闭包使用

def dual_target_v1(med, short, dt, p5, p95):  # 原 v1 双周期（作对照）
    wb = med_base_weight(med, dt, p5, p95)
    if wb is None: return None
    ov = short_overlay(short, dt)
    if ov is None: return max(W_MIN, min(W_MAX, wb))
    return max(W_MIN, min(W_MAX, wb + ov))

def simulate(eq, weights, dates, rf):
    dates = sorted(dates)
    ret = {dates[i]: eq[dates[i]]/eq[dates[i-1]]-1.0 for i in range(1, len(dates))}
    nav = 1.0; pos = 0.0; ns = []; turnover = 0.0
    for i, dt in enumerate(dates):
        if i == 0: ns.append((dt, nav)); continue
        r_eq = ret[dt]; r_cash = rf/252.0
        nav *= (1 + (pos/100.0*r_eq + (1-pos/100.0)*r_cash))
        if i % REBALANCE_EVERY == 0:
            tw = weights.get(dt)
            if tw is not None and abs(tw-pos) >= 0.5:
                traded = abs(tw-pos)/100.0; turnover += traded
                nav *= (1 - traded*COST_ONEWAY); pos = tw
        ns.append((dt, nav))
    return ns, turnover

def metrics(nav_series, eq, weights, yrs_window):
    dates = [d for d, _ in nav_series]; nav = [v for _, v in nav_series]
    rets = [nav[i]/nav[i-1]-1 for i in range(1, len(nav))]
    yrs = len(nav)/252.0; tot = nav[-1]-1; ann = (1+tot)**(1/yrs)-1 if yrs > 0 else 0
    peak = nav[0]; mdd = 0
    for v in nav: peak = max(peak, v); mdd = min(mdd, v/peak-1)
    mu = sum(rets)/len(rets); sd = math.sqrt(sum((r-mu)**2 for r in rets)/len(rets))
    sharpe = mu/sd*math.sqrt(252) if sd > 0 else 0
    avg_w = sum((weights.get(d) or 0) for d in dates)/len(dates)
    eq_tot = eq[dates[-1]]/eq[dates[0]]-1; eq_ann = (1+eq_tot)**(1/yrs)-1 if yrs > 0 else 0
    rd = ann/abs(mdd) if mdd != 0 else 0   # 收益回撤比
    return {"years": round(yrs, 2), "total_return": round(tot, 4), "annualized": round(ann, 4),
            "max_drawdown": round(mdd, 4), "sharpe": round(sharpe, 2),
            "return_drawdown": round(rd, 3),
            "avg_equity_weight": round(avg_w, 1), "benchmark_annualized": round(eq_ann, 4),
            "excess_annualized": round(ann-eq_ann, 4)}

# v2b：更忠实研报机制的"硬上下限"——上行市直接不卖(≥75%)，下行市直接不买(≤30%)，震荡市才跟随信号
UP_FLOOR, DOWN_CAP = 75.0, 30.0
def target_v2b(med, short, dt, p5, p95):
    wb = med_base_weight(med, dt, p5, p95)
    if wb is None: return None
    rg = regime(eq_global, dt)
    if rg == "up":
        return max(W_MIN, min(W_MAX, max(wb, UP_FLOOR)))
    if rg == "down":
        return max(W_MIN, min(W_MAX, min(wb, DOWN_CAP)))
    ov = short_overlay(short, dt)
    tw = wb + ov if ov is not None else wb
    return max(W_MIN, min(W_MAX, tw))

def run(eq, short, med, dates, p5, p95, rf):
    w_v1 = {dt: dual_target_v1(med, short, dt, p5, p95) for dt in dates}
    w_v2 = {dt: target_v2(med, short, dt, p5, p95, True) for dt in dates}
    w_v2b = {dt: target_v2b(med, short, dt, p5, p95) for dt in dates}
    w_med = {dt: med_base_weight(med, dt, p5, p95) for dt in dates}
    nb = {dt: 100.0 for dt in dates}
    nv1, t1 = simulate(eq, w_v1, dates, rf); nv2, t2 = simulate(eq, w_v2, dates, rf)
    nv2b, t2b = simulate(eq, w_v2b, dates, rf)
    nm, tm = simulate(eq, w_med, dates, rf); nbh, _ = simulate(eq, nb, dates, rf)
    yrs = len(dates)/252.0
    return {
        "buy_hold": metrics(nbh, eq, nb, yrs),
        "v1_dual": metrics(nv1, eq, w_v1, yrs),
        "v2_tilt±12": metrics(nv2, eq, w_v2, yrs),
        "v2b_hardFloor75_Cap30": metrics(nv2b, eq, w_v2b, yrs),
        "medium_only": metrics(nm, eq, w_med, yrs),
        "annualized_turnover": {"v1": round(t1/yrs, 2), "v2": round(t2/yrs, 2),
                                 "v2b": round(t2b/yrs, 2), "medium_only": round(tm/yrs, 2)},
        "regime_days": {rg: sum(1 for dt in dates if regime(eq, dt) == rg) for rg in ("up", "down", "osc")},
    }

def main():
    global eq_global
    eq, short, med = load()
    eq_global = eq
    all_dates = sorted(eq)
    common = [dt for dt in all_dates if ffill(med["composite"], dt) is not None
              and (short.get(dt) or {}).get("s") is not None]
    p5, p95 = calibrate_base(med, common)
    res = {"calibration_M_p5_p95": [round(p5, 1), round(p95, 1)],
           "common_window": {"start": common[0].isoformat(), "end": common[-1].isoformat(), "n": len(common),
                             "note": "本地缓存中周期自2022起；仅整合验证，非正式样本外"},
           "RF_1.8%_cash": run(eq, short, med, common, p5, p95, 0.018),
           "RF_3.5%_bond_sleeve": run(eq, short, med, common, p5, p95, 0.035)}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
