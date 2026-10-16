from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import rqdatac as rq

from rqdata_connection import initialize_rqdata
from rqdata_history_cache import history as cached_history

DEFAULT_OUTPUT = Path(__file__).with_name("rqdata-industry-sentiment.json")


def frame(value):
    if isinstance(value, pd.DataFrame):
        return value.reset_index()
    if isinstance(value, pd.Series):
        return value.reset_index()
    return pd.DataFrame(value or [])


def pick(columns, names):
    return next((name for name in names if name in columns), None)


def clean(value, digits=2):
    try:
        return round(float(value), digits)
    except Exception:
        return None


def batches(items, size=250):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def stock_names(stocks):
    result = {}
    for part in batches(stocks, 500):
        for instrument in rq.instruments(part):
            result[instrument.order_book_id] = getattr(instrument, "symbol", None) or instrument.order_book_id
    return result


def load_payload(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    industries = [
        item for item in payload.get("industries", [])
        if item.get("code") and str(item.get("name", "")).strip() != "综合"
    ]
    if not industries:
        raise RuntimeError("行业缓存中没有可用的一级行业")
    return payload, industries


def collect_parent_stocks(industries, as_of):
    rows = []
    for industry in industries:
        code = str(industry["code"])
        for stock in rq.get_industry(code, source="citics_2019", date=as_of) or []:
            rows.append({
                "order_book_id": stock,
                "parentCode": code,
                "parentName": industry.get("name") or code,
            })
    parent = pd.DataFrame(rows).drop_duplicates()
    if parent.empty:
        raise RuntimeError("未取到中信一级行业成分股")
    return parent


def fetch_second_mapping(stocks, as_of):
    parts = []
    for part in batches(stocks, 500):
        raw = frame(rq.get_instrument_industry(part, source="citics_2019", level=0, date=as_of))
        code_col = pick(raw.columns, ("order_book_id", "order_book_ids", "code"))
        if raw.empty or not code_col:
            continue
        if "second_industry_code" not in raw or "second_industry_name" not in raw:
            continue
        item = raw[[code_col, "second_industry_code", "second_industry_name"]].copy()
        item.columns = ["order_book_id", "secondIndustryCode", "secondIndustryName"]
        parts.append(item)
    if not parts:
        raise RuntimeError("未取到中信二级行业映射")
    data = pd.concat(parts, ignore_index=True).dropna(subset=["secondIndustryCode"])
    data["secondIndustryCode"] = data["secondIndustryCode"].astype(str)
    return data.drop_duplicates("order_book_id")


def fetch_capital_flow(stocks, start, end):
    parts = []
    for part in batches(stocks):
        try:
            raw = frame(cached_history(rq,"get_capital_flow",part,start,end,frequency="1d"))
        except Exception as exc:
            print(f"资金流分块跳过 {len(part)} 只：{exc}")
            continue
        code_col = pick(raw.columns, ("order_book_id", "order_book_ids", "code"))
        date_col = pick(raw.columns, ("date", "datetime", "trading_date", "tradedate"))
        if raw.empty or not code_col or not date_col:
            continue
        if "buy_value" not in raw or "sell_value" not in raw:
            continue
        item = raw[[code_col, date_col, "buy_value", "sell_value"]].copy()
        item.columns = ["order_book_id", "date", "buyValue", "sellValue"]
        item["date"] = pd.to_datetime(item["date"]).dt.date
        item["buyValue"] = pd.to_numeric(item["buyValue"], errors="coerce").fillna(0)
        item["sellValue"] = pd.to_numeric(item["sellValue"], errors="coerce").fillna(0)
        item["netFlow"] = item["buyValue"] - item["sellValue"]
        parts.append(item)
    if not parts:
        raise RuntimeError("未取到主动资金流数据")
    return pd.concat(parts, ignore_index=True)


def build_children(parent, second, flow, names):
    mapped = flow.merge(parent, on="order_book_id", how="inner")
    mapped = mapped.merge(second, on="order_book_id", how="inner")
    daily = mapped.groupby(
        ["parentCode", "parentName", "secondIndustryCode", "secondIndustryName", "date"],
        as_index=False,
    ).agg(
        netFlow=("netFlow", "sum"),
        stockCount=("order_book_id", "nunique"),
        positiveStocks=("netFlow", lambda values: int((values > 0).sum())),
    )
    daily = daily.sort_values(["secondIndustryCode", "date"])
    grouped = daily.groupby("secondIndustryCode", group_keys=False)
    daily["flow1D"] = daily["netFlow"] / 1e8
    daily["flow5D"] = grouped["netFlow"].transform(lambda values: values.rolling(5, min_periods=1).sum()) / 1e8
    daily["flow20D"] = grouped["netFlow"].transform(lambda values: values.rolling(20, min_periods=1).sum()) / 1e8
    daily["flowBreadth"] = daily["positiveStocks"] / daily["stockCount"] * 100
    daily["flowBreadth5D"] = grouped["flowBreadth"].transform(lambda values: values.rolling(5, min_periods=1).mean())

    latest_dates = mapped.groupby("order_book_id")["date"].max().rename("latestDate").reset_index()
    stock_daily = mapped.groupby(
        ["parentCode", "secondIndustryCode", "order_book_id", "date"],
        as_index=False,
    ).agg(netFlow=("netFlow", "sum"))
    stock_daily = stock_daily.sort_values(["secondIndustryCode", "order_book_id", "date"])
    stock_grouped = stock_daily.groupby(["secondIndustryCode", "order_book_id"], group_keys=False)
    stock_daily["flow5D"] = stock_grouped["netFlow"].transform(lambda values: values.rolling(5, min_periods=1).sum()) / 1e8
    stock_latest = stock_daily.merge(latest_dates, on="order_book_id", how="left")
    stock_latest = stock_latest[stock_latest["date"] == stock_latest["latestDate"]].copy()
    stock_latest["flow1D"] = stock_latest["netFlow"] / 1e8
    top_stocks = {}
    for code, part in stock_latest.groupby("secondIndustryCode"):
        leaders = part.sort_values("flow5D", ascending=False).head(8)
        top_stocks[str(code)] = [
            {
                "orderBookId": str(row["order_book_id"]),
                "name": names.get(str(row["order_book_id"]), str(row["order_book_id"])),
                "flow1D": clean(row["flow1D"]),
                "flow5D": clean(row["flow5D"]),
            }
            for _, row in leaders.iterrows()
        ]

    children = {}
    for _, row in daily.groupby("secondIndustryCode").tail(1).iterrows():
        child = {
            "code": str(row["secondIndustryCode"]),
            "name": str(row["secondIndustryName"]),
            "parentCode": str(row["parentCode"]),
            "parentName": str(row["parentName"]),
            "asOf": row["date"].isoformat(),
            "flow1D": clean(row["flow1D"]),
            "flow5D": clean(row["flow5D"]),
            "flow20D": clean(row["flow20D"]),
            "flowBreadth": clean(row["flowBreadth"], 1),
            "flowBreadth5D": clean(row["flowBreadth5D"], 1),
            "topStocks": top_stocks.get(str(row["secondIndustryCode"]), []),
        }
        children.setdefault(str(row["parentCode"]), []).append(child)
    for items in children.values():
        items.sort(
            key=lambda item: item["flow5D"] if item["flow5D"] is not None else -999999,
            reverse=True,
        )
    return children


def main():
    parser = argparse.ArgumentParser(description="只刷新中信二级行业主动资金 children 数据。")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--as-of")
    parser.add_argument("--lookback-days", type=int, default=45)
    args = parser.parse_args()

    output = Path(args.output)
    payload, industries = load_payload(output)
    as_of = datetime.strptime(str(args.as_of or payload.get("asOf"))[:10], "%Y-%m-%d").date()
    existing = [child for industry in industries for child in industry.get('children', [])]
    if existing and all(child.get('asOf') == as_of.isoformat() for child in existing):
        print('Second-industry observations already current: '+as_of.isoformat())
        return
    start = as_of - timedelta(days=args.lookback_days)

    initialize_rqdata()
    parent = collect_parent_stocks(industries, as_of)
    stocks = sorted(parent["order_book_id"].unique())
    print(f"拉取二级行业主动资金：{start} ~ {as_of}，股票 {len(stocks)} 只")
    names = stock_names(stocks)
    second = fetch_second_mapping(stocks, as_of)
    flow = fetch_capital_flow(stocks, start, as_of)
    children = build_children(parent, second, flow, names)

    total = 0
    for industry in industries:
        industry["children"] = children.get(str(industry["code"]), [])
        total += len(industry["children"])
    payload["secondIndustryFlowAsOf"] = as_of.isoformat()
    payload["secondIndustryFlowSource"] = "RQData / 中信2019二级行业 / 主动买入额-主动卖出额"
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"完成：写入 {total} 个二级行业 children 到 {output}")


if __name__ == "__main__":
    main()
