from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import date, datetime
from pathlib import Path

import pandas as pd
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
    latest=pd.Timestamp(latest_trading_date).date()
    calendar=json.loads((BASE_DIR/"data-freshness.json").read_text(encoding="utf-8"))["tradingCalendar"]
    sessions=[date.fromisoformat(d) for d in calendar if d[:7]==latest.strftime("%Y-%m")]
    if not sessions:raise ValueError("Verified month trading calendar missing")
    if latest==max(sessions):return latest
    return (pd.Timestamp(latest.replace(day=1))-pd.offsets.Day(1)).date()

def read_hs300_yoy():
    import akshare as ak
    from completed_session import completed_target
    from zoneinfo import ZoneInfo
    from akshare_request_policy import install
    install()
    calendar=json.loads((BASE_DIR/"data-freshness.json").read_text(encoding="utf-8"))["tradingCalendar"]
    latest=completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),calendar)
    completed_month=latest_completed_month(latest)
    saved=BASE_DIR/"macro-tracking.json"
    if saved.exists():
        old=json.loads(saved.read_text(encoding="utf-8"))
        prior=next((s for s in old.get("series",[]) if s.get("id")=="hs300-yoy"),{})
        last=max((p["date"] for p in prior.get("points",[])),default="")
        if "AKShare" in prior.get("source","") and last[:7]==completed_month.strftime("%Y-%m"):
            return prior
    history=(getattr(ak,"index_hist_csindex",None) or ak.stock_zh_index_hist_csindex)(
        symbol="000300",start_date="20150101",end_date=completed_month.strftime("%Y%m%d"))
    prices=history.rename(columns={"日期":"date","收盘":"close"})[["date","close"]].copy()
    prices["date"]=pd.to_datetime(prices["date"])
    prices["close"]=pd.to_numeric(prices["close"],errors="coerce")
    prices=prices.dropna().sort_values("date")
    if prices.empty or (completed_month-prices["date"].max().date()).days>10:
        raise ValueError("Incomplete completed-month CSI index history")
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
        "source": "AKShare / 中证指数官方日收盘价，月末收盘价同比",
        "code": "000300",
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
    # No compatible live public numerator/denominator pair is verified; retain dated history.
    path=BASE_DIR/"macro-tracking.json"
    if path.exists():
        old=json.loads(path.read_text(encoding="utf-8"))
        for item in old.get("series",[]):
            if item.get("id")=="all-a-market-cap-to-household-deposits":
                return {**item,"updateNote":"同口径市值与居民存款月度输入尚未齐，保留历史实际日期"}
    return None

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


def refresh_public_ppi(series):
    """Append same-definition monthly PPI only after overlap verification."""
    import re
    import akshare as ak
    from public_recovery import resolve
    from completed_session import completed_target
    from zoneinfo import ZoneInfo
    from akshare_request_policy import install
    install()
    calendar=json.loads((BASE_DIR/"data-freshness.json").read_text(encoding="utf-8"))["tradingCalendar"]
    target=completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),calendar)
    completed=latest_completed_month(target)
    path=BASE_DIR/"macro-tracking.json"
    saved=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    prior=next((s for s in saved.get("series",[]) if s.get("id")=="china-ppi-yoy"),{})
    item=next((s for s in series if s.get("id")=="china-ppi-yoy"),None)
    if item is None:return
    points={p["date"]:p for p in item.get("points",[])}
    points.update({p["date"]:p for p in prior.get("points",[])})
    item["points"]=[points[d] for d in sorted(points)]
    if max(points,default="")[:7]>=completed.strftime("%Y-%m"):
        if prior.get("source"):item["source"]=prior["source"]
        return
    try:
        frame=resolve(ak,"macro_china_ppi")()
        incoming={}
        for row in frame.to_dict("records"):
            match=re.search(r"(\d{4})\D*(\d{1,2})",str(row.get("月份","")))
            value=number(row.get("当月同比增长"))
            if not match or value is None:continue
            month=date(int(match[1]),int(match[2]),1)
            stamp=(pd.Timestamp(month)+pd.offsets.MonthEnd(0)).date()
            if stamp<=completed:incoming[stamp.isoformat()]=value
        shared=sorted(set(incoming)&set(points))[-6:]
        error=max((abs(incoming[d]-points[d]["value"]) for d in shared),default=float("inf"))
        if len(shared)<3 or error>0.001:raise ValueError("PPI definition overlap failed")
        last=max(points,default="")
        points.update({d:{"date":d,"value":v} for d,v in incoming.items() if d>last})
        item.update(points=[points[d] for d in sorted(points)],source="AKShare / 中国工业品出厂价格指数当月同比；原历史保留")
        print("Public PPI",max(points),"overlap",len(shared),"error",error,flush=True)
    except Exception as exc:
        print("Public PPI retained dated history:",type(exc).__name__,flush=True)

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
    refresh_public_ppi(series)
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
        "沪深300同比使用AKShare中证指数000300日收盘价，取完整月份最后一个交易日收盘价计算12个月同比。",
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
                "path": "AKShare中证指数:000300",
                "modifiedAt": datetime.now().isoformat(timespec="seconds"),
            },
            {
                "name": "全A总市值/居民部门存款余额",
                "path": "历史市值/存款比例缓存；未新增未验证月度数据",
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

