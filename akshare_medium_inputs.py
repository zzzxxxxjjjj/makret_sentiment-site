"""Collect verified public inputs for a future CSI All Share medium-term model.

This snapshot is deliberately separate from the published medium-term score:
CSI dividend history currently covers only about 20 days, and AKShare has no
verified daily series for the Wind partial-debt mixed fund index (885003.WI).
Neither series may be silently replaced with a differently defined fund index.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = BASE_DIR / "akshare-medium-inputs.json"
CSI_ALL_SHARE = "000985"
CDB_CURVE = "政策性金融债(国开)"


def day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return round(value, 6) if math.isfinite(value) else None


def points(frame, date_column, value_column, *, as_of, positive=True):
    result = {}
    for row in frame.to_dict("records"):
        dt = day(row.get(date_column))
        value = number(row.get(value_column))
        if not dt or dt > as_of or value is None or (positive and value <= 0):
            continue
        result[dt] = value
    return [{"date": dt, "value": result[dt]} for dt in sorted(result)]


def merge(old, incoming):
    values = {row["date"]: row["value"] for row in old if row.get("date") and number(row.get("value")) is not None}
    values.update({row["date"]: row["value"] for row in incoming})
    return [{"date": dt, "value": values[dt]} for dt in sorted(values)]


def previous_series(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {item["id"]: item.get("points", []) for item in data.get("series", [])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def fetch(as_of, output=DEFAULT_OUTPUT, *, ak=None):
    if ak is None:
        import akshare as ak

    target = date.fromisoformat(as_of)
    history_start = (target - timedelta(days=5 * 366)).strftime("%Y%m%d")
    history = ak.stock_zh_index_hist_csindex(
        symbol=CSI_ALL_SHARE, start_date=history_start, end_date=target.strftime("%Y%m%d")
    )
    valuation = ak.stock_zh_index_value_csindex(symbol=CSI_ALL_SHARE)
    old = previous_series(output)
    # AKShare currently requests only page 1 (50 tenor rows), so a multi-day
    # query silently returns the first day. Request each weekday separately.
    prior_bonds = old.get("cdb-10y-close-yield", [])
    start = target - timedelta(days=29)
    if prior_bonds:
        start = max(start, date.fromisoformat(prior_bonds[-1]["date"]) - timedelta(days=3))
    bond_rows = []
    cursor = start
    while cursor <= target:
        if cursor.weekday() < 5:
            stamp = cursor.strftime("%Y%m%d")
            try:
                daily = ak.bond_china_close_return(
                    symbol=CDB_CURVE, period="1", start_date=stamp, end_date=stamp,
                )
                bond_rows.extend(points(daily[daily["期限"] == 10], "日期", "到期收益率", as_of=as_of))
            except (KeyError, ValueError):
                # Non-trading dates have no curve observations.
                pass
        cursor += timedelta(days=1)
    definitions = (
        ("csi-all-share-close", "中证全指收盘价", history, "收盘"),
        ("csi-all-share-pe-rolling", "中证全指滚动市盈率", history, "滚动市盈率"),
        ("csi-all-share-dividend-yield", "中证全指股息率（计算用股本）", valuation, "股息率2"),
    )
    series = []
    for sid, name, frame, column in definitions:
        merged = merge(old.get(sid, []), points(frame, "日期", column, as_of=as_of))
        if not merged:
            raise ValueError(f"AKShare returned no valid data for {sid}")
        series.append({"id": sid, "name": name, "asOf": merged[-1]["date"], "points": merged})

    bond_points = merge(prior_bonds, bond_rows)
    if not bond_points:
        raise ValueError("AKShare returned no valid CDB 10Y close yield")
    series.append({"id": "cdb-10y-close-yield", "name": "国开债10年期收盘到期收益率",
                   "asOf": bond_points[-1]["date"], "points": bond_points})

    payload = {
        "targetDate": as_of,
        "source": "AKShare / China Securities Index / ChinaMoney",
        "indexCode": CSI_ALL_SHARE,
        "readyForPublishedMediumScore": False,
        "pending": [
            "未核实 AKShare 中真正的偏债混合型基金指数日线，保留原 885003.WI，不以其他基金类别冒充",
            "中证全指股息率公开接口仅返回近期数据，尚不足以重算原三年历史标准化",
        ],
        "series": series,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = fetch(args.as_of, args.output)
    print(json.dumps({item["id"]: item["asOf"] for item in result["series"]}, ensure_ascii=False))
