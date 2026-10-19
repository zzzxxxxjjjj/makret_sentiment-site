"""Retry late financing, ETF and connect observations without recomputing industry history."""
from __future__ import annotations

import argparse
import json
import math
from datetime import timedelta
from pathlib import Path

import rqdatac as rq
from market_data_sync import merge_points
from rqdata_connection import initialize_rqdata, safe_error
from rqdata_trading_day import completed_trading_date
from rqdata_refresh import (fetch_financing, fetch_index_ma_history, fetch_land_connect_flow, fetch_etf_flows,
                            build_index_financing_activity_series, recent_trading_dates,
                            INDEX_FINANCING_ACTIVITY_DEFINITIONS, FIVE_YEAR_TRADING_DAYS)


def valid_points(points, limit=None):
    result = []
    for point in points:
        value = point.get('value')
        if (point.get('date') and isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and (limit is None or point['date'] <= limit)):
            result.append(point)
    return result


def latest_point_date(points):
    return max((point['date'] for point in valid_points(points)), default=None)


def flow_totals(points):
    values = [point['value'] for point in points]
    return {key: round(float(sum(values[-count:])), 3)
            for key, count in [('flow1D', 1), ('flow5D', 5), ('flow20D', 20)]}


def retry_etf(payload, target):
    """Check the ETF series itself; the overall cache date does not prove it is current."""
    target_date = target.isoformat()
    series = {item['id']: item for item in payload.get('series', [])}
    previous = series.get('broad-etf-flow', {})
    old_details = payload.get('etfDetails', [])
    details_current = bool(old_details) and all(
        latest_point_date(item.get('points', [])) == target_date for item in old_details)
    if latest_point_date(previous.get('points', [])) == target_date and details_current:
        return False
    try:
        # A short overlap provides the prior share observation and >20 sessions
        # for rolling totals; merge it into the saved five-year history.
        metrics, incoming, details = fetch_etf_flows(target, start_date=target-timedelta(days=120))
        incoming = valid_points(incoming, target_date)
        if not incoming:
            raise ValueError('provider returned no valid ETF flow observations')
        existing = valid_points(previous.get('points', []), target_date)
        incoming_date = latest_point_date(incoming)
        if existing and incoming_date < latest_point_date(existing):
            raise ValueError('provider ETF observations are older than the saved history')
        merged = merge_points(existing, incoming)[-FIVE_YEAR_TRADING_DAYS:]
        merged_details = {str(item.get('code') or item.get('orderBookId')): item for item in old_details}
        for item in details:
            key = str(item.get('code') or item.get('orderBookId'))
            old = merged_details.get(key, {})
            new_points = valid_points(item.get('points', []), target_date)
            if not new_points:
                continue
            old_points = valid_points(old.get('points', []), target_date)
            if old_points and latest_point_date(new_points) < latest_point_date(old_points):
                continue
            history = merge_points(old_points, new_points)[-FIVE_YEAR_TRADING_DAYS:]
            merged_details[key] = {**old, **item, 'points': history,
                                   'asOf': latest_point_date(history), **flow_totals(history)}
        totals = flow_totals(merged)
        series['broad-etf-flow'] = {**previous, 'id': 'broad-etf-flow',
            'name': previous.get('name', '宽基ETF日净流量'), 'unit': '亿元', 'points': merged}
        payload.update({key: value for key, value in metrics.items() if key == 'broadEtfCount'})
        payload.update(broadEtfAsOf=latest_point_date(merged), broadEtfFlow1D=totals['flow1D'],
                       broadEtfFlow5D=totals['flow5D'], broadEtfFlow20D=totals['flow20D'])
        payload['series'] = list(series.values())
        payload['etfDetails'] = list(merged_details.values())
        print(f"ETF retry: actual date {payload['broadEtfAsOf']}; target {target_date}; "
              f"{len(merged_details)} ETF details", flush=True)
        return True
    except Exception as exc:
        print(f'ETF retry retained prior data: {safe_error(exc)}', flush=True)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="rqdata-broad-sentiment.json")
    args = parser.parse_args()
    path = Path(args.output)
    payload = json.loads(path.read_text(encoding="utf-8"))
    initialize_rqdata()
    target = completed_trading_date(rq)
    etf_changed = retry_etf(payload, target)
    series = {item["id"]: item for item in payload.get("series", [])}
    required = ["financing-activity", *[item[1] for item in INDEX_FINANCING_ACTIVITY_DEFINITIONS]]
    def current(sid):
        points = series.get(sid, {}).get("points", [])
        return latest_point_date(points) == target.isoformat()
    updates = []
    if not current('star50-close'):
        try:
            _,_,index_series=fetch_index_ma_history(target)
            updates.extend(item for item in index_series if item['id']=='star50-close')
        except Exception as exc:
            print(f'Index retry retained prior data: {safe_error(exc)}', flush=True)
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
    if updates or etf_changed:
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
