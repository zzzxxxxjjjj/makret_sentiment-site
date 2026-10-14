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
        wind = json.loads((Path(directory) / "wind-market-supplement.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        wind = {}
    for incoming in wind.get("series", []):
        sid = incoming.get("id")
        if sid not in {"new-equity-fund-shares", "land-connect-turnover-ma20"}:
            continue
        current = series.get(sid, {})
        # Shares must retain their original unit; counts are a separate measure.
        if sid == "new-equity-fund-shares" and incoming.get("unit") != "�ڷ�":
            continue
        merged = merge_points(current.get("points", []), incoming.get("points", []))
        series[sid] = {**current, **incoming, "points": merged}
    fund = wind.get("fundShares", {})
    for card in payload.get("cards", []):
        if card.get("id") == "new-equity-fund-shares" and fund.get("asOf", "") >= (card.get("asOf") or ""):
            card.update(asOf=fund["asOf"], value=fund.get("shares20D"), percentile=fund.get("shares20DPercentile"))
            values = {"����": fund.get("shares"), "��5���ۼ�": fund.get("shares5D"), "��20���ۼ�": fund.get("shares20D")}
            for metric in card.get("submetrics", []):
                if metric.get("label") in values:
                    metric["value"] = values[metric["label"]]
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
            series[sid] = {**series.get(sid, {}), "id": sid, "unit": "��",
                           "name": series.get(sid, {}).get("name", f"{key}�ֲ���PCR MA3"),
                           "source": oi.get("source", "Wind����"), "points": moving_average(oi["points"])}
        amount = {p["date"]: p["value"] for p in series.get(f"pcr-amount-{key}", {}).get("points", [])}
        volume = {p["date"]: p["value"] for p in series.get(f"pcr-volume-{key}", {}).get("points", [])}
        ratio = [{"date": dt, "value": round(amount[dt] / volume[dt], 4)}
                 for dt in sorted(amount.keys() & volume.keys()) if volume[dt] > 0]
        if ratio:
            sid = f"pcr-amount-volume-{key}"
            series[sid] = {**series.get(sid, {}), "id": sid, "unit": "��", "name": f"{key}�ɽ���PCR/�ɽ���PCR",
                           "source": oi.get("source", "Wind����"), "points": ratio}
            sid = f"pcr-amount-volume-ma3-{key}"
            positive = [{"date": p["date"], "value": round(1 / p["value"], 4)}
                        for p in moving_average(ratio) if p["value"] > 0]
            series[sid] = {**series.get(sid, {}), "id": sid, "unit": "��", "name": f"{key}PCR������ MA3���������򻯣�",
                           "source": oi.get("source", "Wind����"), "points": positive}
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
                              "mode": "Wind����" if manual or "Wind���" in item.get("source", "") else "ÿ���Զ�����",
                              "source": item.get("source") or ("Wind/RQData����" if sid.startswith("land-connect") else "RQData")}
        watched.append({"id": sid, "name": item.get("name", sid), **item["updateInfo"]})
    expected = {"financing-activity": "ȫA���������ռ��", "hs300-financing-activity": "����300���������ռ��",
                "sse50-financing-activity": "��֤50���������ռ��", "star50-financing-activity": "�ƴ�50���������ռ��",
                "csi1000-financing-activity": "��֤1000���������ռ��",
                "land-connect-turnover-ma20": "½��ͨ�ɽ��ܶ� MA5", "new-equity-fund-shares": "�³���ƫ���ͻ���ݶ�"}
    for sid, name in expected.items():
        if sid not in series:
            watched.append({"id": sid, "name": name, "asOf": None, "targetDate": target, "status": "missing",
                            "mode": "Wind����" if sid == "new-equity-fund-shares" else "ÿ���Զ�����"})
    payload["freshness"] = {"targetDate": target, "items": watched,
                            "delayedCount": sum(item["status"] != "current" for item in watched)}
    return payload
