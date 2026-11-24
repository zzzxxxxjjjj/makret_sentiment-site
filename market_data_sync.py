"""Merge supplemental observations and report actual per-series freshness."""
from __future__ import annotations

import json
from pathlib import Path

PCR_KEYS = ("sz50", "hs300", "csi1000", "star50")


def merge_points(existing, incoming):
    points = {p["date"]: p for p in existing if p.get("date") and p.get("value") is not None}
    points.update({p["date"]: p for p in incoming if p.get("date") and p.get("value") is not None})
    return [points[dt] for dt in sorted(points)]


def moving_average(points, window=3):
    return [{"date": points[i]["date"], "value": round(sum(p["value"] for p in points[i-window+1:i+1]) / window, 4)}
            for i in range(window-1, len(points))]


def apply_market_data_sync(payload, directory):
    series = {item["id"]: item for item in payload.get("series", [])}
    try:
        rqdata = json.loads((Path(directory) / "rqdata-broad-sentiment.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rqdata = {}
    # These three RQData series measure the same index turnover rates as the
    # saved Wind columns. Use the complete RQData history when it is newer;
    # mixing observations from two calculation methods would create a seam.
    daily_turnover_ids = {"hs300-turnover", "csi1000-turnover", "star50-turnover", "star50-close"}
    for incoming in rqdata.get("series", []):
        sid = incoming.get("id")
        if sid not in daily_turnover_ids or not incoming.get("points"):
            continue
        current = series.get(sid, {})
        incoming_date = max((p.get("date", "") for p in incoming["points"]), default="")
        current_date = max((p.get("date", "") for p in current.get("points", [])), default="")
        if incoming_date >= current_date:
            series[sid] = {**current, **incoming, "source": "RQData"}
    try:
        wind = json.loads((Path(directory) / "wind-market-supplement.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        wind = {}
    for incoming in wind.get("series", []):
        sid = incoming.get("id")
        if sid not in {"new-equity-fund-shares", "land-connect-turnover-ma20"}:
            continue
        current = series.get(sid, {})
        # Shares must retain their original unit; counts are a separate measure.
        if sid == "new-equity-fund-shares" and incoming.get("unit") != "亿份":
            continue
        merged = merge_points(current.get("points", []), incoming.get("points", []))
        series[sid] = {**current, **incoming, "points": merged}
    fund = wind.get("fundShares", {})
    for card in payload.get("cards", []):
        if card.get("id") == "new-equity-fund-shares" and fund.get("asOf", "") >= (card.get("asOf") or ""):
            card.update(asOf=fund["asOf"], value=fund.get("shares20D"), percentile=fund.get("shares20DPercentile"))
            values = {"当日": fund.get("shares"), "近5日累计": fund.get("shares5D"), "近20日累计": fund.get("shares20D")}
            for metric in card.get("submetrics", []):
                if metric.get("label") in values:
                    metric["value"] = values[metric["label"]]
    try:
        options = json.loads((Path(directory) / "rqdata-options-pcr.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        options = {}
    try:
        fresh_options=json.loads((Path(directory)/"akshare-options-pcr.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fresh_options={}
    options["series"]=options.get("series",[])+fresh_options.get("series",[])
    options["asOf"]=max(options.get("asOf",""),fresh_options.get("asOf",""))
    for incoming in options.get("series", []):
        sid = incoming.get("id", "")
        if not any(sid == f"pcr-{metric}-{key}" for key in PCR_KEYS for metric in ("oi", "amount", "volume")):
            continue
        current = series.get(sid, {})
        series[sid] = {**current, **incoming, "name": current.get("name") or incoming.get("name", sid),
                       "points": merge_points(current.get("points", []), incoming.get("points", []))}
    # Recompute transforms from the merged raw series, rather than keeping old MA3 tails.
    for key in PCR_KEYS:
        oi = series.get(f"pcr-oi-{key}", {})
        if oi.get("points"):
            sid = f"pcr-oi-ma3-{key}"
            series[sid] = {**series.get(sid, {}), "id": sid, "unit": "倍",
                           "name": series.get(sid, {}).get("name", f"{key}持仓量PCR MA3"),
                           "source": oi.get("source", "Wind快照"), "points": moving_average(oi["points"])}
        amount = {p["date"]: p["value"] for p in series.get(f"pcr-amount-{key}", {}).get("points", [])}
        volume = {p["date"]: p["value"] for p in series.get(f"pcr-volume-{key}", {}).get("points", [])}
        ratio = [{"date": dt, "value": round(amount[dt] / volume[dt], 4)}
                 for dt in sorted(amount.keys() & volume.keys()) if volume[dt] > 0]
        if ratio:
            sid = f"pcr-amount-volume-{key}"
            series[sid] = {**series.get(sid, {}), "id": sid, "unit": "倍", "name": f"{key}成交额PCR/成交量PCR",
                           "source": oi.get("source", "Wind快照"), "points": ratio}
            sid = f"pcr-amount-volume-ma3-{key}"
            positive = [{"date": p["date"], "value": round(1 / p["value"], 4)}
                        for p in moving_average(ratio) if p["value"] > 0]
            series[sid] = {**series.get(sid, {}), "id": sid, "unit": "倍", "name": f"{key}PCR价量比 MA3（倒数正向化）",
                           "source": oi.get("source", "Wind快照"), "points": positive}
    # Canonical display metadata also repairs older cached exports with damaged labels.
    display = {"new-equity-fund-shares": ("新成立偏股型基金份额", "亿份"),
               "land-connect-turnover-ma20": ("陆股通成交总额MA5", "亿元")}
    for key, name in zip(PCR_KEYS, ("上证50", "沪深300", "中证1000", "科创50")):
        for metric, label in (("oi", "持仓量认沽认购比率"), ("amount", "成交额认沽认购比率"), ("volume", "成交量认沽认购比率")):
            display[f"pcr-{metric}-{key}"] = (name + label, "倍")
        display[f"pcr-oi-ma3-{key}"] = (name + "持仓量PCR MA3", "倍")
        display[f"pcr-amount-volume-{key}"] = (name + "成交额PCR/成交量PCR", "倍")
        display[f"pcr-amount-volume-ma3-{key}"] = (name + "PCR价量比 MA3（倒数正向化）", "倍")
    for sid, (name, unit) in display.items():
        if sid in series:
            series[sid].update(name=name, unit=unit)
    payload["series"] = list(series.values())
    target = max(filter(None, (payload.get("asOf"), options.get("asOf"))), default=None)
    watched = []
    for sid, item in series.items():
        if not (sid.startswith("pcr-") or sid in {"financing-activity", "hs300-financing-activity",
                "sse50-financing-activity", "star50-financing-activity", "csi1000-financing-activity"}
                or sid in {"land-connect-turnover-ma20", "new-equity-fund-shares",
                           "hs300-turnover", "csi1000-turnover", "star50-turnover",
                           "windall-turnover", "windall-close-excel", "stock-fund-position"}):
            continue
        dates = [p["date"] for p in item.get("points", []) if p.get("value") is not None]
        actual = max(dates, default=None)
        manual = sid in {"new-equity-fund-shares", "windall-turnover", "windall-close-excel", "stock-fund-position"} or (sid.startswith("pcr-") and not options)
        status = "missing" if not actual else "current" if actual == target else "manual" if manual else "delayed"
        item["updateInfo"] = {"asOf": actual, "targetDate": target, "status": status,
                              "mode": "Wind快照" if manual or "Wind插件" in item.get("source", "") else "每日自动更新",
                              "source": item.get("source") or ("Wind/RQData择新" if sid.startswith("land-connect") else "RQData")}
        watched.append({"id": sid, "name": item.get("name", sid), **item["updateInfo"]})
    expected = {"financing-activity": "全A融资买入额占比", "hs300-financing-activity": "沪深300融资买入额占比",
                "sse50-financing-activity": "上证50融资买入额占比", "star50-financing-activity": "科创50融资买入额占比",
                "csi1000-financing-activity": "中证1000融资买入额占比",
                "land-connect-turnover-ma20": "陆股通成交总额 MA5", "new-equity-fund-shares": "新成立偏股型基金份额",
                "windall-turnover": "万得全A换手率", "windall-close-excel": "万得全A指数",
                "stock-fund-position": "股票型基金估算仓位",
                "hs300-turnover": "沪深300换手率", "csi1000-turnover": "中证1000换手率",
                "star50-turnover": "科创50换手率"}
    for sid, name in expected.items():
        if sid not in series:
            watched.append({"id": sid, "name": name, "asOf": None, "targetDate": target, "status": "missing",
                            "mode": "Wind快照" if sid in {"new-equity-fund-shares", "windall-turnover", "windall-close-excel", "stock-fund-position"} else "每日自动更新"})
    for card in payload.get("cards", []):
        if card.get("id") not in {"sentiment-cycle", "institutional-net-buy", "medium-term-sentiment"}:
            continue
        actual = card.get("asOf")
        watched.append({"id": card["id"], "name": card.get("title", card["id"]),
                        "asOf": actual, "targetDate": target,
                        "status": "missing" if not actual else "current" if actual == target else "manual",
                        "mode": "Wind/Excel快照", "source": card.get("source")})
    payload["freshness"] = {"targetDate": target, "items": watched,
                            "delayedCount": sum(item["status"] != "current" for item in watched)}
    from cloud_display import apply_cloud_display
    return apply_cloud_display(payload, directory)
