from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import rqdatac as rq
from openpyxl import load_workbook


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_sources"
DEFAULT_CREDIT = DATA_DIR / "信贷脉冲-更新版.xlsm"
DEFAULT_FX = DATA_DIR / "外汇脉冲.xlsx"
DEFAULT_MARKET = Path.home() / "OneDrive" / "文档" / "市场宽基情绪指标.xlsx"
MIN_DISPLAY_DATE = "2016-01-01"
HS300_INDEX = "000300.XSHG"
ALL_A_INDEX = "000985.XSHG"


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def iso_month(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return None


def points_from_columns(worksheet, date_column, value_column, *, scale=1.0):
    points = []
    for row in range(3, worksheet.max_row + 1):
        month = iso_month(worksheet.cell(row, date_column).value)
        value = number(worksheet.cell(row, value_column).value)
        if month is None or month < MIN_DISPLAY_DATE or value is None:
            continue
        points.append({"date": month, "value": round(value * scale, 6)})
    points.sort(key=lambda item: item["date"])
    return points


def frame(value):
    if value is None:
        return pd.DataFrame()
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return value.reset_index()
    return pd.DataFrame(value)


def normalize_price(raw):
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
    if "date" not in data.columns and data.index.nlevels:
        return normalize_price(data.reset_index())
    if "close" not in data.columns:
        raise RuntimeError("RQData沪深300行情缺少close字段")
    data["date"] = pd.to_datetime(data["date"])
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    return data[["date", "close"]].dropna().sort_values("date")


def latest_completed_month(latest_trading_date):
    latest = pd.Timestamp(latest_trading_date).date()
    month_start = latest.replace(day=1)
    month_end = (pd.Timestamp(month_start) + pd.offsets.MonthEnd(0)).date()
    month_trading_dates = rq.get_trading_dates(month_start, month_end)
    month_trading_dates = [
        item.date() if hasattr(item, "date") else item
        for item in month_trading_dates
    ]
    if month_trading_dates and latest == max(month_trading_dates):
        return latest
    return (pd.Timestamp(month_start) - pd.offsets.Day(1)).date()


def read_hs300_yoy():
    rq.init()
    latest = rq.get_latest_trading_date()
    latest = latest.date() if hasattr(latest, "date") else latest
    completed_month = latest_completed_month(latest)
    start = "2015-01-01"
    raw = rq.get_price(
        HS300_INDEX,
        start,
        completed_month,
        fields=["close"],
        adjust_type="none",
        skip_suspended=False,
    )
    prices = normalize_price(raw)
    if prices.empty:
        raise RuntimeError("RQData未返回沪深300指数行情")
    prices["month"] = prices["date"].dt.to_period("M")
    monthly = prices.groupby("month", as_index=False).tail(1).copy()
    monthly["date"] = monthly["date"].dt.date
    monthly["value"] = monthly["close"].pct_change(12) * 100
    points = [
        {
            "date": row["date"].isoformat(),
            "value": round(float(row["value"]), 6),
        }
        for _, row in monthly.iterrows()
        if pd.notna(row["value"]) and row["date"].isoformat() >= MIN_DISPLAY_DATE
    ]
    return {
        "id": "hs300-yoy",
        "name": "沪深300",
        "unit": "%",
        "axis": "right",
        "frequency": "monthly",
        "source": "RQData",
        "code": HS300_INDEX,
        "points": points,
    }


def read_resident_deposit_points(market_path):
    if not market_path.exists():
        return []
    workbook = load_workbook(market_path, data_only=True, read_only=True)
    try:
        for worksheet in workbook.worksheets:
            for row in range(1, min(worksheet.max_row, 12) + 1):
                for column in range(1, worksheet.max_column + 1):
                    header = str(worksheet.cell(row, column).value or "").strip()
                    if "居民" not in header and "住户" not in header:
                        continue
                    if "存款" not in header:
                        continue
                    date_column = max(1, column - 1)
                    points = points_from_columns(worksheet, date_column, column)
                    if points:
                        return points
    finally:
        workbook.close()
    return []


def read_all_a_market_cap_to_deposits(market_path):
    rq.init()
    latest = rq.get_latest_trading_date()
    latest = latest.date() if hasattr(latest, "date") else latest
    completed_month = latest_completed_month(latest)
    start = "2015-01-01"
    raw = frame(
        rq.index_indicator(
            ALL_A_INDEX,
            start_date=start,
            end_date=completed_month,
            fields=["total_market_value"],
        )
    )
    if raw.empty or "total_market_value" not in raw.columns:
        return None
    dt_col = next(
        (name for name in ("trade_date", "date", "datetime", "trading_date") if name in raw.columns),
        None,
    )
    if dt_col is None:
        return None
    raw[dt_col] = pd.to_datetime(raw[dt_col])
    raw["total_market_value"] = pd.to_numeric(raw["total_market_value"], errors="coerce")
    raw = raw.dropna(subset=["total_market_value"]).sort_values(dt_col)
    raw["month"] = raw[dt_col].dt.to_period("M")
    monthly_cap = raw.groupby("month", as_index=False).tail(1).copy()
    deposit_points = read_resident_deposit_points(market_path)
    if not deposit_points:
        return {
            "id": "all-a-market-cap-to-household-deposits",
            "name": "全A总市值/居民部门存款余额",
            "unit": "倍",
            "axis": "left",
            "frequency": "monthly",
            "source": "RQData全A总市值；居民部门存款余额待接入",
            "points": [],
        }
    deposits = pd.DataFrame(deposit_points)
    deposits["date"] = pd.to_datetime(deposits["date"])
    deposits["month"] = deposits["date"].dt.to_period("M")
    deposits["deposit"] = pd.to_numeric(deposits["value"], errors="coerce")
    merged = monthly_cap.merge(
        deposits[["month", "deposit"]],
        on="month",
        how="inner",
    )
    if merged.empty:
        return None
    points = [
        {
            "date": row[dt_col].date().isoformat(),
            "value": round(float(row["total_market_value"]) / float(row["deposit"]), 6),
        }
        for _, row in merged.iterrows()
        if pd.notna(row["total_market_value"]) and pd.notna(row["deposit"]) and float(row["deposit"]) != 0
    ]
    return {
        "id": "all-a-market-cap-to-household-deposits",
        "name": "全A总市值/居民部门存款余额",
        "unit": "倍",
        "axis": "left",
        "frequency": "monthly",
        "source": "RQData全A总市值 / 本地居民部门存款余额",
        "points": points,
    }


def read_credit(path):
    workbook = load_workbook(path, data_only=True, read_only=True, keep_vba=False)
    try:
        worksheet = workbook["Sheet4"]
        ppi_header = str(worksheet.cell(2, 2).value or "").strip()
        pulse_header = str(worksheet.cell(2, 3).value or "").strip()
        if ppi_header != "中国:PPI:当月同比" or pulse_header != "信贷脉冲":
            raise RuntimeError("信贷脉冲 Sheet4 的A-C列口径与预期不一致")
        return [
            {
                "id": "credit-pulse",
                "name": pulse_header,
                "unit": "%",
                "axis": "left",
                "points": points_from_columns(worksheet, 1, 3, scale=100.0),
            },
            {
                "id": "china-ppi-yoy",
                "name": ppi_header,
                "unit": "%",
                "axis": "right",
                "points": points_from_columns(worksheet, 1, 2),
            },
        ]
    finally:
        workbook.close()


def read_fx(path):
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        worksheet = workbook["图表"]
        pulse_header = str(worksheet.cell(2, 11).value or "").strip()
        index_header = str(worksheet.cell(2, 12).value or "").strip()
        if not pulse_header or not index_header:
            raise RuntimeError("外汇脉冲“图表”工作表的K/L列缺少标题")
        return [
            {
                "id": "fx-pulse-leading-3m",
                "name": pulse_header,
                "unit": "点",
                "axis": "left",
                "points": points_from_columns(worksheet, 10, 11),
            },
        ]
    finally:
        workbook.close()


def refresh_excel_files(market_path, credit_path, fx_path):
    script = BASE_DIR / "refresh_excel_sources.ps1"
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-MarketWorkbook",
        str(market_path),
        "-CreditWorkbook",
        str(credit_path),
        "-FxWorkbook",
        str(fx_path),
    ]
    completed = subprocess.run(command, cwd=BASE_DIR, check=False)
    if completed.returncode:
        print("Excel/Wind自动刷新未完全成功；继续读取上一次已保存值。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(BASE_DIR / "macro-tracking.json"))
    parser.add_argument("--credit", default=str(DEFAULT_CREDIT))
    parser.add_argument("--fx", default=str(DEFAULT_FX))
    parser.add_argument("--market", default=str(DEFAULT_MARKET))
    parser.add_argument("--refresh-excel", action="store_true")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    credit_path = Path(args.credit).resolve()
    fx_path = Path(args.fx).resolve()
    market_path = Path(args.market).resolve()
    if args.refresh_excel:
        refresh_excel_files(market_path, credit_path, fx_path)

    series = read_credit(credit_path) + read_fx(fx_path) + [read_hs300_yoy()]
    cap_deposit = read_all_a_market_cap_to_deposits(market_path)
    if cap_deposit:
        series.append(cap_deposit)
    available_dates = [
        item["points"][-1]["date"]
        for item in series
        if item.get("points")
    ]
    notes = [
        "信贷脉冲按Excel百分比格式转换为百分数；PPI保留原始百分数。",
        "沪深300同比改由RQData读取000300.XSHG日收盘价，取每月最后一个交易日收盘价计算12个月同比。",
        "外汇脉冲沿用原表“领先3M”的月份标记，因此尾部可能出现领先月份。",
    ]
    if not cap_deposit or not cap_deposit.get("points"):
        notes.append("全A总市值/居民部门存款余额已预留左轴入口；当前本地工作簿未找到居民部门存款余额序列，待接入后自动显示。")

    payload = {
        "title": "宏观跟踪",
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "asOf": max(available_dates) if available_dates else None,
        "series": series,
        "sources": [
            {
                "name": "信贷脉冲",
                "path": str(credit_path),
                "modifiedAt": datetime.fromtimestamp(credit_path.stat().st_mtime).isoformat(timespec="seconds"),
            },
            {
                "name": "外汇脉冲",
                "path": str(fx_path),
                "modifiedAt": datetime.fromtimestamp(fx_path.stat().st_mtime).isoformat(timespec="seconds"),
            },
            {
                "name": "沪深300",
                "path": "RQData:000300.XSHG",
                "modifiedAt": datetime.now().isoformat(timespec="seconds"),
            },
            {
                "name": "全A总市值/居民部门存款余额",
                "path": "RQData:000985.XSHG / 本地居民部门存款余额",
                "modifiedAt": datetime.now().isoformat(timespec="seconds"),
            },
        ],
        "notes": notes,
    }
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"ok": True, "asOf": payload["asOf"], "series": len(series)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

