from __future__ import annotations

import argparse
import bisect
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import rqdatac as rq

from rqdata_connection import initialize_rqdata


BROAD_KEYWORDS = (
    "上证50", "上证180", "上证380", "沪深300", "中证500", "中证800", "中证1000", "中证2000",
    "中证A500", "中证A50", "深证100", "深证成指", "创业板", "科创50", "科创100", "科创200",
    "国证2000", "北证50", "全A", "MSCI中国A50", "富时中国A50",
)
EXCLUDE_KEYWORDS = (
    "行业", "主题", "红利", "价值", "成长", "低波", "质量", "增强", "联接", "海外", "港股", "恒生",
    "纳斯达克", "标普", "德国", "法国", "日本", "印度", "东南亚", "债", "黄金", "商品", "货币",
)
FOCUS_ETFS = {
    "510300.XSHG": {"code": "510300", "name": "沪深300ETF华泰柏瑞", "index": "沪深300", "group": "大盘压舱石"},
    "515390.XSHG": {"code": "515390", "name": "沪深300ETF华安", "index": "沪深300", "group": "大盘压舱石"},
    "510210.XSHG": {"code": "510210", "name": "上证指数ETF富国", "index": "上证指数", "group": "大盘压舱石"},
    "159949.XSHE": {"code": "159949", "name": "创业板50ETF华安", "index": "创业板50", "group": "科技成长主线"},
    "159915.XSHE": {"code": "159915", "name": "创业板ETF易方达", "index": "创业板指", "group": "科技成长主线"},
    "588000.XSHG": {"code": "588000", "name": "科创50ETF华夏", "index": "科创50", "group": "科技成长主线"},
    "588290.XSHG": {"code": "588290", "name": "科创芯片ETF华安", "index": "科创芯片", "group": "科技成长主线"},
    "510500.XSHG": {"code": "510500", "name": "中证500ETF南方", "index": "中证500", "group": "中小市值流动性托底"},
    "512100.XSHG": {"code": "512100", "name": "中证1000ETF南方", "index": "中证1000", "group": "中小市值流动性托底"},
}
FIVE_YEAR_TRADING_DAYS = 1260
FIVE_YEAR_CALENDAR_DAYS = 366 * 5
PERCENTILE_LOOKBACK_DAYS = 250
TOP5_LOOKBACK_DAYS = FIVE_YEAR_TRADING_DAYS
TOP5_MIN_VALID_STOCKS = 4000
TURNOVER_LOOKBACK_DAYS = FIVE_YEAR_TRADING_DAYS
INDEX_MA_LOOKBACK_DAYS = FIVE_YEAR_TRADING_DAYS
FINANCING_LOOKBACK_DAYS = FIVE_YEAR_TRADING_DAYS
LAND_CONNECT_LOOKBACK_DAYS = FIVE_YEAR_TRADING_DAYS
PRICE_HISTORY_DAYS = 2500
NEW_FUND_LOOKBACK_DAYS = FIVE_YEAR_TRADING_DAYS
INDEX_TURNOVER_DEFINITIONS = (
    ("000300.XSHG", "hs300-turnover", "沪深300换手率"),
    ("000852.XSHG", "csi1000-turnover", "中证1000换手率"),
    ("000688.XSHG", "star50-turnover", "科创50换手率"),
)
INDEX_FINANCING_ACTIVITY_DEFINITIONS = (
    ("000300.XSHG", "hs300-financing-activity", "沪深300融资买入额占比"),
    ("000852.XSHG", "csi1000-financing-activity", "中证1000融资买入额占比"),
    ("000688.XSHG", "star50-financing-activity", "科创50融资买入额占比"),
)


def index_financing_metric_ids():
    ids = set()
    for _, activity_id, _ in INDEX_FINANCING_ACTIVITY_DEFINITIONS:
        prefix = activity_id.removesuffix("-financing-activity")
        ids.update(
            {
                activity_id,
                f"{prefix}-financing-buy",
                f"{prefix}-turnover-amount",
            }
        )
    return ids


def frame(value):
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.Series):
        return value.rename(value.name or "value").reset_index()
    if isinstance(value, pd.DataFrame):
        return value.reset_index()
    return pd.DataFrame(value)


def code_column(df):
    for name in ("order_book_id", "order_book_ids", "code"):
        if name in df.columns:
            return name
    return None


def date_column(df):
    for name in ("date", "datetime", "trading_date", "tradedate"):
        if name in df.columns:
            return name
    return None


def batch(items, size=500):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def a_share_ids(as_of):
    # Without a date RQData also keeps recently delisted instruments, which
    # avoids survivorship bias when the initial five-year history is rebuilt.
    instruments = rq.all_instruments(type="CS")
    if instruments.empty:
        instruments = rq.all_instruments(type="CS", date=as_of)
    if "currency" in instruments.columns:
        instruments = instruments[instruments["currency"].astype(str).str.upper().isin(["CNY", "RMB"])]
    else:
        # B shares use the 200/900 prefixes; exclude them when currency is not returned.
        codes = instruments["order_book_id"].astype(str).str.split(".").str[0]
        instruments = instruments[~codes.str.startswith(("200", "900"))]
    return instruments["order_book_id"].dropna().astype(str).drop_duplicates().tolist()


def completed_trading_date():
    latest = rq.get_latest_trading_date()
    if hasattr(latest, "date"):
        latest = latest.date()
    # Never use today's daily bar: during trading hours it is incomplete and
    # immediately after the close it may not have finished loading.
    if latest >= date.today():
        recent = rq.get_trading_dates(date.today() - timedelta(days=14), latest)
        completed = [
            item.date() if hasattr(item, "date") else item
            for item in recent
            if (item.date() if hasattr(item, "date") else item) < date.today()
        ]
        if completed:
            return max(completed)
    return latest


def recent_trading_dates(as_of, count=TOP5_LOOKBACK_DAYS):
    calendar = rq.get_trading_dates(as_of - timedelta(days=count * 2 + 30), as_of)
    dates = [item.date() if hasattr(item, "date") else item for item in calendar]
    return dates[-count:]


def fetch_top5_history(target_dates, as_of):
    if not target_dates:
        return {}, {}
    ids = a_share_ids(as_of)
    daily_values = {trading_date: [] for trading_date in target_dates}
    for date_batch in batch(target_dates, 120):
        target_set = set(date_batch)
        for ids_batch in batch(ids, 800):
            raw = frame(
                rq.get_price(
                    ids_batch,
                    min(date_batch),
                    max(date_batch),
                    fields="total_turnover",
                    adjust_type="none",
                    skip_suspended=True,
                )
            )
            dt_col = date_column(raw)
            if raw.empty or not dt_col or "total_turnover" not in raw.columns:
                continue
            raw[dt_col] = pd.to_datetime(raw[dt_col]).dt.date
            raw["total_turnover"] = pd.to_numeric(raw["total_turnover"], errors="coerce")
            raw = raw[
                raw[dt_col].isin(target_set)
                & raw["total_turnover"].notna()
                & (raw["total_turnover"] > 0)
            ]
            for trading_date, values in raw.groupby(dt_col)["total_turnover"]:
                daily_values[trading_date].extend(values.astype(float).tolist())

    results = {}
    counts = {}
    for trading_date, values in daily_values.items():
        valid = [value for value in values if math.isfinite(value) and value > 0]
        counts[trading_date] = len(valid)
        # A completed recent A-share session should contain well above 4,000
        # traded stocks. Fewer rows usually means the daily bar is incomplete.
        if len(valid) < TOP5_MIN_VALID_STOCKS:
            continue
        valid.sort(reverse=True)
        top_count = max(1, math.ceil(len(valid) * 0.05))
        results[trading_date] = round(sum(valid[:top_count]) / sum(valid) * 100, 3)
    return results, counts


def fetch_market_turnover_history(target_dates, as_of):
    """Calculate the equal-weighted daily turnover of all tradable A shares."""
    if not target_dates:
        return {}, {}
    ids = a_share_ids(as_of)
    daily_values = {trading_date: [] for trading_date in target_dates}
    for date_batch in batch(target_dates, 120):
        target_set = set(date_batch)
        for ids_batch in batch(ids, 800):
            raw = frame(
                rq.get_turnover_rate(
                    ids_batch,
                    min(date_batch),
                    max(date_batch),
                    fields="today",
                )
            )
            dt_col = date_column(raw)
            if raw.empty or not dt_col or "today" not in raw.columns:
                continue
            raw[dt_col] = pd.to_datetime(raw[dt_col]).dt.date
            raw["today"] = pd.to_numeric(raw["today"], errors="coerce")
            raw = raw[
                raw[dt_col].isin(target_set)
                & raw["today"].notna()
                & (raw["today"] >= 0)
            ]
            for trading_date, values in raw.groupby(dt_col)["today"]:
                daily_values[trading_date].extend(values.astype(float).tolist())

    results = {}
    counts = {}
    for trading_date, values in daily_values.items():
        valid = [value for value in values if math.isfinite(value) and value >= 0]
        counts[trading_date] = len(valid)
        if len(valid) < TOP5_MIN_VALID_STOCKS:
            continue
        # RQData `today` is already expressed in percentage points.
        results[trading_date] = round(sum(valid) / len(valid), 4)
    return results, counts


def build_index_turnover_series(previous, window_dates):
    """Calculate daily constituent-weighted turnover for three broad indices."""
    series_ids = {definition[1] for definition in INDEX_TURNOVER_DEFINITIONS}
    previous_series = {
        item.get("id"): item
        for item in previous.get("series", [])
        if item.get("id") in series_ids
    }
    window_set = set(window_dates)
    history = {}
    missing_by_series = {}
    for _, series_id, _ in INDEX_TURNOVER_DEFINITIONS:
        old_values = {
            pd.to_datetime(item.get("date")).date(): float(item["value"])
            for item in previous_series.get(series_id, {}).get("points", [])
            if item.get("date")
            and item.get("value") is not None
            and pd.to_datetime(item.get("date")).date() in window_set
        }
        history[series_id] = old_values
        missing_by_series[series_id] = [
            trading_date
            for trading_date in window_dates
            if trading_date not in old_values
        ]

    active_dates = [
        trading_date
        for missing_dates in missing_by_series.values()
        for trading_date in missing_dates
    ]
    if active_dates:
        start_date, end_date = min(active_dates), max(active_dates)
        weight_parts = []
        for order_book_id, series_id, _ in INDEX_TURNOVER_DEFINITIONS:
            target_set = set(missing_by_series[series_id])
            if not target_set:
                continue
            weights = frame(
                rq.index_weights_ex(
                    order_book_id,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
            dt_col = date_column(weights)
            id_col = code_column(weights)
            if weights.empty or not dt_col or not id_col or "weight" not in weights.columns:
                continue
            weights[dt_col] = pd.to_datetime(weights[dt_col]).dt.date
            weights["weight"] = pd.to_numeric(weights["weight"], errors="coerce")
            weights = weights[
                weights[dt_col].isin(target_set)
                & weights["weight"].notna()
                & (weights["weight"] > 0)
            ][[dt_col, id_col, "weight"]]
            weights.columns = ["date", "order_book_id", "weight"]
            weights["series_id"] = series_id
            weight_parts.append(weights)

        if weight_parts:
            all_weights = pd.concat(weight_parts, ignore_index=True)
            ids = all_weights["order_book_id"].dropna().astype(str).drop_duplicates().tolist()
            turnover_parts = []
            for ids_batch in batch(ids, 800):
                turnover = frame(
                    rq.get_turnover_rate(
                        ids_batch,
                        start_date,
                        end_date,
                        fields="today",
                    )
                )
                dt_col = date_column(turnover)
                id_col = code_column(turnover)
                if turnover.empty or not dt_col or not id_col or "today" not in turnover.columns:
                    continue
                turnover[dt_col] = pd.to_datetime(turnover[dt_col]).dt.date
                turnover["today"] = pd.to_numeric(turnover["today"], errors="coerce")
                turnover = turnover[
                    turnover["today"].notna() & (turnover["today"] >= 0)
                ][[dt_col, id_col, "today"]]
                turnover.columns = ["date", "order_book_id", "turnover"]
                turnover_parts.append(turnover)

            if turnover_parts:
                all_turnover = pd.concat(turnover_parts, ignore_index=True)
                merged = all_weights.merge(
                    all_turnover,
                    on=["date", "order_book_id"],
                    how="left",
                )
                for (series_id, trading_date), values in merged.groupby(["series_id", "date"]):
                    total_weight = values["weight"].sum()
                    valid = values.dropna(subset=["turnover"])
                    valid_weight = valid["weight"].sum()
                    if total_weight <= 0 or valid_weight / total_weight < 0.9:
                        continue
                    weighted_turnover = (
                        valid["turnover"] * valid["weight"]
                    ).sum() / valid_weight
                    history[series_id][trading_date] = round(float(weighted_turnover), 4)

    result = []
    for _, series_id, name in INDEX_TURNOVER_DEFINITIONS:
        points = [
            {"date": trading_date.isoformat(), "value": history[series_id][trading_date]}
            for trading_date in window_dates
            if trading_date in history[series_id]
        ]
        if points:
            result.append({"id": series_id, "name": name, "unit": "%", "points": points})
    return result


def build_index_financing_activity_series(previous, window_dates):
    """Calculate margin-buy value / turnover using each index's historical constituents."""
    series_ids = index_financing_metric_ids()
    previous_series = {
        item.get("id"): item
        for item in previous.get("series", [])
        if item.get("id") in series_ids
    }
    window_set = set(window_dates)
    history = {}
    missing_by_series = {}
    for series_id in series_ids:
        old_values = {
            pd.to_datetime(item.get("date")).date(): float(item["value"])
            for item in previous_series.get(series_id, {}).get("points", [])
            if item.get("date")
            and item.get("value") is not None
            and pd.to_datetime(item.get("date")).date() in window_set
        }
        history[series_id] = old_values
    for _, activity_id, _ in INDEX_FINANCING_ACTIVITY_DEFINITIONS:
        prefix = activity_id.removesuffix("-financing-activity")
        required_ids = (
            activity_id,
            f"{prefix}-financing-buy",
            f"{prefix}-turnover-amount",
        )
        missing_by_series[activity_id] = [
            trading_date
            for trading_date in window_dates
            if any(trading_date not in history[metric_id] for metric_id in required_ids)
        ]

    active_dates = [
        trading_date
        for missing_dates in missing_by_series.values()
        for trading_date in missing_dates
    ]
    if active_dates:
        start_date, end_date = min(active_dates), max(active_dates)
        constituent_parts = []
        for order_book_id, series_id, _ in INDEX_FINANCING_ACTIVITY_DEFINITIONS:
            target_set = set(missing_by_series[series_id])
            if not target_set:
                continue
            weights = frame(
                rq.index_weights_ex(
                    order_book_id,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
            dt_col = date_column(weights)
            id_col = code_column(weights)
            if weights.empty or not dt_col or not id_col:
                continue
            weights[dt_col] = pd.to_datetime(weights[dt_col]).dt.date
            constituents = weights[weights[dt_col].isin(target_set)][
                [dt_col, id_col]
            ].copy()
            constituents.columns = ["date", "order_book_id"]
            constituents["series_id"] = series_id
            constituent_parts.append(constituents.drop_duplicates())

        if constituent_parts:
            constituents = pd.concat(constituent_parts, ignore_index=True)
            ids = (
                constituents["order_book_id"]
                .dropna()
                .astype(str)
                .drop_duplicates()
                .tolist()
            )
            margin_parts = []
            turnover_parts = []
            for ids_batch in batch(ids, 300):
                margin = frame(
                    rq.get_securities_margin(
                        ids_batch,
                        start_date,
                        end_date,
                        fields=["buy_on_margin_value"],
                    )
                )
                margin_date = date_column(margin)
                margin_id = code_column(margin)
                if (
                    not margin.empty
                    and margin_date
                    and margin_id
                    and "buy_on_margin_value" in margin.columns
                ):
                    margin[margin_date] = pd.to_datetime(margin[margin_date]).dt.date
                    margin["buy_on_margin_value"] = pd.to_numeric(
                        margin["buy_on_margin_value"], errors="coerce"
                    )
                    margin = margin[
                        [margin_date, margin_id, "buy_on_margin_value"]
                    ]
                    margin.columns = ["date", "order_book_id", "margin_buy"]
                    margin_parts.append(margin)

                turnover = frame(
                    rq.get_price(
                        ids_batch,
                        start_date,
                        end_date,
                        fields="total_turnover",
                        adjust_type="none",
                        skip_suspended=True,
                    )
                )
                turnover_date = date_column(turnover)
                turnover_id = code_column(turnover)
                if (
                    not turnover.empty
                    and turnover_date
                    and turnover_id
                    and "total_turnover" in turnover.columns
                ):
                    turnover[turnover_date] = pd.to_datetime(
                        turnover[turnover_date]
                    ).dt.date
                    turnover["total_turnover"] = pd.to_numeric(
                        turnover["total_turnover"], errors="coerce"
                    )
                    turnover = turnover[
                        [turnover_date, turnover_id, "total_turnover"]
                    ]
                    turnover.columns = ["date", "order_book_id", "turnover"]
                    turnover_parts.append(turnover)

            if turnover_parts:
                turnover = pd.concat(turnover_parts, ignore_index=True)
                margin = (
                    pd.concat(margin_parts, ignore_index=True)
                    if margin_parts
                    else pd.DataFrame(
                        columns=["date", "order_book_id", "margin_buy"]
                    )
                )
                merged = constituents.merge(
                    turnover,
                    on=["date", "order_book_id"],
                    how="left",
                ).merge(
                    margin,
                    on=["date", "order_book_id"],
                    how="left",
                )
                for (series_id, trading_date), values in merged.groupby(
                    ["series_id", "date"]
                ):
                    valid = values[
                        values["turnover"].notna() & (values["turnover"] > 0)
                    ].copy()
                    if len(values) == 0 or len(valid) / len(values) < 0.8:
                        continue
                    turnover_sum = valid["turnover"].sum()
                    if turnover_sum <= 0:
                        continue
                    margin_sum = valid["margin_buy"].fillna(0).sum()
                    prefix = series_id.removesuffix("-financing-activity")
                    history[series_id][trading_date] = round(
                        float(margin_sum / turnover_sum * 100), 4
                    )
                    history[f"{prefix}-financing-buy"][trading_date] = round(
                        float(margin_sum / 1e8), 4
                    )
                    history[f"{prefix}-turnover-amount"][trading_date] = round(
                        float(turnover_sum / 1e8), 4
                    )

    result = []
    for _, activity_id, name in INDEX_FINANCING_ACTIVITY_DEFINITIONS:
        prefix = activity_id.removesuffix("-financing-activity")
        metric_definitions = (
            (activity_id, name, "%"),
            (f"{prefix}-financing-buy", name.replace("占比", ""), "亿元"),
            (f"{prefix}-turnover-amount", name.replace("融资买入额占比", "成交额"), "亿元"),
        )
        for series_id, series_name, unit in metric_definitions:
            points = [
                {
                    "date": trading_date.isoformat(),
                    "value": history[series_id][trading_date],
                }
                for trading_date in window_dates
                if trading_date in history[series_id]
            ]
            if points:
                result.append(
                    {"id": series_id, "name": series_name, "unit": unit, "points": points}
                )
    return result


def fetch_index_ma_history(as_of):
    """Build 100-day MA distance series for major broad-market indices."""
    calendar = recent_trading_dates(as_of, PRICE_HISTORY_DAYS + 110)
    if not calendar:
        return {}, {}, []
    definitions = (
        ("000001.XSHG", "sh-ma100", "上证综指距100日均线", "shCompositeDistance100d", None, None),
        ("000300.XSHG", "hs300-ma100", "沪深300距100日均线", "hs300Distance100d", "hs300-close", "沪深300"),
        ("000852.XSHG", None, None, None, "csi1000-close", "中证1000"),
        ("000985.XSHG", "windall-ma100", "中证全指距100日均线", "allShareDistance100d", "allshare-close", "中证全指"),
    )
    latest = {}
    all_share_turnover = {}
    series = []
    for order_book_id, series_id, name, payload_key, close_series_id, close_name in definitions:
        fields = ["close", "total_turnover"] if order_book_id == "000985.XSHG" else ["close"]
        try:
            raw = frame(
                rq.get_price(
                    order_book_id,
                    calendar[0],
                    calendar[-1],
                    fields=fields,
                    adjust_type="none",
                    skip_suspended=False,
                )
            )
        except Exception as exc:
            try:
                raw = frame(
                    rq.get_price(
                        order_book_id,
                        calendar[0],
                        calendar[-1],
                        fields=fields,
                    )
                )
            except Exception as retry_exc:
                print(f"{order_book_id} 指数更新失败，跳过该指数：{exc}；简化参数重试：{retry_exc}")
                continue
        dt_col = date_column(raw)
        if raw.empty or not dt_col or "close" not in raw.columns:
            continue
        raw[dt_col] = pd.to_datetime(raw[dt_col]).dt.date
        raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
        raw = raw.dropna(subset=["close"]).sort_values(dt_col)
        raw["_ma100"] = raw["close"].rolling(100, min_periods=100).mean()
        raw["_distance"] = (raw["close"] / raw["_ma100"] - 1) * 100
        valid = raw.dropna(subset=["_distance"]).tail(INDEX_MA_LOOKBACK_DAYS)
        points = [
            {"date": row[dt_col].isoformat(), "value": round(float(row["_distance"]), 3)}
            for _, row in valid.iterrows()
        ]
        if points and payload_key:
            latest[payload_key] = points[-1]["value"]
            latest[f"{payload_key}AsOf"] = points[-1]["date"]
        if points and series_id:
            series.append({"id": series_id, "name": name, "unit": "%", "points": points})
        if close_series_id:
            close_points = [
                {"date": row[dt_col].isoformat(), "value": round(float(row["close"]), 3)}
                for _, row in raw.tail(PRICE_HISTORY_DAYS).iterrows()
            ]
            if close_points:
                series.append({
                    "id": close_series_id,
                    "name": close_name,
                    "unit": "点",
                    "points": close_points,
                })
        if order_book_id == "000985.XSHG":
            if "total_turnover" in raw.columns:
                raw["total_turnover"] = pd.to_numeric(raw["total_turnover"], errors="coerce")
                all_share_turnover = {
                    row[dt_col]: float(row["total_turnover"])
                    for _, row in raw.dropna(subset=["total_turnover"]).iterrows()
                    if float(row["total_turnover"]) > 0
                }
    return latest, all_share_turnover, series


def fetch_financing(as_of, all_share_turnover):
    start = as_of - timedelta(days=FINANCING_LOOKBACK_DAYS * 2 + 30)
    raw = frame(rq.get_securities_margin(["XSHG", "XSHE"], start, as_of))
    dt_col = date_column(raw)
    if raw.empty or not dt_col:
        return {}, []
    raw[dt_col] = pd.to_datetime(raw[dt_col]).dt.date
    numeric_cols = [name for name in ("margin_balance", "buy_on_margin_value", "margin_repayment", "total_balance") if name in raw.columns]
    for name in numeric_cols:
        raw[name] = pd.to_numeric(raw[name], errors="coerce")
    daily = raw.groupby(dt_col, as_index=False)[numeric_cols].sum().sort_values(dt_col)
    if daily.empty:
        return {}, []
    daily["_balance_change"] = daily["margin_balance"].diff() if "margin_balance" in daily else None
    if "buy_on_margin_value" in daily and "margin_repayment" in daily:
        daily["_net"] = daily["buy_on_margin_value"] - daily["margin_repayment"]
        daily["_net"] = daily["_net"].where(daily["_net"].notna(), daily["_balance_change"])
    else:
        daily["_net"] = daily["_balance_change"]
    if "buy_on_margin_value" in daily:
        daily["_activity"] = [
            (
                float(row["buy_on_margin_value"]) / all_share_turnover.get(row[dt_col]) * 100
                if all_share_turnover.get(row[dt_col])
                else None
            )
            for _, row in daily.iterrows()
        ]
    else:
        daily["_activity"] = None
    daily = daily.tail(FINANCING_LOOKBACK_DAYS)
    latest = daily.iloc[-1]
    series = []
    net_points = [
        {"date": row[dt_col].isoformat(), "value": round(float(row["_net"]) / 1e8, 3)}
        for _, row in daily.dropna(subset=["_net"]).iterrows()
    ]
    activity_points = [
        {"date": row[dt_col].isoformat(), "value": round(float(row["_activity"]), 3)}
        for _, row in daily.dropna(subset=["_activity"]).iterrows()
    ]
    buy_points = [
        {"date": row[dt_col].isoformat(), "value": round(float(row["buy_on_margin_value"]) / 1e8, 3)}
        for _, row in daily.dropna(subset=["buy_on_margin_value"]).iterrows()
    ] if "buy_on_margin_value" in daily else []
    turnover_points = [
        {"date": row[dt_col].isoformat(), "value": round(float(all_share_turnover[row[dt_col]]) / 1e8, 3)}
        for _, row in daily.iterrows()
        if row[dt_col] in all_share_turnover
    ]
    balance_points = [
        {"date": row[dt_col].isoformat(), "value": round(float(row["margin_balance"]) / 1e8, 3)}
        for _, row in daily.dropna(subset=["margin_balance"]).iterrows()
    ] if "margin_balance" in daily else []
    if net_points:
        series.append({"id": "financing-net", "name": "融资净流入", "unit": "亿元", "points": net_points})
    if activity_points:
        series.append({"id": "financing-activity", "name": "全A融资买入额占比", "unit": "%", "points": activity_points})
    if buy_points:
        series.append({"id": "alla-financing-buy", "name": "全A融资买入额", "unit": "亿元", "points": buy_points})
    if turnover_points:
        series.append({"id": "alla-turnover-amount", "name": "全A成交额", "unit": "亿元", "points": turnover_points})
    if balance_points:
        series.append({"id": "financing-balance", "name": "融资余额", "unit": "亿元", "points": balance_points})
    result = {
        "financingAsOf": latest[dt_col].isoformat(),
        "financingNet": round(float(latest["_net"]) / 1e8, 3) if pd.notna(latest["_net"]) else None,
        "financingBalance": round(float(latest["margin_balance"]) / 1e8, 3) if "margin_balance" in daily and pd.notna(latest["margin_balance"]) else None,
        "financingActivity": round(float(latest["_activity"]), 3) if pd.notna(latest["_activity"]) else None,
    }
    return result, series


def fetch_land_connect_flow(as_of):
    start = as_of - timedelta(days=LAND_CONNECT_LOOKBACK_DAYS * 2 + 30)
    raw = rq.get_stock_connect_quota(
        connect=["hk_to_sh", "hk_to_sz"],
        start_date=start,
        end_date=as_of,
        fields=["buy_turnover", "sell_turnover"],
    )
    raw = frame(raw)
    dt_col = date_column(raw)
    if raw.empty or not dt_col:
        return {}, []
    raw[dt_col] = pd.to_datetime(raw[dt_col]).dt.date
    for name in ("buy_turnover", "sell_turnover"):
        if name not in raw.columns:
            return {}, []
        raw[name] = pd.to_numeric(raw[name], errors="coerce")
    daily = (
        raw.groupby(dt_col, as_index=False)[["buy_turnover", "sell_turnover"]]
        .sum(min_count=1)
        .sort_values(dt_col)
    )
    daily["_turnover"] = (daily["buy_turnover"] + daily["sell_turnover"]) / 1e8
    # After the disclosure-rule change, unavailable northbound values may be
    # represented as zero. Do not let those placeholders enter the MA5.
    daily = daily[daily["_turnover"] > 0].copy()
    daily["_ma5"] = daily["_turnover"].rolling(5, min_periods=5).mean()
    daily = daily.tail(LAND_CONNECT_LOOKBACK_DAYS)
    valid = daily.dropna(subset=["_ma5"])
    if valid.empty:
        return {}, []
    latest = valid.iloc[-1]
    points = [
        {
            "date": row[dt_col].isoformat(),
            "value": round(float(row["_ma5"]), 3),
        }
        for _, row in valid.iterrows()
    ]
    return (
        {
            "landConnectTurnoverAsOf": latest[dt_col].isoformat(),
            "landConnectTurnover": round(float(latest["_turnover"]), 3),
            "landConnectTurnoverMA5": round(float(latest["_ma5"]), 3),
        },
        [
            {
                "id": "land-connect-turnover-ma20",
                "name": "陆股通成交总额MA5",
                "unit": "亿元",
                "points": points,
            }
        ],
    )


def fetch_dragon_tiger(as_of):
    # Pull enough calendar history to build a stable rolling 20-trading-day series.
    start = as_of - timedelta(days=120)
    abnormal = frame(rq.get_abnormal_stocks(start, as_of))
    code_col = code_column(abnormal)
    if abnormal.empty or not code_col:
        return None, 0, []
    ids = abnormal[code_col].dropna().astype(str).unique().tolist()
    details = []
    for ids_batch in batch(ids, 200):
        current = frame(rq.get_abnormal_stocks_detail(ids_batch, start, as_of))
        if not current.empty:
            details.append(current)
    if not details:
        return None, len(ids), []
    detail = pd.concat(details, ignore_index=True)
    dt_col = date_column(detail)
    if not dt_col:
        return None, len(ids), []
    detail[dt_col] = pd.to_datetime(detail[dt_col]).dt.date
    buy = pd.to_numeric(detail.get("buy_value"), errors="coerce")
    sell = pd.to_numeric(detail.get("sell_value"), errors="coerce")
    detail = detail.assign(_buy=buy, _sell=sell)
    dedupe = [name for name in (code_column(detail), date_column(detail), "agency", "side", "_buy", "_sell") if name]
    detail = detail.drop_duplicates(subset=dedupe)
    if "side" in detail.columns:
        side = detail["side"].astype(str).str.upper()
        buy_rows = side.str.contains("BUY|买", regex=True)
        sell_rows = side.str.contains("SELL|卖", regex=True)
        if buy_rows.any() or sell_rows.any():
            detail["_net"] = detail["_buy"].fillna(0) - detail["_sell"].fillna(0)
            detail.loc[buy_rows, "_net"] = detail.loc[buy_rows, "_buy"].fillna(0)
            detail.loc[sell_rows, "_net"] = -detail.loc[sell_rows, "_sell"].fillna(0)
        else:
            detail["_net"] = detail["_buy"].fillna(0) - detail["_sell"].fillna(0)
    else:
        detail["_net"] = detail["_buy"].fillna(0) - detail["_sell"].fillna(0)
    daily = detail.groupby(dt_col, as_index=False)["_net"].sum().sort_values(dt_col)
    if daily.empty:
        return None, len(ids), []
    daily["rolling_20"] = daily["_net"].rolling(20, min_periods=5).sum() / 1e8
    valid = daily.dropna(subset=["rolling_20"])
    series = [
        {"date": item[dt_col].isoformat(), "value": round(float(item["rolling_20"]), 3)}
        for _, item in valid.tail(500).iterrows()
    ]
    latest_row = valid.iloc[-1] if not valid.empty else daily.iloc[-1]
    latest = latest_row["rolling_20"] if "rolling_20" in latest_row else daily["_net"].sum() / 1e8
    return round(float(latest), 3), len(ids), series


def fetch_new_a_share_accounts(as_of):
    # RQData 3.5.5 does not expose a clearly named investor account statistics
    # endpoint. Keep a stable payload slot so the page can light up once the
    # account-opening data source is added.
    return {}, []


def fetch_partial_equity_fund_index_returns(as_of):
    candidates = (
        ("885001.WI", "偏股型基金指数"),
        ("885000.WI", "偏股型基金指数"),
    )
    start = as_of - timedelta(days=NEW_FUND_LOOKBACK_DAYS * 2 + 400)
    for order_book_id, name in candidates:
        try:
            raw = frame(
                rq.get_price(
                    order_book_id,
                    start,
                    as_of,
                    fields=["close"],
                    adjust_type="none",
                    skip_suspended=False,
                )
            )
        except Exception:
            continue
        dt_col = date_column(raw)
        if raw.empty or not dt_col or "close" not in raw.columns:
            continue
        raw[dt_col] = pd.to_datetime(raw[dt_col])
        raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
        raw = raw.dropna(subset=["close"]).sort_values(dt_col)
        if raw.empty:
            continue
        raw["month"] = raw[dt_col].dt.to_period("M")
        monthly = raw.groupby("month", as_index=False).tail(1).copy()
        monthly["monthly_return"] = monthly["close"].pct_change() * 100
        points = [
            {
                "date": row[dt_col].date().isoformat(),
                "value": round(float(row["monthly_return"]), 3),
            }
            for _, row in monthly.tail(72).iterrows()
            if pd.notna(row["monthly_return"])
        ]
        if points:
            return (
                {
                    "partialEquityFundIndexAsOf": points[-1]["date"],
                    "partialEquityFundIndexMonthlyReturn": points[-1]["value"],
                    "partialEquityFundIndexCode": order_book_id,
                },
                [
                    {
                        "id": "partial-equity-fund-index-monthly-return",
                        "name": f"{name}月涨跌幅",
                        "unit": "%",
                        "points": points,
                    }
                ],
            )
    return {}, []


def fetch_new_equity_fund_issuance(as_of):
    """Use new equity-fund establishment/listing dates as an institutional-flow proxy."""
    instruments = rq.all_instruments(type="FUND")
    if instruments is None or instruments.empty or "listed_date" not in instruments.columns:
        return {}, []
    current = instruments.copy()
    descriptor_columns = [
        name
        for name in (
            "fund_type",
            "fund_category",
            "product",
            "symbol",
            "display_name",
            "abbrev_symbol",
            "sector_code_name",
        )
        if name in current.columns
    ]
    if not descriptor_columns:
        return {}, []
    descriptors = current[descriptor_columns].fillna("").astype(str).agg(" ".join, axis=1)
    equity_mask = descriptors.str.contains("股票|EQUITY", case=False, regex=True)
    exclusion_mask = descriptors.str.contains(
        "债券|货币|混合|FOF|QDII|REIT|商品|黄金|联接|ETF",
        case=False,
        regex=True,
    )
    current = current[equity_mask & ~exclusion_mask].copy()
    current["listed_date"] = pd.to_datetime(
        current["listed_date"],
        format="%Y-%m-%d",
        errors="coerce",
    ).dt.date
    current = current.dropna(subset=["listed_date"])
    if current.empty:
        return {}, []

    calendar = recent_trading_dates(as_of, NEW_FUND_LOOKBACK_DAYS + 70)
    if not calendar:
        return {}, []
    daily_counts = {trading_date: 0 for trading_date in calendar}
    for listed_date in current["listed_date"]:
        position = bisect.bisect_left(calendar, listed_date)
        if position < len(calendar):
            daily_counts[calendar[position]] += 1
    count_frame = pd.DataFrame(
        [{"date": trading_date, "count": daily_counts[trading_date]} for trading_date in calendar]
    )
    count_frame["count20D"] = count_frame["count"].rolling(20, min_periods=1).sum()
    count_frame["count60D"] = count_frame["count"].rolling(60, min_periods=1).sum()
    history = count_frame.tail(NEW_FUND_LOOKBACK_DAYS)
    latest = history.iloc[-1]
    count20 = float(latest["count20D"])
    percentile_window = history.tail(PERCENTILE_LOOKBACK_DAYS)
    percentile250 = float((percentile_window["count20D"] <= count20).mean() * 100)
    series = [
        {"date": row["date"].isoformat(), "value": int(row["count20D"])}
        for _, row in history.iterrows()
    ]
    return {
        "newEquityFundAsOf": as_of.isoformat(),
        "newEquityFundCount20D": int(latest["count20D"]),
        "newEquityFundCount60D": int(latest["count60D"]),
        "newEquityFundPercentile250D": round(percentile250, 1),
        "newEquityFundMatchedCount": int(len(current)),
    }, series


def select_broad_etfs(as_of):
    instruments = rq.all_instruments(type="ETF", date=as_of)
    code_col = "order_book_id"
    label_cols = [name for name in ("symbol", "display_name", "abbrev_symbol") if name in instruments.columns]
    selected = []
    for _, row in instruments.iterrows():
        label = " ".join(str(row.get(name, "")) for name in label_cols)
        if any(keyword in label for keyword in BROAD_KEYWORDS) and not any(keyword in label for keyword in EXCLUDE_KEYWORDS):
            selected.append(str(row[code_col]))
    return sorted(set(selected))


def long_value(raw, value_name):
    df = frame(raw)
    code_col = code_column(df)
    dt_col = date_column(df)
    if df.empty or not code_col or not dt_col or value_name not in df.columns:
        return pd.DataFrame(columns=["order_book_id", "date", value_name])
    result = df[[code_col, dt_col, value_name]].copy()
    result.columns = ["order_book_id", "date", value_name]
    result["date"] = pd.to_datetime(result["date"]).dt.date
    result[value_name] = pd.to_numeric(result[value_name], errors="coerce")
    return result.dropna(subset=[value_name])


def fetch_etf_flows(as_of):
    broad_ids = select_broad_etfs(as_of)
    ids = sorted(set(broad_ids) | set(FOCUS_ETFS))
    if not ids:
        return {}, [], []
    start = as_of - timedelta(days=FIVE_YEAR_CALENDAR_DAYS + 10)
    units_parts = []
    price_parts = []
    for ids_batch in batch(ids, 300):
        units_parts.append(long_value(rq.etf.get_daily_units(ids_batch, start, as_of), "units"))
        price_parts.append(long_value(rq.get_price(ids_batch, start, as_of, fields="close", adjust_type="none"), "close"))
    units = pd.concat(units_parts, ignore_index=True).drop_duplicates(["order_book_id", "date"], keep="last")
    prices = pd.concat(price_parts, ignore_index=True).drop_duplicates(["order_book_id", "date"], keep="last")
    merged = units.merge(prices, on=["order_book_id", "date"], how="inner").sort_values(["order_book_id", "date"])
    if merged.empty:
        return {}, [], []
    merged["unit_change"] = merged.groupby("order_book_id")["units"].diff()
    merged["flow"] = merged["unit_change"] * merged["close"] / 1e8
    broad = merged[merged["order_book_id"].isin(broad_ids)]
    daily = broad.groupby("date", as_index=False)["flow"].sum(min_count=1).dropna().sort_values("date")
    if daily.empty:
        result, series = {}, []
    else:
        values = daily["flow"].tolist()
        result = {
            "broadEtfFlow1D": round(float(values[-1]), 3),
            "broadEtfFlow5D": round(float(sum(values[-5:])), 3),
            "broadEtfFlow20D": round(float(sum(values[-20:])), 3),
            "broadEtfCount": len(broad_ids),
        }
        series = [
            {"date": item["date"].isoformat(), "value": round(float(item["flow"]), 3)}
            for _, item in daily.tail(FIVE_YEAR_TRADING_DAYS).iterrows()
        ]

    details = []
    for order_book_id, metadata in FOCUS_ETFS.items():
        current = merged[merged["order_book_id"] == order_book_id].dropna(subset=["flow"]).sort_values("date")
        flows = current["flow"].astype(float).tolist()
        points = [
            {"date": item["date"].isoformat(), "value": round(float(item["flow"]), 3)}
            for _, item in current.tail(FIVE_YEAR_TRADING_DAYS).iterrows()
        ]
        details.append({
            **metadata,
            "orderBookId": order_book_id,
            "asOf": current.iloc[-1]["date"].isoformat() if not current.empty else None,
            "flow1D": round(float(flows[-1]), 3) if flows else None,
            "flow5D": round(float(sum(flows[-5:])), 3) if flows else None,
            "flow20D": round(float(sum(flows[-20:])), 3) if flows else None,
            "close": round(float(current.iloc[-1]["close"]), 4) if not current.empty else None,
            "points": points,
        })
    return result, series, details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    initialize_rqdata()
    as_of = completed_trading_date()

    output = Path(args.output)
    previous = {}
    if output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}

    old_top5 = next(
        (item.get("points", []) for item in previous.get("series", []) if item.get("id") == "top5-concentration"),
        [],
    )
    old_turnover = next(
        (
            item.get("points", [])
            for item in previous.get("series", [])
            if item.get("id") == "market-turnover"
        ),
        [],
    )
    window_dates = recent_trading_dates(as_of)
    window_set = set(window_dates)
    try:
        index_turnover_series = build_index_turnover_series(previous, window_dates)
    except Exception as exc:
        print(f"宽基指数换手率更新失败，继续使用旧缓存：{exc}")
        index_turnover_series = [
            item
            for item in previous.get("series", [])
            if item.get("id") in {
                definition[1] for definition in INDEX_TURNOVER_DEFINITIONS
            }
        ]
    try:
        print("正在更新宽基指数融资活跃度（首次回算五年，之后为日度增量）...")
        index_financing_activity_series = build_index_financing_activity_series(
            previous, window_dates
        )
        print(
            f"宽基指数融资活跃度更新完成：{len(index_financing_activity_series)}条序列"
        )
    except Exception as exc:
        print(f"宽基指数融资活跃度更新失败，继续使用旧缓存：{exc}")
        index_financing_activity_series = [
            item
            for item in previous.get("series", [])
            if item.get("id") in index_financing_metric_ids()
        ]
    if index_turnover_series:
        index_turnover_ids = {
            definition[1] for definition in INDEX_TURNOVER_DEFINITIONS
        }
        previous["series"] = [
            item
            for item in previous.get("series", [])
            if item.get("id") not in index_turnover_ids
            and item.get("id") != "hs300-bias20"
        ] + index_turnover_series
        output.write_text(
            json.dumps(previous, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    existing_top5 = {
        pd.to_datetime(item.get("date")).date(): float(item["value"])
        for item in old_top5
        if item.get("date")
        and item.get("value") is not None
        and pd.to_datetime(item.get("date")).date() in window_set
    }
    missing_dates = [trading_date for trading_date in window_dates if trading_date not in existing_top5]
    new_top5, top5_counts = fetch_top5_history(missing_dates, as_of)
    top5_history = {**existing_top5, **new_top5}
    top5_series = [
        {"date": trading_date.isoformat(), "value": top5_history[trading_date]}
        for trading_date in window_dates
        if trading_date in top5_history
    ]
    latest_top5 = top5_series[-1] if top5_series else None
    top5 = latest_top5["value"] if latest_top5 else previous.get("top5Concentration")
    top5_percentile_window = top5_series[-PERCENTILE_LOOKBACK_DAYS:]
    top5_percentile = (
        sum(1 for item in top5_percentile_window if item["value"] <= top5)
        / len(top5_percentile_window)
        * 100
        if top5 is not None and top5_percentile_window
        else previous.get("top5ConcentrationPercentile250D")
    )
    latest_top5_date = pd.to_datetime(latest_top5["date"]).date() if latest_top5 else None
    stock_count = (
        top5_counts.get(latest_top5_date)
        if latest_top5_date in top5_counts
        else previous.get("stockCount", 0)
    )
    existing_turnover = {
        pd.to_datetime(item.get("date")).date(): float(item["value"])
        for item in old_turnover
        if item.get("date")
        and item.get("value") is not None
        and pd.to_datetime(item.get("date")).date() in window_set
    }
    missing_turnover_dates = [
        trading_date
        for trading_date in window_dates[-TURNOVER_LOOKBACK_DAYS:]
        if trading_date not in existing_turnover
    ]
    new_turnover, turnover_counts = fetch_market_turnover_history(
        missing_turnover_dates,
        as_of,
    )
    turnover_history = {**existing_turnover, **new_turnover}
    turnover_series = [
        {"date": trading_date.isoformat(), "value": turnover_history[trading_date]}
        for trading_date in window_dates[-TURNOVER_LOOKBACK_DAYS:]
        if trading_date in turnover_history
    ]
    latest_turnover = turnover_series[-1] if turnover_series else None
    market_turnover = (
        latest_turnover["value"]
        if latest_turnover
        else previous.get("marketTurnover")
    )
    turnover_percentile_window = turnover_series[-PERCENTILE_LOOKBACK_DAYS:]
    market_turnover_percentile = (
        sum(
            1
            for item in turnover_percentile_window
            if item["value"] <= market_turnover
        )
        / len(turnover_percentile_window)
        * 100
        if market_turnover is not None and turnover_percentile_window
        else previous.get("marketTurnoverPercentile250D")
    )
    index_ma, all_share_turnover, index_series = fetch_index_ma_history(as_of)
    financing, financing_series = fetch_financing(as_of, all_share_turnover)
    try:
        land_connect, land_connect_series = fetch_land_connect_flow(as_of)
    except Exception as exc:
        print(f"陆股通数据更新失败，继续使用旧缓存：{exc}")
        land_connect = {
            key: previous.get(key)
            for key in (
                "landConnectTurnoverAsOf",
                "landConnectTurnover",
                "landConnectTurnoverMA5",
            )
            if previous.get(key) is not None
        }
        land_connect_series = [
            item
            for item in previous.get("series", [])
            if item.get("id") == "land-connect-turnover-ma20"
        ]
    etf, etf_series, etf_details = fetch_etf_flows(as_of)
    try:
        dragon_tiger_net, dragon_tiger_count, dragon_tiger_points = fetch_dragon_tiger(as_of)
    except Exception as exc:
        print(f"龙虎榜资金更新失败，继续使用旧缓存：{exc}")
        dragon_tiger_net = previous.get("dragonTigerNetInflow20D")
        dragon_tiger_count = previous.get("dragonTigerStockCount", 0)
        dragon_tiger_points = next(
            (
                item.get("points", [])
                for item in previous.get("series", [])
                if item.get("id") == "dragon-tiger-net-inflow"
            ),
            [],
        )
    new_accounts, new_account_series = fetch_new_a_share_accounts(as_of)
    new_equity_funds, new_equity_fund_series = fetch_new_equity_fund_issuance(as_of)
    partial_fund_index, partial_fund_index_series = fetch_partial_equity_fund_index_returns(as_of)
    series = []
    if top5_series:
        series.append({"id": "top5-concentration", "name": "成交额前5%个股占比", "unit": "%", "points": top5_series})
    if turnover_series:
        series.append({"id": "market-turnover", "name": "全A等权日频换手率", "unit": "%", "points": turnover_series})
    series.extend(index_series)
    series.extend(index_turnover_series)
    series.extend(financing_series)
    series.extend(index_financing_activity_series)
    series.extend(land_connect_series)
    if etf_series:
        series.append({"id": "broad-etf-flow", "name": "宽基ETF日净流量", "unit": "亿元", "points": etf_series})
    if dragon_tiger_points:
        series.append({"id": "dragon-tiger-net-inflow", "name": "龙虎榜资金净流入（20日滚动）", "unit": "亿元", "points": dragon_tiger_points})
    series.extend(new_account_series)
    if new_equity_fund_series:
        series.append(
            {
                "id": "new-equity-fund-shares",
                "name": "新成立偏股型基金数量（RQData）",
                "unit": "只",
                "points": new_equity_fund_series,
            }
        )
    series.extend(partial_fund_index_series)
    payload = {
        "asOf": as_of.isoformat(),
        "top5AsOf": latest_top5["date"] if latest_top5 else None,
        "top5Concentration": top5,
        "top5ConcentrationPercentile250D": (
            round(top5_percentile, 1) if top5_percentile is not None else None
        ),
        "stockCount": stock_count,
        "top5HistoryCount": len(top5_series),
        "marketTurnoverAsOf": latest_turnover["date"] if latest_turnover else None,
        "marketTurnover": market_turnover,
        "marketTurnoverPercentile250D": (
            round(market_turnover_percentile, 1)
            if market_turnover_percentile is not None
            else None
        ),
        "marketTurnoverStockCount": (
            turnover_counts.get(pd.to_datetime(latest_turnover["date"]).date())
            if latest_turnover
            and pd.to_datetime(latest_turnover["date"]).date() in turnover_counts
            else previous.get("marketTurnoverStockCount", 0)
        ),
        "marketTurnoverHistoryCount": len(turnover_series),
        **index_ma,
        **financing,
        **land_connect,
        **etf,
        "dragonTigerNetInflow20D": dragon_tiger_net,
        "dragonTigerStockCount": dragon_tiger_count,
        **new_accounts,
        **new_equity_funds,
        **partial_fund_index,
        "etfDetails": etf_details,
        "series": series,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "asOf": payload["asOf"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
