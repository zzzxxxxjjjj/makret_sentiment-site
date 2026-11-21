"""Refresh public replacements without requiring an RQData login."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
INDEXES = (
    ("000001", "sh-composite-close-excel", "sh-ma100", "上证综指"),
    ("000300", "hs300-close", "hs300-ma100", "沪深300"),
    ("000985", "allshare-close", "windall-ma100", "中证全指"),
    ("000852", "csi1000-close", None, "中证1000"),
    ("000688", "star50-close", None, "科创50"),
)


def read(name):
    path = ROOT / name
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def save(name, payload):
    path = ROOT / name
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def points(frame, column, target):
    import pandas as pd
    dates = pd.to_datetime(frame["日期"], errors="coerce")
    values = pd.to_numeric(frame[column], errors="coerce")
    observations = {}
    for stamp, value in zip(dates, values):
        if pd.notna(stamp) and pd.notna(value) and math.isfinite(float(value)):
            day = stamp.date().isoformat()
            if day <= target:
                observations[day] = float(value)
    return [{"date": day, "value": value} for day, value in sorted(observations.items())]


def collect(ak, target):
    import pandas as pd
    previous = read("akshare-public-inputs.json")
    series = {item["id"]: item for item in previous.get("series", [])}
    errors = []

    def put(sid, name, unit, incoming, source):
        if not incoming:
            raise ValueError(f"No completed observations for {sid}")
        # A provider change replaces the full series, never appends to an
        # incompatible historical calculation.
        old = series.get(sid, {}).get("points", [])
        if old and old[-1]["date"] > incoming[-1]["date"]:
            raise ValueError(f"Refusing date rollback for {sid}")
        series[sid] = dict(id=sid, name=name, unit=unit, points=incoming, source=source)

    def tail(sid):
        old = series.get(sid, {}).get("points", [])
        return (pd.Timestamp(old[-1]["date"]) + timedelta(days=1)).strftime("%Y%m%d") if old else "20150101"

    def merged(sid, incoming):
        values = {p["date"]: p for p in series.get(sid, {}).get("points", [])}
        values.update({p["date"]: p for p in incoming})
        return [values[d] for d in sorted(values)]

    for code, sid, distance, name in INDEXES:
        try:
            frame = ak.stock_zh_index_hist_csindex(
                symbol=code, start_date=tail(sid), end_date=target.replace("-", ""))
            close = merged(sid, points(frame, "收盘", target))
            if len(close) < 100:
                raise ValueError(f"Insufficient price history for {code}")
            put(sid, name, "点", close, f"AKShare / 中证指数 {code} 收盘价")
            if distance:
                price = pd.Series([p["value"] for p in close])
                bias = (price / price.rolling(100).mean() - 1) * 100
                incoming = [{"date": p["date"], "value": float(bias.iloc[i])}
                            for i, p in enumerate(close) if pd.notna(bias.iloc[i])]
                put(distance, name + "距100日均线", "%", incoming, f"AKShare / 中证指数 {code}，100日均线")
        except Exception as exc:
            errors.append({"source": f"index-{code}", "error": str(exc)[:240]})

    for code, sid, name in (
        ("000300", "hs300-turnover", "沪深300换手率"),
        ("000852", "csi1000-turnover", "中证1000换手率"),
        ("000688", "star50-turnover", "科创50换手率"),
    ):
        try:
            frame = ak.index_zh_a_hist(
                symbol=code, period="daily", start_date=tail(sid),
                end_date=target.replace("-", ""))
            history = merged(sid, points(frame, "换手率", target))
            history = [p for p in history if 0 <= p["value"] <= 100]
            if len(history) < 126 or history[-1]["date"] != target or not any(p["value"] for p in history[-20:]):
                raise ValueError("Incomplete index turnover history through " + target)
            put(sid, name, "%", history, "AKShare / 东方财富指数换手率")
        except Exception as exc:
            errors.append({"source": sid, "error": str(exc)[:240]})

    # The public spot feed has no reliable historical-date selector. Only use
    # it after the close of today's confirmed trading session.
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if target == now.date().isoformat() and now.hour >= 18:
        try:
            spot = ak.stock_zh_a_spot_em()
            codes = spot["代码"].astype(str).str.zfill(6)
            spot = spot[codes.str.match(r"^(00|30|60|68|43|83|87|88|92)")]
            amount = pd.to_numeric(spot["成交额"], errors="coerce")
            turnover = pd.to_numeric(spot["换手率"], errors="coerce")
            valid = spot[(amount > 0) & (turnover >= 0)].copy()
            if len(valid) < 4000:
                raise ValueError("Incomplete all-share closing snapshot")
            amount = pd.to_numeric(valid["成交额"])
            turnover = pd.to_numeric(valid["换手率"])
            count = math.ceil(len(valid) * .05)
            metrics = [
                ("market-turnover", "全A等权日换手率", float(turnover.mean())),
                ("top5-concentration", "成交额前5%个股占比", float(amount.nlargest(count).sum()/amount.sum()*100)),
            ]
            baseline = read("rqdata-broad-sentiment.json")
            for sid, name, value in metrics:
                old = next((s.get("points", []) for s in baseline.get("series", []) if s["id"] == sid), [])
                existing = series.get(sid, {}).get("points", [])
                merged = {p["date"]: p for p in old + existing}
                merged[target] = {"date": target, "value": value}
                put(sid, name, "%", [merged[d] for d in sorted(merged)],
                    "AKShare / 东方财富收盘快照，沪深北A股有成交样本；早期历史保留原数据")
        except Exception as exc:
            errors.append({"source": "all-share-closing-snapshot", "error": str(exc)[:240]})

    # Both exchanges publish financing in yuan. Require both on the same date.
    try:
        end = target.replace("-", "")
        start = (pd.Timestamp(target) - timedelta(days=30)).strftime("%Y%m%d")
        sh = ak.stock_margin_sse(start_date=start, end_date=end)
        sh["date"] = pd.to_datetime(sh["信用交易日期"].astype(str)).dt.strftime("%Y-%m-%d")
        calendar = [d for d in sh["date"].unique() if d <= target]
        rows = []
        for day in sorted(calendar)[-5:]:
            sz = ak.stock_margin_szse(date=day.replace("-", ""))
            if len(sz) != 1:
                raise ValueError(f"Missing Shenzhen market total on {day}")
            sse = sh[sh["date"] == day]
            if len(sse) != 1:
                raise ValueError(f"Ambiguous Shanghai market total on {day}")
            balance = (float(sse.iloc[0]["融资余额"]) + float(sz.iloc[0]["融资余额"])) / 1e8
            buy = (float(sse.iloc[0]["融资买入额"]) + float(sz.iloc[0]["融资买入额"])) / 1e8
            if not all(math.isfinite(x) and x >= 0 for x in [balance, buy]):
                raise ValueError("Invalid financing totals")
            rows.append((day, balance, buy))
        for sid, name, position in [("financing-balance", "融资余额", 1), ("alla-financing-buy", "全A融资买入额", 2)]:
            incoming = [{"date": row[0], "value": row[position]} for row in rows]
            old = series.get(sid, {}).get("points", [])
            # Exchange totals retain the same unit and definition.
            baseline = read("rqdata-broad-sentiment.json")
            earlier = next((s.get("points", []) for s in baseline.get("series", []) if s["id"] == sid), [])
            old = earlier + old
            merged = {p["date"]: p for p in old + incoming}
            put(sid, name, "亿元", [merged[d] for d in sorted(merged)],
                "AKShare / 沪深交易所融资汇总，人民币亿元；早期历史保留原数据")
    except Exception as exc:
        errors.append({"source": "financing", "error": str(exc)[:240]})

    output = dict(targetDate=target, generatedAt=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                  series=list(series.values()), errors=errors)
    save("akshare-public-inputs.json", output)
    return output


def apply_public_inputs(payload, directory):
    path = Path(directory) / "akshare-public-inputs.json"
    if not path.exists():
        return payload
    public = json.loads(path.read_text(encoding="utf-8"))
    series = {item["id"]: item for item in payload.get("series", [])}
    for incoming in public.get("series", []):
        sid = incoming["id"]
        old = series.get(sid, {})
        latest = incoming["points"][-1]["date"] if incoming.get("points") else ""
        old_date = max((p["date"] for p in old.get("points", [])), default="")
        if latest and latest >= old_date:
            series[sid] = incoming
    for card in payload.get("cards", []):
        if card.get("id") in {"market-turnover", "top5-concentration"}:
            item = series.get(card["id"], {})
            if item.get("source", "").startswith("AKShare") and item.get("points"):
                history = [p["value"] for p in item["points"][-250:]]
                last = item["points"][-1]
                card.update(value=last["value"], asOf=last["date"], source=item["source"],
                            percentile=sum(v <= last["value"] for v in history)/len(history)*100)
        if card.get("id") == "ma-distance":
            keys = ["sh-ma100", "hs300-ma100", "windall-ma100"]
            rows = [series.get(k, {}) for k in keys]
            if all(r.get("points") for r in rows):
                dates = [r["points"][-1]["date"] for r in rows]
                if len(set(dates)) == 1:
                    card.update(asOf=dates[0], source="AKShare / 中证指数",
                                submetrics=[dict(label=name, value=row["points"][-1]["value"], unit="%")
                                            for name, row in zip(["上证综指", "沪深300", "中证全指"], rows)])
    payload["series"] = list(series.values())
    payload["publicSourceStatus"] = {"targetDate": public.get("targetDate"), "errors": public.get("errors", [])}
    return payload


def main():
    import akshare as ak
    import pandas as pd
    import requests
    original = requests.sessions.Session.request
    def bounded(self, method, url, **kwargs):
        kwargs.setdefault("timeout", (8, 25))
        return original(self, method, url, **kwargs)
    requests.sessions.Session.request = bounded
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    limit = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
    dates = pd.to_datetime(ak.tool_trade_date_hist_sina()["trade_date"]).dt.date
    target = max(day for day in dates if day <= limit).isoformat()
    output = collect(ak, target)
    if not output["series"]:
        raise ValueError("No public observations available")
    # Reuse the already validated public SSE share-count collector. Importing
    # the SDK used by the legacy module does not initialize an RQData session.
    try:
        from rqdata_late_market_refresh import refresh_sse_etf, SSE_AKSHARE_ETFS
        snapshot = read("rqdata-broad-sentiment.json")
        share_cache = {}
        changed = False
        for code, metadata in SSE_AKSHARE_ETFS.items():
            changed = refresh_sse_etf(snapshot, pd.Timestamp(target).date(), code, metadata, share_cache) or changed
        if changed:
            save("rqdata-broad-sentiment.json", snapshot)
    except Exception as exc:
        output["errors"].append({"source": "sse-etf", "error": str(exc)[:240]})
        save("akshare-public-inputs.json", output)
    if os.environ.get("DEFER_DASHBOARD_BUILD") == "1":
        if output["errors"]:
            raise RuntimeError("Public sources incomplete")
        return
    import broad_sentiment as broad
    broad.ENABLE_RQDATA_REFRESH = False
    payload = broad._build_payload(force=True)
    broad.save_page_cache(payload)
    from data_freshness import write_report
    write_report(target, errors=output["errors"], calendar=[str(d) for d in dates if abs((d-limit).days) <= 90])
    print(json.dumps({"targetDate": target, "series": len(output["series"]), "errors": output["errors"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
