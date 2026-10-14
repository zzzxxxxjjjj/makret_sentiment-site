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
        options = json.loads((Path(directory) / "rqdata-options-pcr.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        options = {}
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
    payload["series"] = list(series.values())
    target = max(filter(None, (payload.get("asOf"), options.get("asOf"))), default=None)
    watched = []
    for sid, item in series.items():
        if not (sid.startswith("pcr-") or sid in {"financing-activity", "hs300-financing-activity",
                "sse50-financing-activity", "star50-financing-activity", "csi1000-financing-activity"}
                or sid in {"land-connect-turnover-ma20", "new-equity-fund-shares"}):
            continue
        dates = [p["date"] for p in item.get("points", []) if p.get("value") is not None]
        actual = max(dates, default=None)
        manual = sid == "new-equity-fund-shares" or (sid.startswith("pcr-") and not options)
        status = "missing" if not actual else "current" if actual == target else "manual" if manual else "delayed"
        item["updateInfo"] = {"asOf": actual, "targetDate": target, "status": status,
                              "mode": "Wind快照" if manual else "每日自动更新",
                              "source": item.get("source") or ("Wind/RQData择新" if sid.startswith("land-connect") else "RQData")}
        watched.append({"id": sid, "name": item.get("name", sid), **item["updateInfo"]})
    expected = {"financing-activity": "全A融资买入额占比", "hs300-financing-activity": "沪深300融资买入额占比",
                "sse50-financing-activity": "上证50融资买入额占比", "star50-financing-activity": "科创50融资买入额占比",
                "csi1000-financing-activity": "中证1000融资买入额占比",
                "land-connect-turnover-ma20": "陆股通成交总额 MA5", "new-equity-fund-shares": "新成立偏股型基金份额"}
    for sid, name in expected.items():
        if sid not in series:
            watched.append({"id": sid, "name": name, "asOf": None, "targetDate": target, "status": "missing",
                            "mode": "Wind快照" if sid == "new-equity-fund-shares" else "每日自动更新"})
    payload["freshness"] = {"targetDate": target, "items": watched,
                            "delayedCount": sum(item["status"] != "current" for item in watched)}
    return payload

