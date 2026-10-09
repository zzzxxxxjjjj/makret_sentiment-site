from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import rqdatac as rq


CATEGORY = "标准股票型"


def quarter_ends(start: date, end: date) -> list[date]:
    dates = pd.date_range(start=start, end=end, freq="QE-DEC")
    return [item.date() for item in dates]


def latest_completed_quarter(today: date) -> date:
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    quarter_start = date(today.year, quarter_start_month, 1)
    return (pd.Timestamp(quarter_start) - pd.Timedelta(days=1)).date()


def normalized_frame(value) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    data = value.reset_index() if isinstance(value, (pd.DataFrame, pd.Series)) else pd.DataFrame(value)
    if "datetime" in data.columns:
        data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    return data


def read_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fetch_quarter(sample_date: date) -> dict | None:
    date_text = sample_date.isoformat()
    category_ids = set(
        str(item)
        for item in (rq.fund.get_category({"fund_type": [CATEGORY]}, date=date_text) or [])
    )
    instruments = rq.fund.all_instruments(date=date_text)
    if instruments is None or instruments.empty or "order_book_id" not in instruments.columns:
        return None
    active_ids = set(instruments["order_book_id"].dropna().astype(str))
    fund_ids = sorted(category_ids & active_ids)
    if not fund_ids:
        return None

    raw = normalized_frame(rq.fund.get_units_change(fund_ids, date=date_text))
    if raw.empty or "datetime" not in raw.columns:
        return None
    raw = raw[raw["datetime"].eq(pd.Timestamp(sample_date))].copy()
    if raw.empty:
        return None

    for column in ("net_asset", "units", "subscribe_units", "redeem_units"):
        raw[column] = pd.to_numeric(raw.get(column), errors="coerce")
    valid = raw[raw["net_asset"].notna() & (raw["net_asset"] >= 0)].copy()
    if valid.empty:
        return None

    estimated_flow = valid[
        valid["units"].notna()
        & (valid["units"] > 0)
        & valid["subscribe_units"].notna()
        & valid["redeem_units"].notna()
    ].copy()
    if estimated_flow.empty:
        estimated_net_subscription = None
    else:
        estimated_flow["unit_value_proxy"] = estimated_flow["net_asset"] / estimated_flow["units"]
        estimated_flow["net_subscription_value"] = (
            (estimated_flow["subscribe_units"] - estimated_flow["redeem_units"])
            * estimated_flow["unit_value_proxy"]
        )
        estimated_net_subscription = float(estimated_flow["net_subscription_value"].sum() / 1e8)

    info_dates = pd.to_datetime(valid.get("info_date"), errors="coerce").dropna()
    return {
        "date": date_text,
        "netAssets": round(float(valid["net_asset"].sum() / 1e8), 2),
        "estimatedNetSubscription": (
            round(estimated_net_subscription, 2)
            if estimated_net_subscription is not None
            else None
        ),
        "eligibleFunds": len(fund_ids),
        "validFunds": int(valid["net_asset"].notna().sum()),
        "infoDate": info_dates.max().date().isoformat() if not info_dates.empty else None,
    }


def add_changes(points: list[dict]) -> list[dict]:
    result = []
    previous = None
    for point in sorted(points, key=lambda item: item["date"]):
        current = point.get("netAssets")
        point = dict(point)
        point["qoqChange"] = (
            round((current / previous - 1) * 100, 2)
            if previous not in (None, 0) and current is not None
            else None
        )
        if current is not None:
            previous = current
        result.append(point)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="rqdata-fund-scale.json")
    parser.add_argument("--start", default="2021-06-30")
    args = parser.parse_args()

    output = Path(args.output)
    rq.init()
    end = latest_completed_quarter(date.today())
    dates = quarter_ends(pd.Timestamp(args.start).date(), end)
    existing = read_existing(output)
    existing_by_date = {
        str(item.get("date")): item
        for item in existing.get("points", [])
        if item.get("date")
    }

    points = []
    for sample_date in dates:
        date_text = sample_date.isoformat()
        # Historical disclosures are stable. Refresh the latest completed
        # quarter because fund reports arrive over several weeks.
        if date_text in existing_by_date and sample_date != end:
            points.append(existing_by_date[date_text])
            continue
        print(f"正在读取普通股票型基金规模：{date_text}", flush=True)
        point = fetch_quarter(sample_date)
        if point:
            points.append(point)
        elif date_text in existing_by_date:
            points.append(existing_by_date[date_text])

    points = add_changes(points)
    latest = points[-1] if points else {}
    payload = {
        "asOf": latest.get("date"),
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "RQData / 聚源公募基金分类",
        "frequency": "quarterly",
        "category": CATEGORY,
        "method": (
            "按每个季度末的聚源三级分类‘标准股票型’恢复当期基金范围；"
            "基金规模为有效基金子份额期末净资产合计，季度规模环比包含申赎与净值涨跌影响。"
        ),
        "points": points,
    }
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    print(
        f"普通股票型基金规模更新完成：{len(points)}个季度，"
        f"最新{latest.get('date')}，{latest.get('netAssets')}亿元",
        flush=True,
    )


if __name__ == "__main__":
    main()
