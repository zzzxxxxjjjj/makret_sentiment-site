"""Rebuild the displayed snapshot and freshness report from saved observations only."""
import argparse
import copy
import json
import os
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
    for filename in ("ifind-index-turnover.json", "akshare-margin-risk.json", "rqdata-breadth-sentiment.json"):
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
    errors = [{"source":name, "error":"Daily collection stage failed; actual older dates retained"} for name in failures]
    public = read(BASE, "akshare-public-inputs.json")
    errors.extend(public.get("errors", []))
    report = write_report(target, calendar=calendar, errors=errors)
    print(json.dumps({"targetDate":target, "current":report["currentDailyCount"],
                      "total":report["dailyCount"], "lagging":len(report["laggingDaily"]),
                      "errors":report["errors"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
