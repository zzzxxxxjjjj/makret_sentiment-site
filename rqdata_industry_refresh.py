from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import rqdatac as rq

from rqdata_connection import initialize_rqdata

PB_FACTOR_CANDIDATES = ("pb_ratio_lf", "pb_ratio", "PB_RATIO_LF", "PB_RATIO")
# Keep the valuation chart on the ordinary parent-company TTM ROE definition.
# Do not fall back to adjusted/non-recurring-item ROE factors, otherwise a
# refresh can silently change the historical percentile methodology.
ROE_FACTOR_CANDIDATES = ("return_on_equity_ttm",)
MARKET_CAP_FACTOR_CANDIDATES = ("market_cap", "total_market_cap", "a_share_market_val", "float_market_cap")


def frame(value):
    if value is None:
        return pd.DataFrame()
    return value.reset_index() if isinstance(value, (pd.DataFrame, pd.Series)) else pd.DataFrame(value)


def batches(items, size=500):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def completed_date():
    latest = rq.get_latest_trading_date()
    latest = latest.date() if hasattr(latest, "date") else latest
    if latest >= date.today():
        calendar = rq.get_trading_dates(date.today() - timedelta(days=14), latest)
        completed = [(item.date() if hasattr(item, "date") else item) for item in calendar]
        completed = [item for item in completed if item < date.today()]
        if completed:
            return max(completed)
    return latest


def percentile_last(values):
    series = pd.Series(values).dropna()
    if series.empty:
        return float("nan")
    return float((series <= series.iloc[-1]).mean() * 100)


def rolling_percentile(values, window=250, min_periods=60):
    numeric_values = pd.to_numeric(values, errors="coerce")

    def current_rank(items):
        valid = items[pd.notna(items)]
        if len(valid) < min_periods:
            return float("nan")
        current = valid[-1]
        return float((valid <= current).mean() * 100)

    return numeric_values.rolling(window, min_periods=min_periods).apply(
        current_rank, raw=True
    )


def finite_round(value, digits=1):
    if value is None or pd.isna(value) or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def normalize_factor_frame(raw):
    data = frame(raw)
    if data.empty:
        return data
    rename = {}
    for column in data.columns:
        lower = str(column).lower()
        if lower in ("order_book_id", "order_book_ids", "code", "symbol"):
            rename[column] = "order_book_id"
        elif lower in ("date", "datetime", "trading_date"):
            rename[column] = "date"
    data = data.rename(columns=rename)
    if "order_book_id" not in data.columns and data.index.nlevels:
        data = data.reset_index()
        return normalize_factor_frame(data)
    if "date" in data.columns:
        data["date"] = pd.to_datetime(data["date"]).dt.date
    return data


def resolve_factor_name(ids, candidates, as_of):
    sample_ids = ids[: min(len(ids), 80)]
    for name in candidates:
        try:
            data = normalize_factor_frame(
                rq.get_factor(sample_ids, name, start_date=as_of, end_date=as_of, expect_df=True)
            )
            if name in data.columns and pd.to_numeric(data[name], errors="coerce").notna().any():
                return name
        except Exception:
            continue
    return None


def valuation_sample_dates(as_of):
    calendar = rq.get_trading_dates(date(2016, 1, 1), as_of)
    dates = sorted({item.date() if hasattr(item, "date") else item for item in calendar})
    if not dates:
        return [as_of]
    monthly = []
    current_month = None
    last_day = None
    for item in dates:
        month = (item.year, item.month)
        if current_month is not None and month != current_month and last_day is not None:
            monthly.append(last_day)
        current_month = month
        last_day = item
    if last_day is not None:
        monthly.append(last_day)
    if as_of not in monthly:
        monthly.append(as_of)
    return sorted(set(monthly))


def valuation_universe_and_industry(sample_date):
    instruments = rq.all_instruments(type="CS", date=sample_date)
    if instruments is None or instruments.empty or "order_book_id" not in instruments.columns:
        return [], pd.DataFrame()
    if "currency" in instruments.columns:
        instruments = instruments[
            instruments["currency"].astype(str).str.upper().isin(["CNY", "RMB"])
        ]
    sample_ids = instruments["order_book_id"].dropna().astype(str).tolist()
    industry_parts = []
    for ids_batch in batches(sample_ids):
        try:
            industry_parts.append(
                frame(
                    rq.get_instrument_industry(
                        ids_batch,
                        source="citics_2019",
                        level=1,
                        date=sample_date,
                    )
                )
            )
        except Exception:
            continue
    if not industry_parts:
        return sample_ids, pd.DataFrame()
    industry = pd.concat(industry_parts, ignore_index=True)
    code_col = next(
        (name for name in ("order_book_id", "order_book_ids") if name in industry.columns),
        None,
    )
    required = {"first_industry_code", "first_industry_name"}
    if code_col is None or not required.issubset(industry.columns):
        return sample_ids, pd.DataFrame()
    industry = industry[
        [code_col, "first_industry_code", "first_industry_name"]
    ].dropna().drop_duplicates(code_col)
    industry.columns = ["order_book_id", "industryCode", "industryName"]
    return sample_ids, industry


def build_pb_roe_percentiles(ids, industry, as_of):
    pb_factor = resolve_factor_name(ids, PB_FACTOR_CANDIDATES, as_of)
    roe_factor = resolve_factor_name(ids, ROE_FACTOR_CANDIDATES, as_of)
    cap_factor = resolve_factor_name(ids, MARKET_CAP_FACTOR_CANDIDATES, as_of)
    status = {
        "pbFactor": pb_factor,
        "roeFactor": roe_factor,
        "weightFactor": cap_factor,
        "aggregationMethod": "aggregate_fundamentals",
        "membershipMethod": "quarterly_historical_citics_constituents",
    }
    if not pb_factor or not roe_factor or not cap_factor:
        return {}, status

    requested_factors = [pb_factor, roe_factor, cap_factor]
    records = []
    membership_cache = {}
    for sample_date in valuation_sample_dates(as_of):
        if sample_date == as_of:
            sample_ids = ids
            sample_industry = industry
        else:
            membership_key = (sample_date.year, (sample_date.month - 1) // 3)
            if membership_key not in membership_cache:
                membership_cache[membership_key] = valuation_universe_and_industry(
                    sample_date
                )
            sample_ids, sample_industry = membership_cache[membership_key]
        if not sample_ids or sample_industry.empty:
            continue
        pieces = []
        for ids_batch in batches(sample_ids):
            try:
                pieces.append(
                    normalize_factor_frame(
                        rq.get_factor(ids_batch, requested_factors, start_date=sample_date, end_date=sample_date, expect_df=True)
                    )
                )
            except Exception:
                continue
        if not pieces:
            continue
        data = pd.concat(pieces, ignore_index=True)
        if "order_book_id" not in data.columns:
            continue
        data = data.merge(sample_industry, on="order_book_id", how="inner")
        data[pb_factor] = pd.to_numeric(data.get(pb_factor), errors="coerce")
        data[roe_factor] = pd.to_numeric(data.get(roe_factor), errors="coerce")
        data[cap_factor] = pd.to_numeric(data.get(cap_factor), errors="coerce")
        data = data[
            (data[pb_factor] > 0)
            & data[pb_factor].notna()
            & data[roe_factor].notna()
            & (data[cap_factor] > 0)
        ].copy()
        if data.empty:
            continue
        # Book equity proxy = market capitalisation / PB.  Aggregating the
        # underlying numerator and denominator avoids the upward bias of an
        # arithmetic market-cap-weighted average of individual PB ratios.
        data["_book_equity"] = data[cap_factor] / data[pb_factor]
        data = data[data["_book_equity"] > 0]
        if data.empty:
            continue

        rows = []
        for (industry_code, industry_name), group in data.groupby(["industryCode", "industryName"]):
            total_market_cap = group[cap_factor].sum()
            total_book_equity = group["_book_equity"].sum()
            if total_market_cap <= 0 or total_book_equity <= 0:
                continue
            pb = total_market_cap / total_book_equity
            roe = (group[roe_factor] * group["_book_equity"]).sum() / total_book_equity
            rows.append(
                {
                    "industryCode": industry_code,
                    "industryName": industry_name,
                    "date": sample_date,
                    "pb": pb,
                    "roe": roe,
                }
            )
        if rows:
            records.append(pd.DataFrame(rows))

    if not records:
        return {}, status
    history = pd.concat(records, ignore_index=True).sort_values(["industryCode", "date"])
    result = {}
    for code, part in history.groupby("industryCode"):
        part = part.dropna(subset=["pb", "roe"]).sort_values("date")
        if part.empty:
            continue
        latest = part.iloc[-1]
        result[str(code)] = {
            "pb": finite_round(latest.get("pb"), 2),
            "roe": finite_round(latest.get("roe") * 100, 2),
            "pbPercentile": finite_round(percentile_last(part["pb"]), 1),
            "roePercentile": finite_round(percentile_last(part["roe"]), 1),
            "valuationAsOf": latest["date"].isoformat(),
            "valuationSamples": int(len(part)),
        }
    return result, status


def find_column(columns, candidates, contains_all=None):
    lower_map = {str(column).lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    if contains_all:
        for column in columns:
            text = str(column).lower()
            if all(token.lower() in text for token in contains_all):
                return column
    return None


def build_payload(as_of):
    calendar = rq.get_trading_dates(as_of - timedelta(days=560), as_of)
    dates = [(item.date() if hasattr(item, "date") else item) for item in calendar][-330:]
    # 270 个交易日 ≈ 一年多一点：覆盖 250 日走势图 + 20 日均线预热
    flow_start = dates[-270] if len(dates) >= 270 else dates[0]

    instruments = rq.all_instruments(type="CS", date=as_of)
    if "currency" in instruments.columns:
        instruments = instruments[instruments["currency"].astype(str).str.upper().isin(["CNY", "RMB"])]
    ids = instruments["order_book_id"].dropna().astype(str).tolist()

    industry_parts = []
    price_parts = []
    turnover_parts = []
    margin_parts = []
    flow_parts = []
    flow_error = None
    margin_error = None

    for ids_batch in batches(ids):
        industry_parts.append(
            frame(rq.get_instrument_industry(ids_batch, source="citics_2019", level=1, date=as_of))
        )
        price_parts.append(
            frame(
                rq.get_price(
                    ids_batch,
                    dates[0],
                    dates[-1],
                    fields=["close", "total_turnover"],
                    adjust_type="none",
                    skip_suspended=True,
                )
            )
        )
        turnover_parts.append(
            frame(rq.get_turnover_rate(ids_batch, dates[0], dates[-1], fields="today"))
        )
        try:
            margin_parts.append(
                frame(
                    rq.get_securities_margin(
                        ids_batch,
                        start_date=flow_start,
                        end_date=dates[-1],
                        fields=["margin_balance", "buy_on_margin_value"],
                    )
                )
            )
        except Exception as error:
            margin_error = f"{type(error).__name__}: {error}"
        try:
            flow_parts.append(
                frame(
                    rq.get_capital_flow(
                        ids_batch,
                        start_date=flow_start,
                        end_date=dates[-1],
                        frequency="1d",
                    )
                )
            )
        except Exception as error:
            flow_error = f"{type(error).__name__}: {error}"

    industry = pd.concat(industry_parts, ignore_index=True)
    code_col = next(name for name in ("order_book_id", "order_book_ids") if name in industry.columns)
    industry = industry[[code_col, "first_industry_code", "first_industry_name"]].dropna().drop_duplicates(code_col)
    industry.columns = ["order_book_id", "industryCode", "industryName"]
    second_industry = pd.DataFrame(
        columns=["order_book_id", "parentCode", "parentName", "secondIndustryCode", "secondIndustryName"]
    )
    valuation_by_industry, valuation_status = build_pb_roe_percentiles(ids, industry, as_of)

    prices = pd.concat(price_parts, ignore_index=True)
    price_date = next(name for name in ("date", "datetime", "trading_date") if name in prices.columns)
    price_code = next(name for name in ("order_book_id", "order_book_ids") if name in prices.columns)
    prices = prices[[price_code, price_date, "close", "total_turnover"]].copy()
    prices.columns = ["order_book_id", "date", "close", "amount"]
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices["amount"] = pd.to_numeric(prices["amount"], errors="coerce")
    prices = prices.dropna(subset=["close"]).merge(industry, on="order_book_id", how="inner")
    prices = prices.sort_values(["order_book_id", "date"])

    grouped_stock = prices.groupby("order_book_id", group_keys=False)
    prices["return"] = grouped_stock["close"].pct_change()
    prices["ma20"] = grouped_stock["close"].transform(lambda values: values.rolling(20, min_periods=15).mean())
    prices["ma60"] = grouped_stock["close"].transform(lambda values: values.rolling(60, min_periods=45).mean())
    prices["high20"] = grouped_stock["close"].transform(lambda values: values.rolling(20, min_periods=15).max())
    prices["low20"] = grouped_stock["close"].transform(lambda values: values.rolling(20, min_periods=15).min())
    prices["high60"] = grouped_stock["close"].transform(lambda values: values.rolling(60, min_periods=45).max())
    prices["low60"] = grouped_stock["close"].transform(lambda values: values.rolling(60, min_periods=45).min())
    prices["above20"] = (prices["close"] > prices["ma20"]).astype(float)
    prices["above60"] = (prices["close"] > prices["ma60"]).astype(float)
    prices["newHigh20"] = (prices["close"] >= prices["high20"]).astype(float)
    prices["newLow20"] = (prices["close"] <= prices["low20"]).astype(float)
    prices["newHigh60"] = (prices["close"] >= prices["high60"]).astype(float)
    prices["newLow60"] = (prices["close"] <= prices["low60"]).astype(float)
    prices["up"] = (prices["return"] > 0).astype(float)
    prices["limitUp"] = (prices["return"] >= 0.095).astype(float)

    daily = prices.groupby(["industryCode", "industryName", "date"], as_index=False).agg(
        eligible=("order_book_id", "nunique"),
        industryReturn=("return", "mean"),
        amount=("amount", "sum"),
        aboveMa20=("above20", "mean"),
        aboveMa60=("above60", "mean"),
        newHigh20=("newHigh20", "mean"),
        newLow20=("newLow20", "mean"),
        newHigh60=("newHigh60", "mean"),
        newLow60=("newLow60", "mean"),
        upRatio=("up", "mean"),
        limitUpRatio=("limitUp", "mean"),
    )
    market = prices.groupby("date", as_index=False).agg(
        marketReturn=("return", "mean"), marketAmount=("amount", "sum")
    )
    daily = daily.merge(market, on="date", how="left").sort_values(["industryCode", "date"])
    daily["amountShare"] = daily["amount"] / daily["marketAmount"] * 100
    daily["amountShareMa20"] = daily.groupby("industryCode")["amountShare"].transform(
        lambda values: values.rolling(20, min_periods=10).mean()
    )
    daily["nhnl20"] = (daily["newHigh20"] - daily["newLow20"]) * 100
    daily["nhnl60"] = (daily["newHigh60"] - daily["newLow60"]) * 100
    daily["excessReturn"] = daily["industryReturn"] - daily["marketReturn"]
    by_industry = daily.groupby("industryCode", group_keys=False)
    daily["relativeStrength20"] = by_industry["excessReturn"].transform(
        lambda values: values.rolling(20, min_periods=15).sum()
    ) * 100

    turnover = pd.concat(turnover_parts, ignore_index=True)
    turnover_date = next(
        (name for name in ("tradedate", "date", "datetime", "trading_date") if name in turnover.columns),
        None,
    )
    turnover_code = next(
        (name for name in ("order_book_id", "order_book_ids") if name in turnover.columns),
        None,
    )
    if turnover_date and turnover_code and "today" in turnover.columns:
        turnover = turnover[[turnover_code, turnover_date, "today"]].copy()
        turnover.columns = ["order_book_id", "date", "turnover"]
        turnover["date"] = pd.to_datetime(turnover["date"]).dt.date
        turnover["turnover"] = pd.to_numeric(turnover["turnover"], errors="coerce")
        turnover = turnover.merge(industry, on="order_book_id", how="inner")
        turnover_daily = turnover.groupby(["industryCode", "date"], as_index=False)["turnover"].mean()
        daily = daily.merge(turnover_daily, on=["industryCode", "date"], how="left")
    else:
        daily["turnover"] = float("nan")

    margin_available = False
    margin = pd.DataFrame()
    usable_margin_parts = [part for part in margin_parts if not part.empty]
    if usable_margin_parts:
        raw_margin = pd.concat(usable_margin_parts, ignore_index=True)
        margin_date = next(
            (name for name in ("date", "datetime", "trading_date") if name in raw_margin.columns),
            None,
        )
        margin_code = next(
            (name for name in ("order_book_id", "order_book_ids") if name in raw_margin.columns),
            None,
        )
        if (
            margin_date
            and margin_code
            and {"margin_balance", "buy_on_margin_value"}.issubset(raw_margin.columns)
        ):
            margin_available = True
            margin = raw_margin[
                [margin_code, margin_date, "margin_balance", "buy_on_margin_value"]
            ].copy()
            margin.columns = [
                "order_book_id",
                "date",
                "marginBalance",
                "marginBuyValue",
            ]
            margin["date"] = pd.to_datetime(margin["date"]).dt.date
            margin["marginBalance"] = pd.to_numeric(
                margin["marginBalance"], errors="coerce"
            ).fillna(0)
            margin["marginBuyValue"] = pd.to_numeric(
                margin["marginBuyValue"], errors="coerce"
            ).fillna(0)
            margin = margin.merge(industry, on="order_book_id", how="inner")
            margin_daily = margin.groupby(["industryCode", "date"], as_index=False).agg(
                marginBalance=("marginBalance", "sum"),
                marginBuyValue=("marginBuyValue", "sum"),
            )
            margin_daily = margin_daily.merge(
                daily[["industryCode", "date", "amount"]],
                on=["industryCode", "date"],
                how="left",
            ).sort_values(["industryCode", "date"])
            margin_daily["marginActivity"] = (
                margin_daily["marginBuyValue"] / margin_daily["amount"] * 100
            )
            margin_grouped = margin_daily.groupby("industryCode", group_keys=False)
            margin_daily["marginActivityMa20"] = margin_grouped[
                "marginActivity"
            ].transform(lambda values: values.rolling(20, min_periods=10).mean())
            margin_daily["marginBalanceChange20"] = margin_grouped[
                "marginBalance"
            ].pct_change(20) * 100
            daily = daily.merge(
                margin_daily[
                    [
                        "industryCode",
                        "date",
                        "marginBalance",
                        "marginBuyValue",
                        "marginActivity",
                        "marginActivityMa20",
                        "marginBalanceChange20",
                    ]
                ],
                on=["industryCode", "date"],
                how="left",
            )
    if "marginActivity" not in daily.columns:
        for column in (
            "marginBalance",
            "marginBuyValue",
            "marginActivity",
            "marginActivityMa20",
            "marginBalanceChange20",
        ):
            daily[column] = float("nan")

    crowding_grouped = daily.groupby("industryCode", group_keys=False)
    daily["turnoverPercentile"] = crowding_grouped["turnover"].transform(
        rolling_percentile
    )
    daily["amountSharePercentile"] = crowding_grouped["amountShare"].transform(
        rolling_percentile
    )
    daily["marginActivityPercentile"] = crowding_grouped["marginActivity"].transform(
        lambda values: rolling_percentile(values, window=100, min_periods=40)
    )
    daily["relativeStrengthPercentile"] = crowding_grouped["relativeStrength20"].transform(
        rolling_percentile
    )
    daily["crowdingScore"] = (
        daily["turnoverPercentile"] * 0.50
        + daily["amountSharePercentile"] * 0.30
        + daily["relativeStrengthPercentile"] * 0.20
    )

    flow_stock = pd.DataFrame()
    flow_available = False
    usable_flow_parts = [part for part in flow_parts if not part.empty]
    if usable_flow_parts:
        raw_flow = pd.concat(usable_flow_parts, ignore_index=True)
        flow_date = next(
            (name for name in ("tradedate", "date", "datetime", "trading_date") if name in raw_flow.columns),
            None,
        )
        flow_code = next(
            (name for name in ("order_book_id", "order_book_ids") if name in raw_flow.columns),
            None,
        )
        required = {"buy_value", "sell_value"}
        if flow_date and flow_code and required.issubset(raw_flow.columns):
            flow_available = True
            flow_stock = raw_flow[[flow_code, flow_date, "buy_value", "sell_value"]].copy()
            flow_stock.columns = ["order_book_id", "date", "buyValue", "sellValue"]
            flow_stock["date"] = pd.to_datetime(flow_stock["date"]).dt.date
            for column in ("buyValue", "sellValue"):
                flow_stock[column] = pd.to_numeric(flow_stock[column], errors="coerce").fillna(0)
            flow_stock["netFlow"] = flow_stock["buyValue"] - flow_stock["sellValue"]
            flow_stock = flow_stock.merge(industry, on="order_book_id", how="inner")

            flow_daily = flow_stock.groupby(
                ["industryCode", "industryName", "date"], as_index=False
            ).agg(
                netFlow=("netFlow", "sum"),
                buyValue=("buyValue", "sum"),
                sellValue=("sellValue", "sum"),
                flowStocks=("order_book_id", "nunique"),
                positiveFlowStocks=("netFlow", lambda values: int((values > 0).sum())),
            )
            flow_daily["flowBreadth"] = (
                flow_daily["positiveFlowStocks"] / flow_daily["flowStocks"] * 100
            )
            flow_daily = flow_daily.merge(
                daily[["industryCode", "date", "amount"]],
                on=["industryCode", "date"],
                how="left",
            ).sort_values(["industryCode", "date"])
            flow_grouped = flow_daily.groupby("industryCode", group_keys=False)
            flow_daily["flow1D"] = flow_daily["netFlow"] / 1e8
            flow_daily["flow5D"] = flow_grouped["netFlow"].transform(
                lambda values: values.rolling(5, min_periods=1).sum()
            ) / 1e8
            flow_daily["flow20D"] = flow_grouped["netFlow"].transform(
                lambda values: values.rolling(20, min_periods=1).sum()
            ) / 1e8
            flow_daily["flowRatio1D"] = flow_daily["netFlow"] / flow_daily["amount"] * 100
            rolling_net_5 = flow_grouped["netFlow"].transform(
                lambda values: values.rolling(5, min_periods=1).sum()
            )
            rolling_net_20 = flow_grouped["netFlow"].transform(
                lambda values: values.rolling(20, min_periods=1).sum()
            )
            rolling_amount_5 = flow_grouped["amount"].transform(
                lambda values: values.rolling(5, min_periods=1).sum()
            )
            rolling_amount_20 = flow_grouped["amount"].transform(
                lambda values: values.rolling(20, min_periods=1).sum()
            )
            flow_daily["flowRatio5D"] = rolling_net_5 / rolling_amount_5 * 100
            flow_daily["flowRatio20D"] = rolling_net_20 / rolling_amount_20 * 100
            flow_daily["flowBreadth5D"] = flow_grouped["flowBreadth"].transform(
                lambda values: values.rolling(5, min_periods=1).mean()
            )
            flow_daily["positiveDays20"] = flow_grouped["netFlow"].transform(
                lambda values: values.gt(0).rolling(20, min_periods=1).sum()
            )
            flow_columns = [
                "industryCode",
                "date",
                "flow1D",
                "flow5D",
                "flow20D",
                "flowRatio1D",
                "flowRatio5D",
                "flowRatio20D",
                "flowBreadth",
                "flowBreadth5D",
                "positiveDays20",
            ]
            daily = daily.merge(flow_daily[flow_columns], on=["industryCode", "date"], how="left")

    flow_concentrations = {}
    if not flow_stock.empty:
        latest_flow_date = max(flow_stock["date"])
        for code, part in flow_stock[flow_stock["date"] == latest_flow_date].groupby("industryCode"):
            net = part["netFlow"].dropna()
            total_net = float(net.sum())
            directional = net[net > 0] if total_net >= 0 else -net[net < 0]
            directional = directional.sort_values(ascending=False)
            if not directional.empty and directional.sum() > 0:
                count = max(1, math.ceil(len(directional) * 0.05))
                flow_concentrations[code] = {
                    "value": float(directional.iloc[:count].sum() / directional.sum() * 100),
                    "side": "流入" if total_net >= 0 else "流出",
                }

    children_by_parent = {}
    if not second_industry.empty:
        second_prices = prices.merge(second_industry, on="order_book_id", how="inner")
        second_daily = second_prices.groupby(
            ["parentCode", "parentName", "secondIndustryCode", "secondIndustryName", "date"],
            as_index=False,
        ).agg(
            amount=("amount", "sum"),
            industryReturn=("return", "mean"),
            upRatio=("up", "mean"),
            aboveMa20=("above20", "mean"),
            aboveMa60=("above60", "mean"),
        )
        second_daily = second_daily.merge(market, on="date", how="left").sort_values(["secondIndustryCode", "date"])
        second_daily["amountShare"] = second_daily["amount"] / second_daily["marketAmount"] * 100
        second_daily["amountShareMa20"] = second_daily.groupby("secondIndustryCode")["amountShare"].transform(
            lambda values: values.rolling(20, min_periods=10).mean()
        )
        second_daily["excessReturn"] = second_daily["industryReturn"] - second_daily["marketReturn"]
        second_grouped = second_daily.groupby("secondIndustryCode", group_keys=False)
        second_daily["relativeStrength20"] = second_grouped["excessReturn"].transform(
            lambda values: values.rolling(20, min_periods=15).sum()
        ) * 100

        if "turnover" in locals() and isinstance(turnover, pd.DataFrame) and not turnover.empty and "order_book_id" in turnover.columns:
            second_turnover = turnover.merge(second_industry, on="order_book_id", how="inner")
            second_turnover_daily = second_turnover.groupby(["secondIndustryCode", "date"], as_index=False)["turnover"].mean()
            second_daily = second_daily.merge(second_turnover_daily, on=["secondIndustryCode", "date"], how="left")
        else:
            second_daily["turnover"] = float("nan")

        if not margin.empty:
            second_margin = margin.merge(second_industry, on="order_book_id", how="inner")
            second_margin_daily = second_margin.groupby(["secondIndustryCode", "date"], as_index=False).agg(
                marginBalance=("marginBalance", "sum"),
                marginBuyValue=("marginBuyValue", "sum"),
            )
            second_margin_daily = second_margin_daily.merge(
                second_daily[["secondIndustryCode", "date", "amount"]],
                on=["secondIndustryCode", "date"],
                how="left",
            ).sort_values(["secondIndustryCode", "date"])
            second_margin_daily["marginActivity"] = second_margin_daily["marginBuyValue"] / second_margin_daily["amount"] * 100
            second_margin_grouped = second_margin_daily.groupby("secondIndustryCode", group_keys=False)
            second_margin_daily["marginActivityMa20"] = second_margin_grouped["marginActivity"].transform(
                lambda values: values.rolling(20, min_periods=10).mean()
            )
            second_margin_daily["marginBalanceChange20"] = second_margin_grouped["marginBalance"].pct_change(20) * 100
            second_daily = second_daily.merge(
                second_margin_daily[
                    [
                        "secondIndustryCode",
                        "date",
                        "marginBalance",
                        "marginBuyValue",
                        "marginActivity",
                        "marginActivityMa20",
                        "marginBalanceChange20",
                    ]
                ],
                on=["secondIndustryCode", "date"],
                how="left",
            )
        for column in ("marginBalance", "marginBuyValue", "marginActivity", "marginActivityMa20", "marginBalanceChange20"):
            if column not in second_daily.columns:
                second_daily[column] = float("nan")

        second_grouped = second_daily.groupby("secondIndustryCode", group_keys=False)
        second_daily["turnoverPercentile"] = second_grouped["turnover"].transform(rolling_percentile)
        second_daily["amountSharePercentile"] = second_grouped["amountShare"].transform(rolling_percentile)
        second_daily["marginActivityPercentile"] = second_grouped["marginActivity"].transform(
            lambda values: rolling_percentile(values, window=100, min_periods=40)
        )
        second_daily["relativeStrengthPercentile"] = second_grouped["relativeStrength20"].transform(rolling_percentile)
        second_daily["crowdingScore"] = (
            second_daily["turnoverPercentile"] * 0.50
            + second_daily["amountSharePercentile"] * 0.30
            + second_daily["relativeStrengthPercentile"] * 0.20
        )

        if not flow_stock.empty:
            second_flow_stock = flow_stock.merge(second_industry, on="order_book_id", how="inner")
            second_flow_daily = second_flow_stock.groupby(
                ["secondIndustryCode", "date"], as_index=False
            ).agg(
                netFlow=("netFlow", "sum"),
                flowStocks=("order_book_id", "nunique"),
                positiveFlowStocks=("netFlow", lambda values: int((values > 0).sum())),
            )
            second_flow_daily["flowBreadth"] = second_flow_daily["positiveFlowStocks"] / second_flow_daily["flowStocks"] * 100
            second_flow_daily = second_flow_daily.merge(
                second_daily[["secondIndustryCode", "date", "amount"]],
                on=["secondIndustryCode", "date"],
                how="left",
            ).sort_values(["secondIndustryCode", "date"])
            second_flow_grouped = second_flow_daily.groupby("secondIndustryCode", group_keys=False)
            second_flow_daily["flow1D"] = second_flow_daily["netFlow"] / 1e8
            second_flow_daily["flow5D"] = second_flow_grouped["netFlow"].transform(lambda values: values.rolling(5, min_periods=1).sum()) / 1e8
            second_flow_daily["flow20D"] = second_flow_grouped["netFlow"].transform(lambda values: values.rolling(20, min_periods=1).sum()) / 1e8
            second_flow_daily["flowRatio1D"] = second_flow_daily["netFlow"] / second_flow_daily["amount"] * 100
            second_flow_daily["flowRatio5D"] = (
                second_flow_grouped["netFlow"].transform(lambda values: values.rolling(5, min_periods=1).sum())
                / second_flow_grouped["amount"].transform(lambda values: values.rolling(5, min_periods=1).sum())
                * 100
            )
            second_flow_daily["flowRatio20D"] = (
                second_flow_grouped["netFlow"].transform(lambda values: values.rolling(20, min_periods=1).sum())
                / second_flow_grouped["amount"].transform(lambda values: values.rolling(20, min_periods=1).sum())
                * 100
            )
            second_flow_daily["flowBreadth5D"] = second_flow_grouped["flowBreadth"].transform(
                lambda values: values.rolling(5, min_periods=1).mean()
            )
            second_flow_daily["positiveDays20"] = second_flow_grouped["netFlow"].transform(
                lambda values: values.gt(0).rolling(20, min_periods=1).sum()
            )
            second_daily = second_daily.merge(
                second_flow_daily[
                    [
                        "secondIndustryCode",
                        "date",
                        "flow1D",
                        "flow5D",
                        "flow20D",
                        "flowRatio1D",
                        "flowRatio5D",
                        "flowRatio20D",
                        "flowBreadth",
                        "flowBreadth5D",
                        "positiveDays20",
                    ]
                ],
                on=["secondIndustryCode", "date"],
                how="left",
            )

        for code, history in second_daily.groupby("secondIndustryCode"):
            history = history.sort_values("date")
            item = history.iloc[-1]
            child = {
                "code": str(item["secondIndustryCode"]),
                "name": str(item["secondIndustryName"]),
                "parentCode": str(item["parentCode"]),
                "parentName": str(item["parentName"]),
                "asOf": item["date"].isoformat(),
                "flow1D": finite_round(item.get("flow1D"), 2),
                "flow5D": finite_round(item.get("flow5D"), 2),
                "flow20D": finite_round(item.get("flow20D"), 2),
                "flowRatio1D": finite_round(item.get("flowRatio1D"), 2),
                "flowRatio5D": finite_round(item.get("flowRatio5D"), 2),
                "flowRatio20D": finite_round(item.get("flowRatio20D"), 2),
                "flowBreadth": finite_round(item.get("flowBreadth"), 1),
                "flowBreadth5D": finite_round(item.get("flowBreadth5D"), 1),
                "positiveDays20": finite_round(item.get("positiveDays20"), 0),
                "turnover": finite_round(item.get("turnover"), 3),
                "amountShare": finite_round(item.get("amountShare"), 2),
                "amountShareMa20": finite_round(item.get("amountShareMa20"), 2),
                "turnoverPercentile": finite_round(item.get("turnoverPercentile"), 1),
                "amountSharePercentile": finite_round(item.get("amountSharePercentile"), 1),
                "marginBalance": finite_round(item.get("marginBalance") / 1e8, 2),
                "marginBuyValue": finite_round(item.get("marginBuyValue") / 1e8, 2),
                "marginActivity": finite_round(item.get("marginActivity"), 2),
                "marginActivityMa20": finite_round(item.get("marginActivityMa20"), 2),
                "marginActivityPercentile": finite_round(item.get("marginActivityPercentile"), 1),
                "marginBalanceChange20": finite_round(item.get("marginBalanceChange20"), 2),
                "relativeStrength20": finite_round(item.get("relativeStrength20"), 2),
                "relativeStrengthPercentile": finite_round(item.get("relativeStrengthPercentile"), 1),
                "crowdingScore": finite_round(item.get("crowdingScore"), 1),
                "upRatio": finite_round(float(item["upRatio"]) * 100, 1),
                "aboveMa20": finite_round(float(item["aboveMa20"]) * 100, 1),
                "aboveMa60": finite_round(float(item["aboveMa60"]) * 100, 1),
            }
            children_by_parent.setdefault(str(item["parentCode"]), []).append(child)

        for children in children_by_parent.values():
            children.sort(
                key=lambda item: item["flowRatio5D"] if item["flowRatio5D"] is not None else -999,
                reverse=True,
            )

    industries = []
    for code, history in daily.groupby("industryCode"):
        history = history.sort_values("date")
        item = history.iloc[-1]
        if str(item["industryName"]).strip() == "综合":
            continue
        concentration = flow_concentrations.get(code, {})
        valuation = valuation_by_industry.get(str(code), {})
        industries.append(
            {
                "code": str(code),
                "name": str(item["industryName"]),
                "asOf": item["date"].isoformat(),
                "flow1D": finite_round(item.get("flow1D"), 2),
                "flow5D": finite_round(item.get("flow5D"), 2),
                "flow20D": finite_round(item.get("flow20D"), 2),
                "flowRatio1D": finite_round(item.get("flowRatio1D"), 2),
                "flowRatio5D": finite_round(item.get("flowRatio5D"), 2),
                "flowRatio20D": finite_round(item.get("flowRatio20D"), 2),
                "flowBreadth": finite_round(item.get("flowBreadth"), 1),
                "flowBreadth5D": finite_round(item.get("flowBreadth5D"), 1),
                "positiveDays20": finite_round(item.get("positiveDays20"), 0),
                "flowConcentration": finite_round(concentration.get("value"), 1),
                "flowConcentrationSide": concentration.get("side"),
                "aboveMa20": finite_round(float(item["aboveMa20"]) * 100, 1),
                "aboveMa60": finite_round(float(item["aboveMa60"]) * 100, 1),
                "nhnl20": finite_round(item["nhnl20"], 1),
                "nhnl60": finite_round(item["nhnl60"], 1),
                "relativeStrength20": finite_round(item["relativeStrength20"], 2),
                "turnover": finite_round(item["turnover"], 3),
                "amountShare": finite_round(item["amountShare"], 2),
                "amountShareMa20": finite_round(item["amountShareMa20"], 2),
                "turnoverPercentile": finite_round(item["turnoverPercentile"], 1),
                "amountSharePercentile": finite_round(item["amountSharePercentile"], 1),
                "marginBalance": finite_round(item["marginBalance"] / 1e8, 2),
                "marginBuyValue": finite_round(item["marginBuyValue"] / 1e8, 2),
                "marginActivity": finite_round(item["marginActivity"], 2),
                "marginActivityMa20": finite_round(item["marginActivityMa20"], 2),
                "marginActivityPercentile": finite_round(
                    item["marginActivityPercentile"], 1
                ),
                "marginBalanceChange20": finite_round(
                    item["marginBalanceChange20"], 2
                ),
                "relativeStrengthPercentile": finite_round(item["relativeStrengthPercentile"], 1),
                "crowdingScore": finite_round(item["crowdingScore"], 1),
                "upRatio": finite_round(float(item["upRatio"]) * 100, 1),
                "limitUpRatio": finite_round(float(item["limitUpRatio"]) * 100, 2),
                "pb": valuation.get("pb"),
                "roe": valuation.get("roe"),
                "pbPercentile": valuation.get("pbPercentile"),
                "roePercentile": valuation.get("roePercentile"),
                "valuationAsOf": valuation.get("valuationAsOf"),
                "valuationSamples": valuation.get("valuationSamples"),
                "crowdingSeries": [
                    {
                        "date": row["date"].isoformat(),
                        "crowdingScore": finite_round(row.get("crowdingScore"), 1),
                        "turnoverPercentile": finite_round(row.get("turnoverPercentile"), 1),
                        "amountSharePercentile": finite_round(row.get("amountSharePercentile"), 1),
                        "relativeStrengthPercentile": finite_round(row.get("relativeStrengthPercentile"), 1),
                    }
                    for _, row in history.tail(250).iterrows()
                    if pd.notna(row.get("crowdingScore"))
                ],
                "series": [
                    {
                        "date": row["date"].isoformat(),
                        "netFlow": finite_round(row.get("flow1D"), 2),
                        "flowRatio": finite_round(row.get("flowRatio1D"), 2),
                        "flowBreadth": finite_round(row.get("flowBreadth"), 1),
                        "amountShare": finite_round(row.get("amountShare"), 2),
                        "marginActivity": finite_round(row.get("marginActivity"), 2),
                        "industryReturn": finite_round(row.get("industryReturn") * 100, 2),
                    }
                    for _, row in history.tail(250).iterrows()
                    if pd.notna(row.get("flow1D"))
                ],
                "children": children_by_parent.get(str(code), []),
            }
        )

    industries.sort(
        key=lambda item: item["flowRatio5D"] if item["flowRatio5D"] is not None else -999,
        reverse=True,
    )
    source = "RQData / 中信2019一级行业"
    if flow_error and not usable_flow_parts:
        source += "（主动资金接口本次未返回数据）"
    return {
        "asOf": as_of.isoformat(),
        "source": source,
        "method": (
            "不合成情绪分。主动资金净额＝成分股主动买入额－主动卖出额；"
            "净流入率＝主动资金净额÷行业成交额。行业拥挤度＝换手率分位50%＋"
            "成交额占比分位30%＋20日相对强弱分位20%，均使用近250日滚动分位。"
            "行业PB＝成分股总市值合计÷净资产代理值合计；行业普通TTM ROE按净资产代理值加权，"
            "历史分位使用2016年以来月末数据，并按季度恢复当时的中信一级行业成分。"
        ),
        "flowAvailable": flow_available,
        "marginAvailable": margin_available,
        "marginError": margin_error,
        "valuationAvailable": bool(valuation_by_industry),
        "valuationFactorStatus": valuation_status,
        "industries": industries,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    initialize_rqdata()
    as_of = completed_date()
    payload = build_payload(as_of)
    Path(args.output).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": True,
                "asOf": payload["asOf"],
                "industries": len(payload["industries"]),
                "flowAvailable": payload["flowAvailable"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
