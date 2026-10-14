"""Refresh like-for-like option PCRs, retaining Wind history and real dates."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import rqdatac as rq

from rqdata_connection import initialize_rqdata, safe_error
from rqdata_trading_day import CHINA_TIME, completed_trading_date

BASE_DIR = Path(__file__).resolve().parent
DEFINITIONS = (
    ("sz50", "上证50", "510050.XSHG"),
    ("hs300", "沪深300", "510300.XSHG"),
    ("csi1000", "中证1000", "000852.XSHG"),
    ("star50", "科创50", "588000.XSHG"),
)
FIELDS = {"oi": "open_interest", "amount": "total_turnover", "volume": "volume"}
METRIC_NAMES = {"oi": "持仓量认沽认购比率", "amount": "成交额认沽认购比率", "volume": "成交量认沽认购比率"}


def calculate_ratios(raw, contracts):
    """Sum put/call quantities separately; incomplete sides never become zero."""
    if raw is None or raw.empty:
        return {}
    data = raw.reset_index().merge(contracts[["order_book_id", "option_type"]],
                                  on="order_book_id", how="inner", validate="many_to_one")
    data["date"] = pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d")
    result = {key: [] for key in FIELDS}
    for dt, rows in data.groupby("date", sort=True):
        for metric, field in FIELDS.items():
            sides = {}
            for side in ("P", "C"):
                values = pd.to_numeric(rows.loc[rows.option_type == side, field], errors="coerce")
                if values.empty or values.isna().any() or (values < 0).any():
                    break
                sides[side] = float(values.sum())
            if len(sides) == 2 and sides["C"] > 0:
                result[metric].append({"date": dt, "value": round(sides["P"] / sides["C"], 6)})
    return result


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(BASE_DIR / "rqdata-options-pcr.json"))
    args = parser.parse_args()
    initialize_rqdata()
    end = completed_trading_date(rq)
    output = Path(args.output)
    previous = read_json(output)
    stored = {item["id"]: item for item in previous.get("series", [])}
    # The first refresh needs only the missing tail, not a full historical rebuild.
    seed = previous or read_json(BASE_DIR / "broad-sentiment-page-cache.json").get("payload", {})
    old = {item["id"]: item for item in seed.get("series", []) if item.get("id", "").startswith("pcr-")}
    instruments = rq.all_instruments(type="Option")
    instruments["listed_date"] = pd.to_datetime(instruments["listed_date"], errors="coerce")
    instruments["de_listed_date"] = pd.to_datetime(instruments["de_listed_date"], errors="coerce")
    series = []
    for key, name, underlying in DEFINITIONS:
        dates = [old.get(f"pcr-{metric}-{key}", {}).get("points", []) for metric in FIELDS]
        tails = [points[-1]["date"] for points in dates if points]
        start = end - timedelta(days=90)
        if len(tails) == len(FIELDS):
            start = max(start, datetime.fromisoformat(min(tails)).date() - timedelta(days=7))
        contracts = instruments[
            (instruments.underlying_order_book_id == underlying)
            & (instruments.listed_date <= pd.Timestamp(end))
            & (instruments.de_listed_date >= pd.Timestamp(start))
        ].drop_duplicates("order_book_id")
        if contracts.empty:
            raise ValueError(f"No matching contracts: {underlying}")
        parts = []
        ids = contracts.order_book_id.tolist()
        for offset in range(0, len(ids), 250):
            raw = rq.get_price(ids[offset:offset + 250], start_date=start, end_date=end,
                               fields=list(FIELDS.values()), adjust_type="none", skip_suspended=False)
            if raw is not None and not raw.empty:
                parts.append(raw)
        ratios = calculate_ratios(pd.concat(parts) if parts else None, contracts)
        for metric in FIELDS:
            incoming = ratios.get(metric, [])
            if not incoming or incoming[-1]["date"] != end.isoformat():
                raise ValueError(f"{key}/{metric} has no complete data for {end}; prior snapshot retained")
            points = {p["date"]: p for p in stored.get(f"pcr-{metric}-{key}", {}).get("points", [])}
            points.update({p["date"]: p for p in incoming})
            series.append({"id": f"pcr-{metric}-{key}", "name": f"{name}{METRIC_NAMES[metric]}",
                           "source": "RQData期权日线（历史部分保留Wind）", "unit": "倍",
                           "points": [points[dt] for dt in sorted(points)][-1900:]})
        print(f"PCR refreshed: {key} through {end}", flush=True)
    payload = {"asOf": end.isoformat(), "generatedAt": datetime.now(CHINA_TIME).isoformat(timespec="seconds"),
               "source": "RQData期权日线", "series": series,
               "methodology": "同原Wind品种：50ETF、华泰柏瑞300ETF、中证1000股指、科创50ETF；全部存续到期月份的认沽总量/认购总量"}
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    temporary.replace(output)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(safe_error(exc))
        raise SystemExit(1)
