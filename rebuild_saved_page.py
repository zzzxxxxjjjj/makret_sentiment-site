"""Rebuild the displayed snapshot and freshness report from saved observations only."""
import argparse
import copy
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from data_freshness import read, write_report
from market_data_sync import apply_market_data_sync
from akshare_public_refresh import apply_public_inputs
import broad_sentiment as broad

BASE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target")
    args = parser.parse_args()
    # An unchanged older artifact must never roll back a newer committed breadth recovery.
    try:
        committed=json.loads(subprocess.check_output(["git","show","HEAD:rqdata-breadth-sentiment.json"],cwd=BASE,stderr=subprocess.DEVNULL,timeout=10))
        working=read(BASE,"rqdata-breadth-sentiment.json")
        if committed.get("asOf","")>working.get("asOf",""):
            (BASE/"rqdata-breadth-sentiment.json").write_text(json.dumps(committed,ensure_ascii=False),encoding="utf-8")
            status=json.loads(subprocess.check_output(["git","show","HEAD:breadth-public-status.json"],cwd=BASE,stderr=subprocess.DEVNULL,timeout=10))
            (BASE/"breadth-public-status.json").write_text(json.dumps(status,ensure_ascii=False),encoding="utf-8")
    except (OSError,ValueError,subprocess.SubprocessError):
        pass
    previous = read(BASE, "data-freshness.json")
    calendar = previous.get("tradingCalendar", [])
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    limit = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
    target = args.target or os.environ.get("DAILY_TARGET_DATE") or max((d for d in calendar if d <= str(limit)), default=None)
    if not target:
        raise ValueError("No verified completed trading date available")
    original = read(BASE, "broad-sentiment-page-cache.json")
    payload = copy.deepcopy(original.get("payload") or {})
    if not payload.get("cards") or not payload.get("series"):
        raise ValueError("Previous valid page snapshot is required")
    payload = apply_public_inputs(apply_market_data_sync(payload, BASE), BASE)
    series = {s["id"]: s for s in payload["series"]}
    for filename in ("ifind-index-turnover.json", "akshare-margin-risk.json", "rqdata-breadth-sentiment.json", "public-etf-flow.json"):
        source = read(BASE, filename)
        for incoming in source.get("series", []):
            if not incoming.get("points"): continue
            old = series.get(incoming["id"], {})
            old_date = max((p["date"] for p in old.get("points", [])), default="")
            new_date = max(p["date"] for p in incoming["points"])
            if new_date >= old_date:
                merged = {p["date"]:p for p in old.get("points", [])}
                merged.update({p["date"]:p for p in incoming["points"]})
                series[incoming["id"]] = {**old, **incoming, "points":[merged[d] for d in sorted(merged)],
                                           "source":incoming.get("source") or source.get("source", "iFind")}
    # Recompute using the current model's real inputs; retain its actual date.
    medium = broad.broad_market_medium_term_sentiment_snapshot()
    for incoming in medium.get("series", []):
        series[incoming["id"]] = incoming
    # Reuse the original 80% breadth + 20% CSI RSI model for dependent charts.
    exact=read(BASE,"rqdata-breadth-sentiment.json")
    equity=read(BASE,"cloud-market-inputs.json").get("inputs",{}).get("equity",[])
    price_map={p["date"]:p["value"] for p in equity}
    aligned=[{**p,"windAll":price_map[p["date"]]} for p in exact.get("points",[]) if p.get("date") in price_map]
    if aligned:
        derived=broad.add_price_breadth_diagnostics(broad.blend_breadth_with_rsi(aligned,price_map,rsi_weight=0.20))
        old_cycle=payload.get("cycleComparison",{})
        prior={p["date"]:p for p in old_cycle.get("points",[])}
        overlap=[abs(p["sentiment"]-prior[p["date"]]["sentiment"]) for p in derived if p["date"] in prior][-5:]
        compatible=not prior or (len(overlap)>=3 and max(overlap)<=0.1)
        payload["derivedBreadthStatus"]={"asOf":derived[-1]["date"] if derived else None,"compatible":compatible,"recentOverlapMaxError":max(overlap,default=None)}
        if derived and compatible:
            cutoff=max(prior,default="")
            prior.update({p["date"]:p for p in derived if p["date"]>cutoff})
            points=[prior[d] for d in sorted(prior)]
            last=points[-1];diagnostics=last.get("diagnostics",{})
            payload["cycleComparison"]={**old_cycle,"asOf":last["date"],"points":points,
                "score":last["sentiment"],"phase":last.get("phase"),"phaseLabel":last.get("phaseLabel"),
                "label":broad.cycle_label(last["sentiment"]),"diagnostics":diagnostics,
                "sourceMode":"exact","priceLabel":"中证全指",
                "description":"原规则：全A市场广度80%＋中证全指14日Wilder RSI（三日平滑）20%；保留历史，仅补新增日期。"}
            sid="price-breadth-divergence"
            incoming=[{"date":p["date"],"value":p["diagnostics"]["priceBreadthDivergence"]} for p in points if p.get("diagnostics",{}).get("priceBreadthDivergence") is not None]
            if incoming:
                old=series.get(sid,{})
                merged={p["date"]:p for p in old.get("points",[])}
                merged.update({p["date"]:p for p in incoming if p["date"]>max((v["date"] for v in old.get("points",[])),default="")})
                series[sid]={**old,"id":sid,"name":"价格—广度背离","unit":"分","source":"原广度诊断规则，核验历史后补算","points":[merged[d] for d in sorted(merged)]}
            for card in payload["cards"]:
                if card.get("id")=="breadth-sentiment":
                    metrics=last.get("metrics",{})
                    values={"原始市场广度分":last.get("originalBreadthSentiment"),"中证全指 RSI":last.get("rsi14"),
                        "20日新高家数":metrics.get("newHigh"),"20日新低家数":metrics.get("newLow"),
                        "新高-新低广度":metrics.get("nhnlBreadth"),"均线上方广度":metrics.get("aboveMaBreadth"),
                        "60日净新高广度":metrics.get("nhnlBreadth60"),"60日均线上方":metrics.get("aboveMaBreadth60"),
                        "60日广度确认":diagnostics.get("breadth60Confirmation"),"价格—广度背离":diagnostics.get("priceBreadthDivergence"),
                        "顶部风险":diagnostics.get("topRisk"),"底部修复":diagnostics.get("bottomRepair"),"有效样本":metrics.get("eligible")}
                    texts={"周期阶段":str(last.get("phaseLabel",""))+" · "+broad.cycle_label(last["sentiment"]),
                        "60日状态":str(diagnostics.get("cycleConfirmationLabel",""))+" · "+str(diagnostics.get("breadth60AsOf","")),
                        "背离状态":str(diagnostics.get("priceBreadthDivergenceLabel",""))+" · "+str(diagnostics.get("priceBreadthAsOf","")),
                        "前瞻观察":diagnostics.get("leadingSignal","")}
                    for metric in card.get("submetrics",[]):
                        label=metric.get("label","")
                        if label in values:metric["value"]=values[label]
                        if label in texts:metric.update(value=None,text=texts[label])
                    card.update(asOf=last["date"],value=last["sentiment"],source="已核验全A广度＋中证全指RSI；沿用原80/20规则")
    # Refresh the ETF card from the same verified points displayed in its chart.
    etf_points=series.get("broad-etf-flow",{}).get("points",[])
    if etf_points:
        values={p["date"]:p["value"] for p in etf_points}
        last=max(values)
        for card in payload["cards"]:
            if card.get("id")=="broad-etf-flow":
                card.update(asOf=last,value=values[last],source=series["broad-etf-flow"].get("source"))
                for metric in card.get("submetrics",[]):
                    label=metric.get("label","")
                    window=5 if "5" in label else 20 if "20" in label else 1
                    dates=[d for d in calendar if d<=last][-window:]
                    metric["value"]=sum(values[d] for d in dates) if len(dates)==window and all(d in values for d in dates) else None
    payload["series"] = list(series.values())
    payload["generatedAt"] = now.isoformat(timespec="seconds")
    payload["rebuildTargetDate"] = target
    for card in payload["cards"]:
        if card.get("id") == "medium-term-sentiment":
            if not series.get("medium-term-sentiment", {}).get("points"):
                card.update(value=None, asOf=None, percentile=None, submetrics=[], description="新中证估值口径历史积累中；未缩短原窗口，不沿用旧分数")
            item = series.get("medium-term-sentiment", {})
            if item.get("points"):
                last = item["points"][-1]
                card.update(value=last["value"], asOf=last["date"])
    broad.ENABLE_RQDATA_REFRESH = False
    broad.save_page_cache(payload)
    state = read(BASE, "daily-update-status.json")
    failures = state.get("failedStages", []) if state.get("targetDate") == target else []
    # Independent successful collectors supersede an older batch-stage error.
    for stage, filename in (("etf", "etf-market.json"), ("industry-flow", "sw-industry-flow.json")):
        current = read(BASE, filename)
        if current.get("available") and current.get("asOf") == target:
            failures = [name for name in failures if name != stage]
    etf_status=read(BASE,"etf-share-recovery-status.json")
    if etf_status.get("ok") and etf_status.get("targetDate")==target:
        failures=[name for name in failures if name!="etf-shares"]
    errors = [{"source":name, "error":"Daily collection stage failed; actual older dates retained"} for name in failures]
    public = read(BASE, "akshare-public-inputs.json")
    errors.extend(public.get("errors", []))
    report = write_report(target, calendar=calendar, errors=errors)
    print(json.dumps({"targetDate":target, "current":report["currentDailyCount"],
                      "total":report["dailyCount"], "lagging":len(report["laggingDaily"]),
                      "errors":report["errors"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
