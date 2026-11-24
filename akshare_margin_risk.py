"""Publish market-wide margin account risk history from AKShare / Eastmoney."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent
OUTPUT = BASE_DIR / "akshare-margin-risk.json"
MIN_HISTORY = 100


def finite(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def iso_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def transform(frame, as_of):
    required = {
        "日期", "平均维持担保比例", "参与交易的投资者数量",
        "个人投资者数量", "机构投资者数量",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError("AKShare margin account fields missing: " + ", ".join(sorted(missing)))

    guarantee = {}
    participation = {}
    for row in frame.to_dict("records"):
        day = iso_date(row["日期"])
        if day > as_of or len(day) != 10:
            continue
        date.fromisoformat(day)
        ratio = finite(row["平均维持担保比例"])
        if ratio is not None and 50 <= ratio <= 2000:
            guarantee[day] = round(ratio, 4)

        # Eastmoney publishes personal account holders in 10,000 persons,
        # institutional holders and active participants in persons.
        personal = finite(row["个人投资者数量"])
        institutions = finite(row["机构投资者数量"])
        active = finite(row["参与交易的投资者数量"])
        if personal is None or institutions is None or active is None:
            continue
        enrolled = personal * 10000 + institutions
        if enrolled > 0 and 0 <= active <= enrolled:
            participation[day] = round(active / enrolled * 100, 4)

    if min(len(guarantee), len(participation)) < MIN_HISTORY:
        raise ValueError("AKShare margin account history has insufficient valid observations")
    series = [
        {"id": "margin-guarantee-ratio", "name": "市场平均维持担保比例", "unit": "%",
         "points": [{"date": day, "value": value} for day, value in sorted(guarantee.items())]},
        {"id": "margin-investor-participation-ratio", "name": "两融交易投资者参与率", "unit": "%",
         "points": [{"date": day, "value": value} for day, value in sorted(participation.items())]},
    ]
    return {
        "asOf": min(item["points"][-1]["date"] for item in series),
        "source": "AKShare stock_margin_account_info / 东方财富两融账户统计",
        "methodology": "参与交易投资者人数 ÷ (个人两融投资者人数×10000 + 机构两融投资者人数) ×100%；个人投资者原始单位为万名，其余人数为名。",
        "series": series,
    }


def collect(as_of=None, output=OUTPUT, *, ak=None):
    if ak is None:
        import akshare as ak
    as_of = as_of or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    payload = transform(ak.stock_margin_account_info(), as_of)
    if output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        by_id = {item["id"]: item for item in previous.get("series", [])}
        for item in payload["series"]:
            values = {row["date"]: row for row in by_id.get(item["id"], {}).get("points", [])}
            values.update({row["date"]: row for row in item["points"]})
            item["points"] = [values[dt] for dt in sorted(values)]
            by_id[item["id"]] = item
        payload["series"] = list(by_id.values())
        payload["asOf"] = min(item["points"][-1]["date"] for item in payload["series"])
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(output)
    return payload


if __name__ == "__main__":
    from akshare_request_policy import install
    install()
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = collect(args.as_of, args.output)
    print(json.dumps({"asOf": result["asOf"],
                      "observations": {item["id"]: len(item["points"]) for item in result["series"]}},
                     ensure_ascii=False))
