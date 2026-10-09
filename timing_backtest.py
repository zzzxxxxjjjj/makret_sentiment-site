# -*- coding: utf-8 -*-
"""
双周期择时 + 仓位管理：基于本项目已有情绪指标的回测骨架（v2，训练/样本外切分）
数据源：broad-sentiment-page-cache.json（已内含 point-in-time 历史序列）
权益基准：中证全指（windAll）
短周期信号：短期情绪分 / 相位 / 价格-广度背离 / 顶底修复诊断
中周期信号：中期情绪综合分 + ERP / 股债位置差 / 60日融资变化 分项
"""
import json, math
from datetime import date

CACHE = r"C:\Users\DELL\Documents\Codex\2026-07-17/http-127-0-0-1-codex\ifind-market-sentiment-site\broad-sentiment-page-cache.json"
OUT = r"C:\Users\DELL\Documents\Codex\2026-07-17/http-127-0-0-1-codex\ifind-market-sentiment-site\timing_backtest_results.json"

W_MIN, W_MAX = 20.0, 95.0
COST_ONEWAY = 0.0010
REBALANCE_EVERY = 5
RF_ANNUAL = 0.018
TRAIN_RATIO = 0.60

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
        out = {}
        for p in series.get(sid, {}).get("points", []):
            out[pdate(p["date"])] = p.get("value")
        return out
    med = {"composite": mk("medium-term-sentiment"), "erp": mk("medium-erp-score"),
           "position": mk("medium-position-score"), "fin60": mk("medium-financing-balance-change-60d-score"),
           "breadth60": mk("medium-breadth60-score")}
    return eq, short, med

def ffill(m, asof):
    val=None
    for dt in sorted(m):
        if dt<=asof and m[dt] is not None: val=m[dt]
        if dt>asof: break
    return val

def calibrate_base(med, train_dates):
    vals=[ffill(med["composite"],dt) for dt in train_dates]
    vals=[v for v in vals if v is not None]
    vals.sort()
    p5=vals[int(0.05*len(vals))]; p95=vals[int(0.95*len(vals))]
    return p5,p95

def med_base_weight(med, dt, p5, p95):
    M=ffill(med["composite"],dt)
    if M is None: return None
    base=40.0+(M-p5)/(p95-p5)*(85.0-40.0) if p95>p5 else 50.0
    fin60=ffill(med["fin60"],dt); pos=ffill(med["position"],dt); erp=ffill(med["erp"],dt)
    if fin60 is not None and fin60<20: base-=3
    if pos is not None and pos>70: base-=2
    if erp is not None and erp>60: base+=2
    return max(W_MIN,min(W_MAX,base))

def short_overlay(short, dt):
    sig=short.get(dt)
    if sig is None or sig["s"] is None: return None
    s=sig["s"]; ph=sig["phase"]; o=0.0
    if ph=="bottom": o+=15.0
    elif ph=="rising": o+=5.0
    elif ph=="falling": o-=10.0
    elif ph=="top": o-=20.0
    br=sig.get("bottomRepair"); tr=sig.get("topRisk"); div=sig.get("div")
    if br is not None and br>=55: o+=5.0
    if tr is not None and tr>=45: o-=10.0
    if div is not None and div>=20: o-=5.0
    if s<25: o+=10.0
    elif s>70: o-=10.0
    return o

def target(med, short, dt, use_short, p5, p95):
    wb=med_base_weight(med,dt,p5,p95)
    if wb is None: return None
    if not use_short: return max(W_MIN,min(W_MAX,wb))
    ov=short_overlay(short,dt)
    if ov is None: return max(W_MIN,min(W_MAX,wb))
    return max(W_MIN,min(W_MAX,wb+ov))

def simulate(eq, weights, dates):
    dates=sorted(dates)
    ret={dates[i]: eq[dates[i]]/eq[dates[i-1]]-1.0 for i in range(1,len(dates))}
    nav=1.0; pos=0.0; ns=[]; turnover=0.0
    for i,dt in enumerate(dates):
        if i==0: ns.append((dt,nav)); continue
        r_eq=ret[dt]; r_cash=RF_ANNUAL/252.0
        nav*=(1+(pos/100.0*r_eq+(1-pos/100.0)*r_cash))
        if i%REBALANCE_EVERY==0:
            tw=weights.get(dt)
            if tw is not None and abs(tw-pos)>=0.5:
                traded=abs(tw-pos)/100.0; turnover+=traded
                nav*=(1-traded*COST_ONEWAY); pos=tw
        ns.append((dt,nav))
    return ns, turnover

def metrics(nav_series, eq, weights):
    dates=[d for d,_ in nav_series]; nav=[v for _,v in nav_series]
    rets=[nav[i]/nav[i-1]-1 for i in range(1,len(nav))]
    yrs=len(nav)/252.0; tot=nav[-1]-1; ann=(1+tot)**(1/yrs)-1 if yrs>0 else 0
    peak=nav[0]; mdd=0
    for v in nav: peak=max(peak,v); mdd=min(mdd,v/peak-1)
    mu=sum(rets)/len(rets); sd=math.sqrt(sum((r-mu)**2 for r in rets)/len(rets))
    sharpe=mu/sd*math.sqrt(252) if sd>0 else 0
    avg_w=sum((weights.get(d) or 0) for d in dates)/len(dates)
    eq_tot=eq[dates[-1]]/eq[dates[0]]-1; eq_ann=(1+eq_tot)**(1/yrs)-1 if yrs>0 else 0
    return {"years":round(yrs,2),"total_return":round(tot,4),"annualized":round(ann,4),
            "max_drawdown":round(mdd,4),"sharpe":round(sharpe,2),
            "avg_equity_weight":round(avg_w,1),"benchmark_annualized":round(eq_ann,4),
            "excess_annualized":round(ann-eq_ann,4)}

def run_window(eq, short, med, dates, p5, p95, label):
    w_med={dt:target(med,short,dt,False,p5,p95) for dt in dates}
    w_du={dt:target(med,short,dt,True,p5,p95) for dt in dates}
    nm,to_m=simulate(eq,w_med,dates); nd,to_d=simulate(eq,w_du,dates)
    nb,_=simulate(eq,{dt:100.0 for dt in dates},dates)
    return {"label":label,"medium_only":metrics(nm,eq,w_med),"dual_horizon":metrics(nd,eq,w_du),
            "buy_hold":metrics(nb,eq,{dt:100.0 for dt in dates}),
            "annualized_turnover":{"medium_only":round(to_m/(len(dates)/252.0),2),
                                   "dual_horizon":round(to_d/(len(dates)/252.0),2)}}

def main():
    eq,short,med=load()
    all_dates=sorted(eq)
    # 共同可交易区间：短+中信号都非空
    common=[dt for dt in all_dates if ffill(med["composite"],dt) is not None
            and (short.get(dt) or {}).get("s") is not None]
    # 标定区间取自共同区间自身的历史分位（本地中周期历史较短，仅作整合验证；
    # 正式标定应改用项目已有的 2018-2026 组件回测样本）
    p5,p95=calibrate_base(med, common)
    res={}
    res["calibration_M_p5_p95"]=[round(p5,1),round(p95,1)]
    res["common_window"]={"start":common[0].isoformat(),"end":common[-1].isoformat(),
                          "n":len(common),
                          "note":"本地缓存中周期序列仅自2022起；下方为整合验证，非正式样本外"}
    res["integration_2022_2026"]=run_window(eq,short,med,common,p5,p95,"共同区间整合(2022-2026)")
    last=common[-1]
    res["current_recommendation"]={
        "asOf":last.isoformat(),"med_base":round(med_base_weight(med,last,p5,p95),1),
        "dual_target":round(target(med,short,last,True,p5,p95),1),
        "med_only_target":round(target(med,short,last,False,p5,p95),1),
        "med_composite":ffill(med["composite"],last),
        "short_sentiment":(short.get(last) or {}).get("s"),
        "short_phase":(short.get(last) or {}).get("phase")}
    json.dump(res,open(OUT,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
    print(json.dumps(res,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
