"""Retry late financing, ETF and connect observations without recomputing industry history."""
from __future__ import annotations

import argparse
import json
import math
from datetime import timedelta
from pathlib import Path

from retired_provider import client as rq
from market_data_sync import merge_points
from rqdata_connection import initialize_rqdata, safe_error
from rqdata_trading_day import completed_trading_date
from rqdata_refresh import (fetch_financing, fetch_index_ma_history, fetch_land_connect_flow, fetch_etf_flows,
                            build_index_financing_activity_series, build_index_turnover_series, recent_trading_dates,
                            INDEX_FINANCING_ACTIVITY_DEFINITIONS, FIVE_YEAR_TRADING_DAYS, FOCUS_ETFS)


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
    detail_dates = {str(item.get('code')): latest_point_date(item.get('points', []))
                    for item in old_details}
    details_current = all(
        detail_dates.get(item['code']) == target_date for item in FOCUS_ETFS.values())
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


SSE_AKSHARE_ETFS = {
    '510050': ('上证50ETF华夏', '上证50', '大盘压舱石'),
    '510300': ('沪深300ETF华泰柏瑞', '沪深300', '大盘压舱石'),
    '588000': ('科创50ETF华夏', '科创50', '科技成长主线'),
    '510500': ('中证500ETF南方', '中证500', '中小市值流动性托底'),
    '512100': ('中证1000ETF南方', '中证1000', '中小市值流动性托底'),
}


def refresh_sse_etf(payload, target, code, metadata, share_cache):
    """Collect one Shanghai ETF using dated share counts and unadjusted closes."""
    name, index, group = metadata
    target_date = target.isoformat()
    details = payload.get('etfDetails', [])
    prior = next((item for item in details if str(item.get('code')) == code), {})
    existing = valid_points(prior.get('points', []), target_date) if prior.get('source') == 'AkShare' else []
    last_date = latest_point_date(existing)
    if last_date == target_date:
        return False
    try:
        import akshare as ak

        prices = ak.fund_etf_hist_em(
            symbol=code, period='daily',
            start_date=(target - timedelta(days=100)).strftime('%Y%m%d'),
            end_date=target.strftime('%Y%m%d'), adjust='')
        closes = {}
        for _, row in prices.iterrows():
            day, close = str(row['日期'])[:10], float(row['收盘'])
            if day <= target_date and math.isfinite(close) and close > 0:
                closes[day] = close
        dates = sorted(closes)[-41:]
        if last_date in dates and len(existing) >= 20:
            dates = dates[dates.index(last_date):]

        shares = {}
        for day in dates:
            if day not in share_cache:
                share_cache[day] = ak.fund_etf_scale_sse(date=day.replace('-', ''))
            frame = share_cache[day]
            match = frame.loc[(frame['基金代码'].astype(str) == code)
                              & (frame['统计日期'].astype(str) == day), '基金份额']
            if len(match) == 1:
                units = float(match.iloc[0])
                if math.isfinite(units) and units > 0:
                    shares[day] = units  # AkShare returns shares, already converted from 万份.

        incoming = [{'date': day, 'value': round((shares[day] - shares[prev]) * closes[day] / 1e8, 3)}
                    for prev, day in zip(dates, dates[1:]) if prev in shares and day in shares]
        if not incoming or (last_date and incoming[-1]['date'] <= last_date):
            print(f'AkShare {code}: no new consecutive share observations', flush=True)
            return False

        history = merge_points(existing, incoming)[-FIVE_YEAR_TRADING_DAYS:]
        as_of = history[-1]['date']
        totals = flow_totals(history)
        # An incomplete window must remain blank rather than look like a full-period total.
        trading_days = [day for day in sorted(closes) if day <= as_of]
        flow_days = {point['date'] for point in history}
        for key, count in [('flow5D', 5), ('flow20D', 20)]:
            if len(trading_days) < count or not flow_days.issuperset(trading_days[-count:]):
                totals[key] = None
        detail = dict(code=code, orderBookId=f'{code}.XSHG', name=name,
                      index=index, group=group, source='AkShare',
                      asOf=as_of, close=closes[as_of], points=history, **totals)
        payload['etfDetails'] = [item for item in details if str(item.get('code')) != code] + [detail]
        print(f'AkShare {code}: {as_of}, {len(history)} flow observations', flush=True)
        return True
    except Exception as exc:
        print(f'AkShare {code} retained prior data: {safe_error(exc)}', flush=True)
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
    share_cache = {}
    for code, metadata in SSE_AKSHARE_ETFS.items():
        etf_changed = refresh_sse_etf(payload, target, code, metadata, share_cache) or etf_changed
    series = {item["id"]: item for item in payload.get("series", [])}
    def current(sid):
        points = series.get(sid, {}).get("points", [])
        return latest_point_date(points) == target.isoformat()
    updates = []
    try:
        updates.extend(build_index_turnover_series(payload, recent_trading_dates(target, 260)))
    except Exception as exc:
        print(f'Index turnover retry retained prior data: {safe_error(exc)}', flush=True)
    if not current('star50-close'):
        try:
            _,_,index_series=fetch_index_ma_history(target)
            updates.extend(item for item in index_series if item['id']=='star50-close')
        except Exception as exc:
            print(f'Index retry retained prior data: {safe_error(exc)}', flush=True)
    # Recheck recently cached financing values for incomplete publication.
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
            if sid.endswith(('-financing-activity', '-financing-buy', '-turnover-amount')) or sid in {'financing-activity', 'financing-net', 'financing-balance'}:
                series[sid] = item
            else:
                series[sid] = {**item, "points": merge_points(series.get(sid, {}).get("points", []), item.get("points", []))}
        payload["series"] = list(series.values())
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    print(f"Late market data checked for {target}", flush=True)


if __name__ == "__main__":
    main()
