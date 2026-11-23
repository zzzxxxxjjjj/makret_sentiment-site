from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from retired_provider import client as rq

from rqdata_connection import initialize_rqdata
from rqdata_trading_day import completed_trading_date

from breadth_phase import apply_optimized_phases


def batches(items, size=300):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def is_a_share(order_book_id):
    code, _, exchange = str(order_book_id).partition(".")
    if code.startswith(("200", "900")):
        return False
    return exchange in ("XSHG", "XSHE", "XBSE", "XBEI")


def normalize_price_frame(raw):
    if raw is None:
        return pd.DataFrame()
    frame = raw.reset_index()
    rename = {}
    if "datetime" in frame.columns:
        rename["datetime"] = "date"
    if "order_book_ids" in frame.columns:
        rename["order_book_ids"] = "order_book_id"
    frame = frame.rename(columns=rename)
    needed = {"order_book_id", "date", "close", "volume"}
    if not needed.issubset(frame.columns):
        return pd.DataFrame()
    frame = frame[list(needed)].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    return frame.dropna(subset=["order_book_id", "date", "close"])


def calculate_batch(raw, output_start):
    frame = normalize_price_frame(raw)
    if frame.empty:
        return pd.DataFrame()
    frame = frame.sort_values(["order_book_id", "date"])
    grouped = frame.groupby("order_book_id", group_keys=False)
    frame["prevHigh20"] = grouped["close"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).max()
    )
    frame["prevLow20"] = grouped["close"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).min()
    )
    frame["ma20"] = grouped["close"].transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    frame["prevHigh60"] = grouped["close"].transform(
        lambda values: values.shift(1).rolling(60, min_periods=60).max()
    )
    frame["prevLow60"] = grouped["close"].transform(
        lambda values: values.shift(1).rolling(60, min_periods=60).min()
    )
    frame["ma60"] = grouped["close"].transform(
        lambda values: values.rolling(60, min_periods=60).mean()
    )
    frame = frame[frame["date"] >= output_start].copy()
    frame["eligible"] = (
        frame["ma20"].notna()
        & frame["prevHigh20"].notna()
        & frame["prevLow20"].notna()
        & (frame["volume"].fillna(0) > 0)
    )
    # Use strict breakouts versus the previous 20 closes. Including today's
    # close or allowing equality double-counts sideways stocks as repeated
    # highs/lows and can mark the same stock as both.
    frame["newHigh"] = frame["eligible"] & (frame["close"] > frame["prevHigh20"])
    frame["newLow"] = frame["eligible"] & (frame["close"] < frame["prevLow20"])
    frame["aboveMa20"] = frame["eligible"] & (frame["close"] > frame["ma20"])
    frame["eligible60"] = (
        frame["ma60"].notna()
        & frame["prevHigh60"].notna()
        & frame["prevLow60"].notna()
        & (frame["volume"].fillna(0) > 0)
    )
    frame["newHigh60"] = frame["eligible60"] & (frame["close"] > frame["prevHigh60"])
    frame["newLow60"] = frame["eligible60"] & (frame["close"] < frame["prevLow60"])
    frame["aboveMa60"] = frame["eligible60"] & (frame["close"] > frame["ma60"])
    return frame.groupby("date", as_index=False).agg(
        eligible=("eligible", "sum"),
        newHigh=("newHigh", "sum"),
        newLow=("newLow", "sum"),
        aboveMa20=("aboveMa20", "sum"),
        eligible60=("eligible60", "sum"),
        newHigh60=("newHigh60", "sum"),
        newLow60=("newLow60", "sum"),
        aboveMa60=("aboveMa60", "sum"),
    )


def merge_daily(parts):
    fields = (
        "eligible", "newHigh", "newLow", "aboveMa20",
        "eligible60", "newHigh60", "newLow60", "aboveMa60",
    )
    counters = defaultdict(lambda: {field: 0 for field in fields})
    for part in parts:
        for row in part.itertuples(index=False):
            item = counters[row.date]
            for field in fields:
                item[field] += int(getattr(row, field))
    rows = [{"date": current, **values} for current, values in sorted(counters.items())]
    return pd.DataFrame(rows)


def rolling_percentile(series, window=750, min_periods=120):
    def last_rank(values):
        values = values[np.isfinite(values)]
        if len(values) < min_periods:
            return np.nan
        current = values[-1]
        return (np.sum(values < current) + 0.5 * np.sum(values == current)) / len(values) * 100

    return series.rolling(window, min_periods=min_periods).apply(last_rank, raw=True)


def build_sentiment(daily, percentile_window=750, percentile_min_periods=120):
    daily = daily.sort_values("date").reset_index(drop=True)
    daily = daily[daily["eligible"] > 0].copy()
    daily["nhnlBreadth"] = (daily["newHigh"] - daily["newLow"]) / daily["eligible"] * 100
    daily["newHighBreadth"] = daily["newHigh"] / daily["eligible"] * 100
    daily["newLowBreadth"] = daily["newLow"] / daily["eligible"] * 100
    daily["aboveMaBreadth"] = daily["aboveMa20"] / daily["eligible"] * 100
    daily["nhnlBreadth60"] = np.where(
        daily["eligible60"] > 0,
        (daily["newHigh60"] - daily["newLow60"]) / daily["eligible60"] * 100,
        np.nan,
    )
    daily["aboveMaBreadth60"] = np.where(
        daily["eligible60"] > 0,
        daily["aboveMa60"] / daily["eligible60"] * 100,
        np.nan,
    )
    daily["nhnlChange5"] = daily["nhnlBreadth"].diff(5)
    daily["aboveMaChange5"] = daily["aboveMaBreadth"].diff(5)
    daily["nhnlScore"] = rolling_percentile(
        daily["nhnlBreadth"], percentile_window, percentile_min_periods
    )
    daily["aboveMaScore"] = rolling_percentile(
        daily["aboveMaBreadth"], percentile_window, percentile_min_periods
    )
    daily["nhnlChangeScore"] = rolling_percentile(
        daily["nhnlChange5"], percentile_window, percentile_min_periods
    )
    daily["aboveMaChangeScore"] = rolling_percentile(
        daily["aboveMaChange5"], percentile_window, percentile_min_periods
    )
    daily["nhnl60Score"] = rolling_percentile(
        daily["nhnlBreadth60"], percentile_window, percentile_min_periods
    )
    daily["aboveMa60Score"] = rolling_percentile(
        daily["aboveMaBreadth60"], percentile_window, percentile_min_periods
    )
    daily["breadth60Confirmation"] = (
        daily["nhnl60Score"] * 0.5 + daily["aboveMa60Score"] * 0.5
    )
    daily["rawScore"] = (
        daily["nhnlScore"] * 0.35
        + daily["aboveMaScore"] * 0.35
        + daily["nhnlChangeScore"] * 0.15
        + daily["aboveMaChangeScore"] * 0.15
    )
    daily["sentiment"] = daily["rawScore"].ewm(span=3, adjust=False).mean()
    daily = daily.dropna(subset=["sentiment"])
    points = []
    for row in daily.itertuples(index=False):
        points.append({
            "date": row.date.isoformat(),
            "sentiment": round(float(row.sentiment), 2),
            "metrics": {
                "eligible": int(row.eligible),
                "newHigh": int(row.newHigh),
                "newLow": int(row.newLow),
                "aboveMa20": int(row.aboveMa20),
                "nhnlBreadth": round(float(row.nhnlBreadth), 3),
                "newHighBreadth": round(float(row.newHighBreadth), 3),
                "newLowBreadth": round(float(row.newLowBreadth), 3),
                "aboveMaBreadth": round(float(row.aboveMaBreadth), 3),
                "eligible60": int(row.eligible60),
                "newHigh60": int(row.newHigh60),
                "newLow60": int(row.newLow60),
                "aboveMa60": int(row.aboveMa60),
                "nhnlBreadth60": round(float(row.nhnlBreadth60), 3),
                "aboveMaBreadth60": round(float(row.aboveMaBreadth60), 3),
            },
            "components": {
                "nhnlBreadth": round(float(row.nhnlScore), 1),
                "aboveMaBreadth": round(float(row.aboveMaScore), 1),
                "nhnlChange": round(float(row.nhnlChangeScore), 1),
                "aboveMaChange": round(float(row.aboveMaChangeScore), 1),
                "nhnlBreadth60": round(float(row.nhnl60Score), 1),
                "aboveMaBreadth60": round(float(row.aboveMa60Score), 1),
                "breadth60Confirmation": round(float(row.breadth60Confirmation), 1),
            },
        })
    return apply_optimized_phases(points)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--batch-size", type=int, default=300)
    parser.add_argument("--percentile-window", type=int, default=750)
    parser.add_argument("--percentile-min-periods", type=int, default=120)
    args = parser.parse_args()

    initialize_rqdata()
    end = completed_trading_date(rq)
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    requested_start = start
    previous = {}
    output_path = Path(args.output)
    if output_path.is_file():
        previous = json.loads(output_path.read_text(encoding='utf-8-sig'))
    raw_history = previous.get('dailyCounts', [])
    if raw_history:
        last = date.fromisoformat(raw_history[-1]['date'])
        start = min(end, last - timedelta(days=7))
    fetch_start = start - timedelta(days=120)

    instruments = rq.all_instruments(type="CS")
    if "currency" in instruments.columns:
        instruments = instruments[instruments["currency"].astype(str).str.upper().isin(["CNY", "RMB"])]
    codes = [
        code for code in instruments["order_book_id"].dropna().astype(str).unique()
        if is_a_share(code)
    ]

    daily_parts = []
    completed = 0
    for current_codes in batches(codes, args.batch_size):
        raw = rq.get_price(
            current_codes,
            start_date=fetch_start,
            end_date=end,
            frequency="1d",
            fields=["close", "volume"],
            adjust_type="pre",
            skip_suspended=False,
            expect_df=True,
        )
        part = calculate_batch(raw, start)
        if not part.empty:
            daily_parts.append(part)
        completed += len(current_codes)
        print(json.dumps({"progress": completed, "total": len(codes)}, ensure_ascii=False), flush=True)

    daily = merge_daily(daily_parts)
    if raw_history:
        old = pd.DataFrame(raw_history)
        old['date'] = pd.to_datetime(old['date']).dt.date
        # Drop warmup dates, then retain the verified aggregate history verbatim.
        daily = pd.concat([old[old['date'] < start], daily[daily['date'] >= start]], ignore_index=True)
        daily = daily.drop_duplicates('date', keep='last').sort_values('date')
    else:
        daily = daily[daily['date'] >= requested_start]
    daily_counts = [{**row, 'date': row['date'].isoformat()} for row in daily.to_dict('records')]
    points = build_sentiment(
        daily,
        percentile_window=args.percentile_window,
        percentile_min_periods=args.percentile_min_periods,
    )
    if raw_history:
        kept = [p for p in previous.get('points', []) if p['date'] < start.isoformat()]
        points = kept + [p for p in points if p['date'] >= start.isoformat()]
    latest = points[-1] if points else {}
    payload = {
        "source": "RQData逐股前复权日线",
        "dailyCounts": daily_counts,
        "methodology": {
            "universe": "全部境内A股（含沪深北交所，剔除B股）；20日和60日指标分别要求足够历史且当日有成交",
            "newHighLow": "严格突破此前20个收盘价的新高/新低；(新高家数 - 新低家数) / 当日有效股票数",
            "aboveMa": "收盘价高于20日均线家数 / 当日有效股票数",
            "breadth60": "60日新高-新低广度与60日均线上方广度等权形成中期确认分，不改变短线情绪主分",
            "normalization": f"{args.percentile_window}个交易日滚动分位，至少{args.percentile_min_periods}个样本",
            "smoothing": "3日指数平滑",
            "phase": "顶部沿用高位回落规则；底部要求近10日曾低于25分、5日回升至少5分，并由净新高广度、均线上方广度或新低收缩至少一项确认",
        },
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "asOf": latest.get("date"),
        "score": latest.get("sentiment"),
        "phase": latest.get("phase"),
        "phaseLabel": latest.get("phaseLabel"),
        "components": latest.get("components", {}),
        "metrics": latest.get("metrics", {}),
        "weights": {
            "nhnlBreadth": 35,
            "aboveMaBreadth": 35,
            "nhnlChange": 15,
            "aboveMaChange": 15,
        },
        "stockMasterCount": len(codes),
        "points": points,
        "series": [
            {
                "id": "rqdata-nhnl-breadth",
                "name": "20日新高-新低广度",
                "unit": "%",
                "points": [
                    {"date": item["date"], "value": item["metrics"]["nhnlBreadth"]}
                    for item in points
                ],
            },
            {
                "id": "rqdata-above-ma20-breadth",
                "name": "20日均线上方广度",
                "unit": "%",
                "points": [
                    {"date": item["date"], "value": item["metrics"]["aboveMaBreadth"]}
                    for item in points
                ],
            },
            {
                "id": "rqdata-nhnl-breadth60",
                "name": "60日新高-新低广度",
                "unit": "%",
                "points": [
                    {"date": item["date"], "value": item["metrics"]["nhnlBreadth60"]}
                    for item in points
                ],
            },
            {
                "id": "rqdata-above-ma60-breadth",
                "name": "60日均线上方广度",
                "unit": "%",
                "points": [
                    {"date": item["date"], "value": item["metrics"]["aboveMaBreadth60"]}
                    for item in points
                ],
            },
            {
                "id": "rqdata-breadth60-confirmation",
                "name": "60日广度确认",
                "unit": "分",
                "points": [
                    {"date": item["date"], "value": item["components"]["breadth60Confirmation"]}
                    for item in points
                ],
            },
            {
                "id": "rqdata-breadth-sentiment",
                "name": "RQData市场广度情绪",
                "unit": "分",
                "points": [
                    {"date": item["date"], "value": item["sentiment"]}
                    for item in points
                ],
            },
        ],
    }
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "asOf": payload["asOf"], "points": len(points)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
