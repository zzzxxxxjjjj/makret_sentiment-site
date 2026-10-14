"""Retry late financing/connect observations without recomputing industry history."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import rqdatac as rq
from market_data_sync import merge_points
from rqdata_connection import initialize_rqdata, safe_error
from rqdata_trading_day import completed_trading_date
from rqdata_refresh import (fetch_financing, fetch_index_ma_history, fetch_land_connect_flow,
                            build_index_financing_activity_series, recent_trading_dates,
                            INDEX_FINANCING_ACTIVITY_DEFINITIONS, FIVE_YEAR_TRADING_DAYS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="rqdata-broad-sentiment.json")
    args = parser.parse_args()
    path = Path(args.output)
    payload = json.loads(path.read_text(encoding="utf-8"))
    initialize_rqdata()
    target = completed_trading_date(rq)
    series = {item["id"]: item for item in payload.get("series", [])}
    required = ["financing-activity", *[item[1] for item in INDEX_FINANCING_ACTIVITY_DEFINITIONS]]
    def current(sid):
        points = series.get(sid, {}).get("points", [])
        return bool(points) and max(p["date"] for p in points) == target.isoformat()
    updates = []
    if not all(current(sid) for sid in required):
        try:
            _, turnover, _ = fetch_index_ma_history(target)
            metrics, incoming = fetch_financing(target, turnover)
            payload.update(metrics)
            updates.extend(incoming)
            dates = recent_trading_dates(target, FIVE_YEAR_TRADING_DAYS)
            updates.extend(build_index_financing_activity_series(payload, dates))
        except Exception as exc:
            print(f"Financing retry retained prior data: {safe_error(exc)}", flush=True)
    if not current("land-connect-turnover-ma20"):
        try:
            metrics, incoming = fetch_land_connect_flow(target)
            if not incoming:
                raise ValueError("provider returned no valid turnover")
            payload.update(metrics)
            updates.extend(incoming)
        except Exception as exc:
            print(f"Connect retry retained prior data: {safe_error(exc)}", flush=True)
    if updates:
        for item in updates:
            sid = item["id"]
            series[sid] = {**item, "points": merge_points(series.get(sid, {}).get("points", []), item.get("points", []))}
        payload["series"] = list(series.values())
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    print(f"Late market data checked for {target}", flush=True)


if __name__ == "__main__":
    main()
