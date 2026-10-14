from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path

from breadth_phase import apply_optimized_phases
from market_data_sync import apply_market_data_sync


BASE_DIR = Path(__file__).resolve().parent
ONEDRIVE_EXCEL = Path.home() / "OneDrive" / "文档" / "市场情绪指标.xlsx"
LOCAL_EXCEL = BASE_DIR / "excel-source.xlsx"
BROAD_MARKET_ONEDRIVE_EXCEL = (
    Path.home() / "OneDrive" / "文档" / "市场宽基情绪指标.xlsx"
)
BROAD_MARKET_LOCAL_EXCEL = BASE_DIR / "broad-market-excel-source.xlsx"
OPEN_FUND_LOCAL_EXCEL = BASE_DIR / "open-fund-stock-position.xlsx"
OPEN_FUND_WIND_DIR = Path(r"C:\Wind\Wind.NET.Client\WindNET\tmp")
OPEN_FUND_PREFERRED_NAME = "开放式基金估算股票投资比例20260729(3).xlsx"
OPEN_FUND_HISTORY_CACHE = BASE_DIR / "rqdata-fund-stock-position-history.json"
RQDATA_CACHE = BASE_DIR / "rqdata-broad-sentiment.json"
RQDATA_SCRIPT = BASE_DIR / "rqdata_refresh.py"
RQDATA_BREADTH_CACHE = BASE_DIR / "rqdata-breadth-sentiment.json"
PAYLOAD_CACHE = BASE_DIR / "broad-sentiment-page-cache.json"
RQDATA_PYTHON = Path(os.environ.get("RQDATA_PYTHON", r"C:\Users\DELL\anaconda3\envs\rqsdk\python.exe"))
RQDATA_REFRESH_SECONDS = int(os.environ.get("RQDATA_REFRESH_SECONDS", "1800"))
RQDATA_REFRESH_TIMEOUT = int(os.environ.get("RQDATA_REFRESH_TIMEOUT", "45"))
ENABLE_RQDATA_REFRESH = os.environ.get("ENABLE_RQDATA_REFRESH", "0") == "1"
NODE_EXE = Path(
    os.environ.get(
        "NODE_EXE",
        r"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe",
    )
)
PAYLOAD_BUILD_LOCK = threading.Lock()


def source_signature():
    try:
        open_fund_source = resolve_open_fund_position_excel()
    except Exception:
        open_fund_source = OPEN_FUND_LOCAL_EXCEL
    paths = [
        LOCAL_EXCEL,
        ONEDRIVE_EXCEL,
        BROAD_MARKET_LOCAL_EXCEL,
        BROAD_MARKET_ONEDRIVE_EXCEL,
        open_fund_source,
        OPEN_FUND_HISTORY_CACHE,
        RQDATA_CACHE,
        RQDATA_BREADTH_CACHE,
        BASE_DIR / "rqdata-options-pcr.json",
    ]
    signature = [["pageCacheVersion", 55, "perSeriesFreshnessAndDailyPCR"]]
    for path in paths:
        try:
            stat = path.stat()
            signature.append([str(path), stat.st_size, stat.st_mtime_ns])
        except OSError:
            signature.append([str(path), None, None])
    return signature


def load_page_cache(signature):
    try:
        cached = json.loads(PAYLOAD_CACHE.read_text(encoding="utf-8"))
        if cached.get("sourceSignature") == signature and isinstance(cached.get("payload"), dict):
            return cached["payload"]
    except Exception:
        pass
    return None


def load_stale_page_cache(signature=None):
    """Return the last complete page payload even when source files changed."""
    try:
        cached = json.loads(PAYLOAD_CACHE.read_text(encoding="utf-8"))
        if signature is not None and cached.get("sourceSignature", [None])[0] != signature[0]:
            return None
        payload = cached.get("payload")
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def save_page_cache(payload):
    try:
        temporary = PAYLOAD_CACHE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"sourceSignature": source_signature(), "payload": payload},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(PAYLOAD_CACHE)
    except OSError:
        pass


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    try:
        text = str(value).replace(",", "").replace("%", "").strip()
        if not text or text.startswith("#"):
            return None
        number = float(text)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def five_year_start(value):
    """Return the same calendar date five years earlier, leap-day safe."""
    try:
        current = datetime.fromisoformat(str(value)[:10]).date()
    except (TypeError, ValueError):
        return None
    try:
        return current.replace(year=current.year - 5).isoformat()
    except ValueError:
        return current.replace(year=current.year - 5, day=28).isoformat()


def clean(value, digits=4):
    number = numeric(value)
    if number is None:
        return None
    return round(number, digits)


def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            from openpyxl.utils.datetime import from_excel

            converted = from_excel(value)
            return converted.date() if isinstance(converted, datetime) else converted
        except Exception:
            return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def percentile(values, current):
    current = numeric(current)
    nums = sorted(numeric(value) for value in values if numeric(value) is not None)
    if current is None or not nums:
        return None
    if len(nums) == 1:
        return 50.0
    below = sum(1 for value in nums if value < current)
    equal = sum(1 for value in nums if value == current)
    rank = below + max(equal - 1, 0) / 2
    return round(rank / (len(nums) - 1) * 100, 1)


def resolve_excel():
    configured = os.environ.get("MARKET_SENTIMENT_EXCEL")
    if configured:
        candidates = [Path(configured), LOCAL_EXCEL]
    else:
        # Keep the website independent from OneDrive locks: refresh the local
        # snapshot when possible, then always read the snapshot.
        try:
            if ONEDRIVE_EXCEL.exists() and (
                not LOCAL_EXCEL.exists() or ONEDRIVE_EXCEL.stat().st_mtime > LOCAL_EXCEL.stat().st_mtime
            ):
                shutil.copy2(ONEDRIVE_EXCEL, LOCAL_EXCEL)
        except (OSError, PermissionError):
            pass
        candidates = [LOCAL_EXCEL, ONEDRIVE_EXCEL]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise FileNotFoundError("未找到市场情绪指标.xlsx 或网站本地副本")


def resolve_broad_market_excel():
    configured = os.environ.get("BROAD_MARKET_SENTIMENT_EXCEL")
    source = Path(configured) if configured else BROAD_MARKET_ONEDRIVE_EXCEL
    refresh_needed = source.exists() and (
        not BROAD_MARKET_LOCAL_EXCEL.exists()
        or source.stat().st_mtime > BROAD_MARKET_LOCAL_EXCEL.stat().st_mtime
    )
    try:
        if refresh_needed:
            shutil.copy2(source, BROAD_MARKET_LOCAL_EXCEL)
    except (OSError, PermissionError):
        snapshot_script = BASE_DIR / "copy_locked_excel.mjs"
        temporary = BROAD_MARKET_LOCAL_EXCEL.with_name(
            "broad-market-excel-source.tmp.xlsx"
        )
        try:
            if temporary.exists():
                temporary.unlink()
            subprocess.run(
                [
                    str(NODE_EXE),
                    str(snapshot_script),
                    str(source),
                    str(temporary),
                ],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            temporary.replace(BROAD_MARKET_LOCAL_EXCEL)
        except Exception:
            pass
    for candidate in (BROAD_MARKET_LOCAL_EXCEL, source):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("未找到市场宽基情绪指标.xlsx 或网站本地副本")


def margin_risk_excel_snapshot():
    """Read market-level margin risk and participation data from BL/BM/BP/BR."""
    from openpyxl import load_workbook

    path = resolve_broad_market_excel()
    workbook = load_workbook(path, data_only=True, read_only=True)
    worksheet = workbook.worksheets[0]
    try:
        rows = read_series(
            worksheet,
            63,
            {
                "guaranteeRatio": 64,
                "investorCount": 65,
                "marginClientCount": 68,
                "tradingInvestorCount": 70,
            },
            start_row=3,
            end_row=worksheet.max_row,
        )
    finally:
        workbook.close()

    rows = [
        item
        for item in rows
        if numeric(item.get("guaranteeRatio")) is not None
        or numeric(item.get("investorCount")) is not None
        or numeric(item.get("marginClientCount")) is not None
        or numeric(item.get("tradingInvestorCount")) is not None
    ]
    if not rows:
        return None
    return {
        "series": [
            {
                "id": "margin-guarantee-ratio",
                "name": "中国:融资融券:市场平均担保比例",
                "unit": "%",
                "points": [
                    {
                        "date": item["date"].isoformat(),
                        "value": clean(item.get("guaranteeRatio"), 3),
                    }
                    for item in rows[-1900:]
                    if numeric(item.get("guaranteeRatio")) is not None
                    and numeric(item.get("guaranteeRatio")) > 0
                ],
            },
            {
                "id": "margin-investor-count",
                "name": "中国:有融资融券负债的投资者数量",
                "unit": "户",
                "points": [
                    {
                        "date": item["date"].isoformat(),
                        "value": clean(item.get("investorCount"), 0),
                    }
                    for item in rows[-1900:]
                    if numeric(item.get("investorCount")) is not None
                    and numeric(item.get("investorCount")) > 0
                ],
            },
            {
                "id": "margin-investor-participation-ratio",
                "name": "参与两融的投资者占比",
                "unit": "%",
                "points": [
                    {
                        "date": item["date"].isoformat(),
                        "value": clean(
                            float(numeric(item.get("tradingInvestorCount")))
                            / float(numeric(item.get("marginClientCount")))
                            * 100,
                            3,
                        ),
                    }
                    for item in rows[-1900:]
                    if numeric(item.get("tradingInvestorCount")) is not None
                    and numeric(item.get("tradingInvestorCount")) > 0
                    and numeric(item.get("marginClientCount")) is not None
                    and numeric(item.get("marginClientCount")) > 0
                ],
            },
        ]
    }


def derivatives_pcr_snapshot():
    from openpyxl import load_workbook

    path = resolve_broad_market_excel()
    workbook = load_workbook(path, data_only=True, read_only=True)
    worksheet = workbook["综合日频数据源"]
    definitions = (
        ("sz50", "上证50", ("510050.SH", "510050.XSHG", "000016.SH", "上证50")),
        ("hs300", "沪深300", ("510300.SH", "510300.XSHG", "000300.SH", "沪深300")),
        ("csi1000", "中证1000", ("512100.SH", "512100.XSHG", "159845.SZ", "159845.XSHE", "000852.SH", "中证1000")),
        ("star50", "科创50", ("588000.SH", "588000.XSHG", "000688.SH", "科创50")),
    )
    values_by_index = {
        identifier: {"name": name, "markers": markers, "oi": [], "amount": [], "volume": []}
        for identifier, name, markers in definitions
    }

    def moving_average(points, window=3):
        ordered = sorted(points, key=lambda point: point["date"])
        result = []
        for index in range(window - 1, len(ordered)):
            values = [
                numeric(point.get("value"))
                for point in ordered[index - window + 1:index + 1]
            ]
            if any(value is None for value in values):
                continue
            result.append(
                {
                    "date": ordered[index]["date"],
                    "value": clean(sum(values) / window, 4),
                }
            )
        return result
    pcr_blocks = []
    for oi_col in range(1, worksheet.max_column - 1):
        oi_header = str(worksheet.cell(5, oi_col).value or "")
        amount_header = str(worksheet.cell(5, oi_col + 1).value or "")
        volume_header = str(worksheet.cell(5, oi_col + 2).value or "")
        if (
            "持仓量认沽认购比率" in oi_header
            and "成交额认沽认购比率" in amount_header
            and "成交量认沽认购比率" in volume_header
        ):
            pcr_blocks.append((oi_col - 1, oi_col, oi_col + 1, oi_col + 2))
    available_blocks = []
    for date_col, oi_col, amount_col, volume_col in pcr_blocks:
        block_text = " ".join(
            str(worksheet.cell(row, col).value or "")
            for row in range(3, 7)
            for col in (date_col, oi_col, amount_col, volume_col)
        ).upper()
        available_blocks.append((block_text, date_col, oi_col, amount_col, volume_col))
    for identifier, item in values_by_index.items():
        block = next(
            (
                block
                for block in available_blocks
                if any(marker.upper() in block[0] for marker in item["markers"])
            ),
            None,
        )
        if block is None:
            continue
        _, date_col, oi_col, amount_col, volume_col = block
        rows = read_series(
            worksheet,
            date_col,
            {"oi": oi_col, "amount": amount_col, "volume": volume_col},
            start_row=6,
            end_row=worksheet.max_row,
        )
        for row in rows:
            for metric in ("oi", "amount", "volume"):
                value = numeric(row.get(metric))
                if value is not None and value >= 0:
                    item[metric].append(
                        {"date": row["date"].isoformat(), "value": float(value)}
                    )
    workbook.close()

    series = []
    metric_names = {
        "oi": "持仓量认沽认购比率",
        "amount": "成交额认沽认购比率",
        "volume": "成交量认沽认购比率",
    }
    latest_dates = []
    for identifier, item in values_by_index.items():
        for metric, metric_name in metric_names.items():
            raw_points = sorted(item[metric], key=lambda point: point["date"])
            if not raw_points:
                continue
            points = [
                {"date": point["date"], "value": clean(point["value"], 4)}
                for point in raw_points[-1260:]
            ]
            latest_dates.append(points[-1]["date"])
            series.append(
                {
                    "id": f"pcr-{metric}-{identifier}",
                    "name": f"{item['name']}{metric_name}",
                    "unit": "倍",
                    "points": points,
                }
            )
            if metric == "oi":
                ma3_points = moving_average(points)
                if ma3_points:
                    series.append(
                        {
                            "id": f"pcr-{metric}-ma3-{identifier}",
                            "name": f"{item['name']}{metric_name}3日移动平均",
                            "unit": "倍",
                            "points": ma3_points,
                        }
                    )
        amount_by_date = {
            point["date"]: numeric(point["value"])
            for point in item["amount"]
            if numeric(point.get("value")) is not None
        }
        volume_by_date = {
            point["date"]: numeric(point["value"])
            for point in item["volume"]
            if numeric(point.get("value")) not in (None, 0)
        }
        ratio_points = [
            {
                "date": dt,
                "value": clean(amount_by_date[dt] / volume_by_date[dt], 4),
            }
            for dt in sorted(set(amount_by_date) & set(volume_by_date))
        ][-1260:]
        if ratio_points:
            latest_dates.append(ratio_points[-1]["date"])
            series.append(
                {
                    "id": f"pcr-amount-volume-{identifier}",
                    "name": f"{item['name']}成交额PCR/成交量PCR",
                    "unit": "倍",
                    "points": ratio_points,
                }
            )
            ratio_ma3_points = moving_average(ratio_points)
            if ratio_ma3_points:
                positive_ratio_ma3_points = [
                    {
                        "date": point["date"],
                        "value": clean(1 / point["value"], 4),
                    }
                    for point in ratio_ma3_points
                    if numeric(point.get("value")) not in (None, 0)
                ]
                series.append(
                    {
                        "id": f"pcr-amount-volume-ma3-{identifier}",
                        "name": f"{item['name']}成交额PCR/成交量PCR MA3（倒数正向化）",
                        "unit": "倍",
                        "points": positive_ratio_ma3_points,
                    }
                )
    if not series:
        raise RuntimeError("Excel 中没有可用的期权PCR历史序列")
    return {
        "path": str(path),
        "asOf": max(latest_dates) if latest_dates else None,
        "series": series,
    }


def broad_market_new_equity_fund_shares_snapshot():
    from openpyxl import load_workbook

    path = resolve_broad_market_excel()
    workbook = load_workbook(path, data_only=True, read_only=True)
    worksheet = workbook["综合日频数据源"]
    target_header = "中国:新成立基金份额:偏股型"
    shares_col = None
    for col in range(1, worksheet.max_column + 1):
        labels = [
            str(worksheet.cell(row, col).value or "").strip()
            for row in range(1, 7)
        ]
        if any(target_header in label for label in labels):
            shares_col = col
            break
    if shares_col is None:
        workbook.close()
        raise RuntimeError(f"市场宽基情绪指标.xlsx 中未找到“{target_header}”")

    date_col = shares_col - 1
    while date_col > 0 and as_date(worksheet.cell(6, date_col).value) is None:
        date_col -= 1
    if date_col <= 0:
        workbook.close()
        raise RuntimeError(f"市场宽基情绪指标.xlsx 中未找到“{target_header}”对应日期列")

    rows = read_series(
        worksheet,
        date_col,
        {"shares": shares_col},
        start_row=6,
        end_row=worksheet.max_row,
    )
    workbook.close()

    fund_rows = [item for item in rows if numeric(item.get("shares")) is not None]
    latest = fund_rows[-1] if fund_rows else {}
    values = [item["shares"] for item in fund_rows]
    shares_5d = sum(values[-5:]) if values else None
    shares_20d = sum(values[-20:]) if values else None
    rolling_20d = [
        sum(values[index - 19:index + 1])
        for index in range(19, len(values))
    ]
    shares_20d_percentile = percentile(rolling_20d, shares_20d)
    points = [
        {
            "date": item["date"].isoformat(),
            "value": clean(item.get("shares"), 3),
        }
        for item in fund_rows[-1900:]
    ]
    return {
        "path": str(path),
        "asOf": latest.get("date").isoformat() if latest.get("date") else None,
        "shares": clean(latest.get("shares"), 3),
        "shares5D": clean(shares_5d, 3),
        "shares20D": clean(shares_20d, 3),
        "shares20DPercentile": clean(shares_20d_percentile, 1),
        "series": [
            {
                "id": "new-equity-fund-shares",
                "name": "新成立偏股型基金份额",
                "unit": "亿份",
                "points": points,
            }
        ] if points else [],
    }


def broad_market_medium_term_sentiment_snapshot():
    from openpyxl import load_workbook

    path = resolve_broad_market_excel()
    workbook = load_workbook(path, data_only=True, read_only=True)
    worksheet = workbook["综合日频数据源"]

    def date_col_for(value_col):
        for col in range(value_col - 1, max(0, value_col - 8), -1):
            labels = [
                str(worksheet.cell(row, col).value or "").strip().lower()
                for row in range(1, 7)
            ]
            if any(label in ("date", "日期") for label in labels):
                return col, 7
        for col in range(value_col - 1, max(0, value_col - 8), -1):
            for row in range(1, 8):
                if as_date(worksheet.cell(row, col).value) is not None:
                    return col, row
        return None, None

    def series_by_header(target, value_name="value"):
        value_col = None
        for col in range(1, worksheet.max_column + 1):
            labels = [
                str(worksheet.cell(row, col).value or "").strip()
                for row in range(1, 7)
            ]
            if any(target in label for label in labels):
                value_col = col
                break
        if value_col is None:
            return []
        date_col, start_row = date_col_for(value_col)
        if date_col is None:
            return []
        return read_series(
            worksheet,
            date_col,
            {value_name: value_col},
            start_row=start_row,
            end_row=worksheet.max_row,
        )

    def series_by_code_field(code, field_markers, value_name="value"):
        markers = tuple(marker.lower() for marker in field_markers)
        for col in range(1, worksheet.max_column + 1):
            labels = [
                str(worksheet.cell(row, col).value or "").strip()
                for row in range(1, 7)
            ]
            label_text = " ".join(labels).lower()
            if not any(label.upper() == code.upper() for label in labels):
                continue
            if not any(marker in label_text for marker in markers):
                continue
            date_col, start_row = date_col_for(col)
            if date_col is None:
                continue
            return read_series(
                worksheet,
                date_col,
                {value_name: col},
                start_row=start_row,
                end_row=worksheet.max_row,
            )
        return []

    def cdb_10y_from_cf_column():
        date_col = 83
        value_col = 84
        labels = [
            str(worksheet.cell(row, value_col).value or "").strip()
            for row in range(1, 7)
        ]
        if not any("中国:国开债到期收益率:10年" in label for label in labels):
            return []
        return read_series(
            worksheet,
            date_col,
            {"bondYield": value_col},
            start_row=3,
            end_row=worksheet.max_row,
        )

    pe_rows = series_by_code_field("881001.WI", ("pe_ttm", "市盈率PE(TTM)", "市盈率"), "peTtm")
    dividend_rows = series_by_code_field(
        "881001.WI",
        ("val_dividendyield3", "股息率ttm", "股息率TTM"),
        "dividend",
    )
    bond_rows = cdb_10y_from_cf_column()
    wind_all_rows = series_by_code_field("881001.WI", ("close", "收盘价"), "close")
    bond_fund_rows = series_by_code_field("885003.WI", ("close", "收盘价"), "close")
    financing_rows = series_by_header("中国:融资余额", "balance")
    workbook.close()

    def points(rows, key, digits=4, unit_transform=None, positive_only=False):
        output = []
        for item in rows:
            value = numeric(item.get(key))
            if value is None:
                continue
            if unit_transform:
                value = unit_transform(value)
            if positive_only and value <= 0:
                continue
            output.append({"date": item["date"].isoformat(), "value": clean(value, digits)})
        return output[-1900:]

    def yield_percent(value):
        # Wind percent-style fields usually arrive as 1.7/2.4; decimal curves arrive as 0.017.
        return value * 100 if abs(value) < 1 else value

    dividend_points = points(dividend_rows, "dividend", positive_only=True)
    bond_points = points(bond_rows, "bondYield", unit_transform=yield_percent, positive_only=True)
    financing_points = points(financing_rows, "balance", digits=3, positive_only=True)

    pe_points = points(pe_rows, "peTtm", positive_only=True)
    pe_by_date = {point["date"]: numeric(point["value"]) for point in pe_points}
    bond_by_date = {point["date"]: numeric(point["value"]) for point in bond_points}
    erp_points = [
        {
            "date": dt,
            "value": clean(100 / pe_by_date[dt] - bond_by_date[dt], 4),
        }
        for dt in sorted(set(pe_by_date) & set(bond_by_date))
        if pe_by_date[dt] is not None
        and pe_by_date[dt] > 0
        and bond_by_date[dt] is not None
    ][-1900:]

    dividend_by_date = {point["date"]: numeric(point["value"]) for point in dividend_points}
    spread_points = [
        {
            "date": dt,
            "value": clean(dividend_by_date[dt] - bond_by_date[dt], 4),
        }
        for dt in sorted(set(dividend_by_date) & set(bond_by_date))
        if dividend_by_date[dt] is not None and bond_by_date[dt] is not None
    ][-1900:]

    wind_all_by_date = {
        item["date"].isoformat(): numeric(item.get("close"))
        for item in wind_all_rows
        if numeric(item.get("close")) is not None
    }
    bond_fund_by_date = {
        item["date"].isoformat(): numeric(item.get("close"))
        for item in bond_fund_rows
        if numeric(item.get("close")) is not None
    }
    position_points = []
    for dt in sorted(set(wind_all_by_date) & set(bond_fund_by_date)):
        wind_value = numeric(wind_all_by_date.get(dt))
        bond_fund_value = numeric(bond_fund_by_date.get(dt))
        if wind_value is None or bond_fund_value in (None, 0):
            continue
        position_points.append(
            {
                "date": dt,
                "value": clean(wind_value / bond_fund_value, 4),
            }
        )
    position_points = position_points[-1900:]

    rqdata = load_rqdata_cache() or {}

    def cache_series_points(payload, series_id, digits=4):
        for series_item in payload.get("series", []) if isinstance(payload, dict) else []:
            if series_item.get("id") != series_id:
                continue
            return [
                {"date": str(item.get("date"))[:10], "value": clean(item.get("value"), digits)}
                for item in series_item.get("points", [])
                if item.get("date") and numeric(item.get("value")) is not None
            ][-1900:]
        return []

    rq_financing_points = cache_series_points(rqdata, "financing-balance", digits=3)
    rq_financing_by_date = {
        str(item.get("date"))[:10]: numeric(item.get("value"))
        for item in rq_financing_points
        if item.get("date") and numeric(item.get("value")) is not None
    }
    excel_financing_by_date = {
        point["date"]: numeric(point["value"])
        for point in financing_points
        if numeric(point.get("value")) is not None
    }
    financing_by_date = {**excel_financing_by_date, **rq_financing_by_date}
    financing_points = [
        {"date": dt, "value": clean(value, 3)}
        for dt, value in sorted(financing_by_date.items())
        if numeric(value) is not None and numeric(value) > 0
    ][-1900:]
    financing_activity_points = cache_series_points(rqdata, "financing-activity", digits=4)
    financing_net_points = cache_series_points(rqdata, "financing-net", digits=3)
    breadth_cache = load_rqdata_breadth_cache() or {}
    breadth60_confirmation_points = cache_series_points(
        breadth_cache,
        "rqdata-breadth60-confirmation",
        digits=3,
    )

    def rolling_average_points(raw_points, window=750, min_periods=120):
        ordered = [
            point for point in sorted(raw_points, key=lambda item: item["date"])
            if numeric(point.get("value")) is not None
        ]
        output = []
        for index, point in enumerate(ordered):
            history = [
                numeric(item["value"])
                for item in ordered[max(0, index - window + 1):index + 1]
                if numeric(item.get("value")) is not None
            ]
            if len(history) < min_periods:
                continue
            output.append(
                {
                    "date": point["date"],
                    "value": clean(sum(history) / len(history), 4),
                }
            )
        return output

    def clamp_score(value):
        return max(0, min(100, value))

    def quantile(values, ratio):
        ordered = sorted(value for value in values if numeric(value) is not None)
        if not ordered:
            return None
        position = (len(ordered) - 1) * ratio
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    def stdev(values):
        nums = [numeric(value) for value in values if numeric(value) is not None]
        if len(nums) < 2:
            return None
        mean = sum(nums) / len(nums)
        return math.sqrt(sum((value - mean) ** 2 for value in nums) / len(nums))

    def rolling_band_percent_points(raw_points, inverse=False, window=750, min_periods=120):
        ordered = [
            point for point in sorted(raw_points, key=lambda item: item["date"])
            if numeric(point.get("value")) is not None
        ]
        output = []
        for index, point in enumerate(ordered):
            history = [
                numeric(item["value"])
                for item in ordered[max(0, index - window + 1):index + 1]
                if numeric(item.get("value")) is not None
            ]
            if len(history) < min_periods:
                continue
            mean = sum(history) / len(history)
            sigma = stdev(history)
            current = numeric(point.get("value"))
            if current is None or sigma in (None, 0):
                continue
            lower = mean - sigma * 2
            upper = mean + sigma * 2
            score = clamp_score((current - lower) / (upper - lower) * 100)
            if inverse:
                score = 100 - score
            output.append(
                {
                    "date": point["date"],
                    "value": clean(score, 3),
                }
            )
        return output

    def rolling_quantile_normalize(raw_points, window=750, min_periods=120):
        ordered = [
            point for point in sorted(raw_points, key=lambda item: item["date"])
            if numeric(point.get("value")) is not None
        ]
        output = []
        for index, point in enumerate(ordered):
            history = [
                numeric(item["value"])
                for item in ordered[max(0, index - window + 1):index + 1]
                if numeric(item.get("value")) is not None
            ]
            if len(history) < min_periods:
                continue
            low = quantile(history, 0.05)
            high = quantile(history, 0.95)
            current = numeric(point.get("value"))
            if current is None or low is None or high is None:
                continue
            score = 50.0 if high == low else clamp_score((current - low) / (high - low) * 100)
            output.append({"date": point["date"], "value": clean(score, 3)})
        return output

    def rolling_percentile_score_points(raw_points, inverse=False, window=750, min_periods=120):
        ordered = [
            point for point in sorted(raw_points, key=lambda item: item["date"])
            if numeric(point.get("value")) is not None
        ]
        output = []
        for index, point in enumerate(ordered):
            history = [
                numeric(item["value"])
                for item in ordered[max(0, index - window + 1):index + 1]
                if numeric(item.get("value")) is not None
            ]
            if len(history) < min_periods:
                continue
            score = percentile(history, point.get("value"))
            if score is None:
                continue
            output.append(
                {
                    "date": point["date"],
                    "value": clean(100 - score if inverse else score, 3),
                }
            )
        return output

    def relative_return_points(primary_by_date, benchmark_by_date, window=120):
        ordered_dates = sorted(set(primary_by_date) & set(benchmark_by_date))
        output = []
        for index, dt in enumerate(ordered_dates):
            if index < window:
                continue
            start_dt = ordered_dates[index - window]
            primary_now = numeric(primary_by_date.get(dt))
            primary_start = numeric(primary_by_date.get(start_dt))
            benchmark_now = numeric(benchmark_by_date.get(dt))
            benchmark_start = numeric(benchmark_by_date.get(start_dt))
            if (
                primary_now is None
                or primary_start in (None, 0)
                or benchmark_now is None
                or benchmark_start in (None, 0)
            ):
                continue
            value = (primary_now / primary_start - benchmark_now / benchmark_start) * 100
            output.append({"date": dt, "value": clean(value, 4)})
        return output[-1900:]

    def change_percent_points(raw_points, window=60):
        ordered = [
            point for point in sorted(raw_points, key=lambda item: item["date"])
            if numeric(point.get("value")) is not None
        ]
        output = []
        for index, point in enumerate(ordered):
            if index < window:
                continue
            previous = numeric(ordered[index - window].get("value"))
            current = numeric(point.get("value"))
            if previous in (None, 0) or current is None:
                continue
            output.append(
                {
                    "date": point["date"],
                    "value": clean((current / previous - 1) * 100, 4),
                }
            )
        return output[-1900:]

    def trailing_sum_points(raw_points, window=20, min_periods=5):
        ordered = [
            point for point in sorted(raw_points, key=lambda item: item["date"])
            if numeric(point.get("value")) is not None
        ]
        output = []
        values = deque()
        running = 0.0
        for point in ordered:
            value = numeric(point.get("value"))
            values.append(value)
            running += value
            if len(values) > window:
                running -= values.popleft()
            if len(values) >= min_periods:
                output.append({"date": point["date"], "value": clean(running, 4)})
        return output[-1900:]

    erp_rolling_points = rolling_average_points(erp_points)
    spread_rolling_points = rolling_average_points(spread_points)
    financing_rolling_points = rolling_average_points(financing_points)
    erp_band_points = rolling_band_percent_points(erp_points, inverse=True)
    spread_band_points = rolling_band_percent_points(spread_points, inverse=True)
    financing_band_points = rolling_band_percent_points(financing_points)
    relative_strength_points = relative_return_points(wind_all_by_date, bond_fund_by_date)
    financing_balance_change_points = change_percent_points(financing_points, window=60)
    financing_net_20d_points = trailing_sum_points(financing_net_points, window=20)
    component_scores = {
        "erp": rolling_quantile_normalize(erp_band_points),
        "spread": rolling_percentile_score_points(spread_points, inverse=True),
        "position": rolling_percentile_score_points(position_points),
        "financingActivity": rolling_quantile_normalize(trailing_mean_points(financing_activity_points, 5)),
        "financingNet20D": rolling_quantile_normalize(financing_net_20d_points),
        "financingBalanceChange60D": rolling_quantile_normalize(financing_balance_change_points),
        "breadth60": breadth60_confirmation_points,
    }
    score_maps = {
        key: {point["date"]: numeric(point["value"]) for point in values}
        for key, values in component_scores.items()
    }
    raw_maps = {
        "erp": {point["date"]: numeric(point["value"]) for point in erp_points},
        "erpRolling": {point["date"]: numeric(point["value"]) for point in erp_rolling_points},
        "position": {point["date"]: numeric(point["value"]) for point in position_points},
        "relativeStrength": {point["date"]: numeric(point["value"]) for point in relative_strength_points},
        "spread": {point["date"]: numeric(point["value"]) for point in spread_points},
        "spreadRolling": {point["date"]: numeric(point["value"]) for point in spread_rolling_points},
        "financing": {point["date"]: numeric(point["value"]) for point in financing_points},
        "financingRolling": {point["date"]: numeric(point["value"]) for point in financing_rolling_points},
        "financingActivity": {point["date"]: numeric(point["value"]) for point in financing_activity_points},
        "financingNet20D": {point["date"]: numeric(point["value"]) for point in financing_net_20d_points},
        "financingBalanceChange60D": {
            point["date"]: numeric(point["value"])
            for point in financing_balance_change_points
        },
        "breadth60": {point["date"]: numeric(point["value"]) for point in breadth60_confirmation_points},
        "dividend": dividend_by_date,
        "bondYield": bond_by_date,
    }
    shared_dates = sorted(set.intersection(*(set(values) for values in score_maps.values())))
    composite_points = [
        {
            "date": dt,
            "value": clean(sum(score_maps[key][dt] for key in score_maps) / len(score_maps), 3),
            "components": {
                "erp": clean(score_maps["erp"][dt], 3),
                "spread": clean(score_maps["spread"][dt], 3),
                "position": clean(score_maps["position"][dt], 3),
                "financingActivity": clean(score_maps["financingActivity"][dt], 3),
                "financingNet20D": clean(score_maps["financingNet20D"][dt], 3),
                "financingBalanceChange60D": clean(score_maps["financingBalanceChange60D"][dt], 3),
                "breadth60": clean(score_maps["breadth60"][dt], 3),
            },
            "metrics": {
                "erp": clean(raw_maps["erp"].get(dt), 4),
                "erpRolling3Y": clean(raw_maps["erpRolling"].get(dt), 4),
                "equityBondPosition": clean(raw_maps["position"].get(dt), 4),
                "equityBondRelativeReturn120D": clean(raw_maps["relativeStrength"].get(dt), 4),
                "equityBondYieldSpread": clean(raw_maps["spread"].get(dt), 4),
                "equityBondYieldSpreadRolling3Y": clean(raw_maps["spreadRolling"].get(dt), 4),
                "financingBalance": clean(raw_maps["financing"].get(dt), 3),
                "financingBalanceRolling3Y": clean(raw_maps["financingRolling"].get(dt), 3),
                "financingActivity": clean(raw_maps["financingActivity"].get(dt), 4),
                "financingNet20D": clean(raw_maps["financingNet20D"].get(dt), 3),
                "financingBalanceChange60D": clean(raw_maps["financingBalanceChange60D"].get(dt), 4),
                "breadth60Confirmation": clean(raw_maps["breadth60"].get(dt), 3),
                "dividendYieldTtm": clean(raw_maps["dividend"].get(dt), 4),
                "cdb10yYield": clean(raw_maps["bondYield"].get(dt), 4),
            },
        }
        for dt in shared_dates
    ][-1900:]
    if not composite_points:
        missing = []
        if not erp_points:
            missing.append("万得全A PE或10年国开债收益率")
        if not spread_points:
            missing.append("万得全A股息率TTM或10年国开债收益率")
        if not position_points:
            missing.append("万得全A或偏债混合型基金指数")
        if not financing_points or not financing_activity_points or not financing_net_points:
            missing.append("融资余额、融资活跃度或融资净流入")
        if not breadth60_confirmation_points:
            missing.append("RQData 60日市场广度")
        raise RuntimeError("、".join(missing) or "中期情绪有效样本不足")

    latest = composite_points[-1]
    return {
        "path": str(path),
        "asOf": latest["date"],
        "score": latest["value"],
        "components": latest["components"],
        "metrics": latest["metrics"],
        "series": [
            {
                "id": "medium-term-sentiment",
                "name": "中期情绪指标",
                "unit": "分",
                "points": [{"date": item["date"], "value": item["value"]} for item in composite_points],
            },
            {"id": "medium-erp-score", "name": "ERP情绪分", "unit": "分", "points": component_scores["erp"][-1900:]},
            {"id": "medium-yield-spread-score", "name": "股债收益差情绪分", "unit": "分", "points": component_scores["spread"][-1900:]},
            {"id": "medium-position-score", "name": "股债位置差情绪分", "unit": "分", "points": component_scores["position"][-1900:]},
            {"id": "medium-financing-activity-score", "name": "融资活跃度情绪分", "unit": "分", "points": component_scores["financingActivity"][-1900:]},
            {"id": "medium-financing-net-20d-score", "name": "20日融资净流入情绪分", "unit": "分", "points": component_scores["financingNet20D"][-1900:]},
            {"id": "medium-financing-balance-change-60d-score", "name": "60日融资余额变化情绪分", "unit": "分", "points": component_scores["financingBalanceChange60D"][-1900:]},
            {"id": "medium-breadth60-score", "name": "60日市场广度确认分", "unit": "分", "points": component_scores["breadth60"][-1900:]},
            {"id": "medium-erp", "name": "万得全A股权风险溢价ERP", "unit": "%", "points": erp_points},
            {"id": "medium-erp-band-percent", "name": "ERP通道百分化", "unit": "分", "points": erp_band_points[-1900:]},
            {"id": "medium-erp-rolling-3y", "name": "ERP三年滚动均值", "unit": "%", "points": erp_rolling_points[-1900:]},
            {"id": "medium-equity-bond-position", "name": "万得全A/偏债混合型基金指数", "unit": "倍", "points": position_points},
            {"id": "medium-equity-bond-relative-return-120d", "name": "万得全A相对偏债基金120日收益差", "unit": "pct", "points": relative_strength_points},
            {"id": "medium-equity-bond-yield-spread", "name": "万得全A股息率TTM-10年国开债收益率", "unit": "pct", "points": spread_points},
            {"id": "medium-yield-spread-band-percent", "name": "股债收益差通道百分化", "unit": "分", "points": spread_band_points[-1900:]},
            {"id": "medium-yield-spread-rolling-3y", "name": "股债收益差三年滚动均值", "unit": "pct", "points": spread_rolling_points[-1900:]},
            {"id": "medium-financing-balance", "name": "中国融资余额", "unit": "亿元", "points": financing_points},
            {"id": "medium-financing-balance-band-percent", "name": "融资余额通道百分化", "unit": "分", "points": financing_band_points[-1900:]},
            {"id": "medium-financing-balance-rolling-3y", "name": "融资余额三年滚动均值", "unit": "亿元", "points": financing_rolling_points[-1900:]},
            {"id": "medium-financing-activity", "name": "全A融资买入额占比", "unit": "%", "points": financing_activity_points},
            {"id": "medium-financing-net-20d", "name": "20日融资净流入", "unit": "亿元", "points": financing_net_20d_points},
            {"id": "medium-financing-balance-change-60d", "name": "60日融资余额变化率", "unit": "%", "points": financing_balance_change_points},
            {"id": "medium-pe-ttm", "name": "万得全A市盈率PE(TTM)", "unit": "倍", "points": pe_points},
            {"id": "medium-dividend-yield-ttm", "name": "万得全A股息率TTM", "unit": "%", "points": dividend_points},
            {"id": "medium-cdb-10y-yield", "name": "中国:国开债到期收益率:10年", "unit": "%", "points": bond_points},
        ],
    }


def broad_market_excel_index_snapshot():
    from openpyxl import load_workbook

    path = resolve_broad_market_excel()
    workbook = load_workbook(path, data_only=True, read_only=True)
    worksheet = workbook["综合日频数据源"]
    definitions = (
        ("881001.WI", "windall-close-excel", "万得全A"),
        ("8841431.WI", "wind-microcap-close", "万得微盘股"),
        ("000688.SH", "star50-close", "科创50"),
    )
    series = []
    latest_dates = []
    for code, series_id, name in definitions:
        value_col = None
        date_col = None
        # The same index code can occur in turnover and close-price blocks.
        # Match the code together with its field marker so the dashboard never
        # mistakes a turnover percentage for an index close after columns move.
        for col in range(1, worksheet.max_column + 1):
            code_value = worksheet.cell(5, col).value
            if code_value is None or str(code_value).strip().upper() != code.upper():
                continue
            candidate_date_col = None
            for left_col in range(col - 1, max(0, col - 7), -1):
                header = worksheet.cell(5, left_col).value
                if header is not None and str(header).strip().lower() in {"date", "日期"}:
                    candidate_date_col = left_col
                    break
            if candidate_date_col is None:
                continue
            field_markers = {
                str(worksheet.cell(3, marker_col).value).strip().lower()
                for marker_col in range(candidate_date_col, col + 1)
                if worksheet.cell(3, marker_col).value is not None
            }
            if "close" not in field_markers:
                continue
            value_col = col
            date_col = candidate_date_col
            break
        if value_col is None or value_col <= 1:
            continue
        if date_col is None:
            continue
        rows = read_series(
            worksheet,
            date_col,
            {"value": value_col},
            start_row=6,
            end_row=worksheet.max_row,
        )
        points = [
            {
                "date": item["date"].isoformat(),
                "value": clean(item.get("value"), 3),
            }
            for item in rows[-3000:]
            if numeric(item.get("value")) is not None
            and item["date"] < date.today()
        ]
        if points:
            latest_dates.append(points[-1]["date"])
            series.append(
                {
                    "id": series_id,
                    "name": name,
                    "unit": "点",
                    "points": points,
                }
            )
    workbook.close()
    if not series:
        raise RuntimeError("市场宽基情绪指标.xlsx 中没有可用的宽基指数历史序列")
    return {
        "path": str(path),
        "asOf": max(latest_dates),
        "series": series,
    }


def broad_market_excel_turnover_snapshot():
    from openpyxl import load_workbook

    path = resolve_broad_market_excel()
    workbook = load_workbook(path, data_only=True, read_only=True)
    worksheet = workbook["综合日频数据源"]
    definitions = (
        ("881001.WI", "windall-turnover", "万得全A换手率"),
        ("000300.SH", "hs300-turnover", "沪深300换手率"),
        ("000852.SH", "csi1000-turnover", "中证1000换手率"),
        ("000688.SH", "star50-turnover", "科创50换手率"),
    )
    series = []
    latest_dates = []
    for code, series_id, name in definitions:
        value_col = None
        date_col = None
        start_row = 7
        for col in range(1, worksheet.max_column + 1):
            code_value = worksheet.cell(3, col).value
            field_value = worksheet.cell(6, col).value
            if (
                code_value is not None
                and str(code_value).strip().upper() == code.upper()
                and field_value is not None
                and str(field_value).strip().lower() == "turn"
            ):
                value_col = col
                date_col = col - 1
                break
        if value_col is None:
            for col in range(1, worksheet.max_column + 1):
                code_value = worksheet.cell(5, col).value
                if (
                    code_value is None
                    or str(code_value).strip().upper() != code.upper()
                ):
                    continue
                candidate_date_col = None
                for left_col in range(col - 1, max(0, col - 7), -1):
                    header = worksheet.cell(5, left_col).value
                    if (
                        header is not None
                        and str(header).strip().lower() == "date"
                    ):
                        candidate_date_col = left_col
                        break
                if candidate_date_col is None:
                    continue
                field_markers = {
                    str(worksheet.cell(3, marker_col).value).strip().lower()
                    for marker_col in range(candidate_date_col + 1, col + 1)
                    if worksheet.cell(3, marker_col).value is not None
                }
                if "turn" not in field_markers:
                    continue
                value_col = col
                date_col = candidate_date_col
                start_row = 6
                break
        if value_col is None or date_col is None:
            continue
        rows = read_series(
            worksheet,
            date_col,
            {"value": value_col},
            start_row=start_row,
            end_row=worksheet.max_row,
        )
        points = [
            {
                "date": item["date"].isoformat(),
                "value": clean(item.get("value"), 4),
            }
            for item in rows[-3000:]
            if numeric(item.get("value")) is not None
            and item["date"] < date.today()
        ]
        if points:
            latest_dates.append(points[-1]["date"])
            series.append(
                {
                    "id": series_id,
                    "name": name,
                    "unit": "%",
                    "points": points,
                }
            )
    workbook.close()
    if not series:
        raise RuntimeError("市场宽基情绪指标.xlsx 中没有可用的指数换手率历史序列")
    return {
        "path": str(path),
        "asOf": max(latest_dates),
        "series": series,
    }


def broad_market_excel_land_connect_turnover_snapshot():
    """Read daily Shanghai- and Shenzhen-connect turnover from Wind Excel."""
    from openpyxl import load_workbook

    path = resolve_broad_market_excel()
    workbook = load_workbook(path, data_only=True, read_only=True)
    worksheet = workbook["综合日频数据源"]
    sh_col = next(
        (
            col
            for col in range(1, worksheet.max_column + 1)
            if "沪股通" in str(worksheet.cell(2, col).value or "")
            and "成交金额" in str(worksheet.cell(2, col).value or "")
        ),
        None,
    )
    sz_col = next(
        (
            col
            for col in range(1, worksheet.max_column + 1)
            if "深股通" in str(worksheet.cell(2, col).value or "")
            and "成交金额" in str(worksheet.cell(2, col).value or "")
        ),
        None,
    )
    date_col = sh_col - 1 if sh_col else None
    if not sh_col or not sz_col or not date_col:
        workbook.close()
        raise RuntimeError("市场宽基情绪指标.xlsx 中未找到沪股通、深股通成交金额列")
    rows = read_series(
        worksheet,
        date_col,
        {"sh": sh_col, "sz": sz_col},
        start_row=3,
        end_row=worksheet.max_row,
    )
    workbook.close()
    daily = []
    for item in rows:
        sh_value = numeric(item.get("sh"))
        sz_value = numeric(item.get("sz"))
        total = (sh_value or 0) + (sz_value or 0)
        if item["date"] >= date.today() or total <= 0:
            continue
        daily.append({"date": item["date"].isoformat(), "value": total})
    ma5_points = []
    window = deque(maxlen=5)
    for point in daily:
        window.append(point["value"])
        if len(window) == 5:
            ma5_points.append(
                {"date": point["date"], "value": clean(sum(window) / 5, 3)}
            )
    if not ma5_points:
        raise RuntimeError("Excel 中没有足够数据计算陆股通成交总额MA5")
    latest_daily = daily[-1]
    latest_ma5 = ma5_points[-1]
    return {
        "path": str(path),
        "asOf": latest_ma5["date"],
        "turnover": clean(latest_daily["value"], 3),
        "ma5": latest_ma5["value"],
        "series": [
            {
                "id": "land-connect-turnover-ma20",
                "name": "陆股通成交总额MA5",
                "unit": "亿元",
                "points": ma5_points[-3000:],
            }
        ],
    }


def resolve_open_fund_position_excel():
    configured = os.environ.get("OPEN_FUND_POSITION_EXCEL")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    if OPEN_FUND_WIND_DIR.exists():
        preferred = OPEN_FUND_WIND_DIR / OPEN_FUND_PREFERRED_NAME
        if preferred.exists():
            candidates.append(preferred)
        candidates.extend(
            sorted(
                (
                    path
                    for path in OPEN_FUND_WIND_DIR.glob("开放式基金估算股票投资比例*.xlsx")
                    if path.name != OPEN_FUND_PREFERRED_NAME
                ),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        )
    source = next((path for path in candidates if path.exists()), None)
    if source:
        try:
            if (
                not OPEN_FUND_LOCAL_EXCEL.exists()
                or source.stat().st_mtime > OPEN_FUND_LOCAL_EXCEL.stat().st_mtime
            ):
                shutil.copy2(source, OPEN_FUND_LOCAL_EXCEL)
        except (OSError, PermissionError):
            pass
    if OPEN_FUND_LOCAL_EXCEL.exists():
        return OPEN_FUND_LOCAL_EXCEL
    if source:
        return source
    raise FileNotFoundError("未找到开放式基金估算股票投资比例 Excel")


def open_fund_position_snapshot():
    from openpyxl import load_workbook

    path = resolve_open_fund_position_excel()
    workbook = load_workbook(path, data_only=True, read_only=True)
    ws = workbook["sheet1"]
    rows = [
        values
        for values in ws.iter_rows(
            min_row=3,
            max_row=ws.max_row,
            min_col=1,
            max_col=23,
            values_only=True,
        )
        if str(values[20] or "").strip() == "普通股票型基金"
    ]
    if not rows:
        raise RuntimeError("Excel 中没有普通股票型基金样本")

    specifications = [
        ("三月前", 14, 16),
        ("一月前", 11, 13),
        ("5日前", 8, 10),
        ("上期", 5, 7),
        ("最新", 3, 4),
    ]
    snapshots = []
    for label, date_index, value_index in specifications:
        valid = []
        for row in rows:
            dt = as_date(row[date_index])
            value = numeric(row[value_index])
            weight = numeric(row[18])
            if dt and value is not None:
                valid.append((dt, value, weight))
        if not valid:
            continue
        values = sorted(item[1] for item in valid)
        midpoint = len(values) // 2
        median = (
            values[midpoint]
            if len(values) % 2
            else (values[midpoint - 1] + values[midpoint]) / 2
        )
        weighted = [
            (value, weight)
            for _, value, weight in valid
            if weight is not None and weight > 0
        ]
        total_weight = sum(weight for _, weight in weighted)
        weighted_mean = (
            sum(value * weight for value, weight in weighted) / total_weight
            if total_weight > 0
            else sum(values) / len(values)
        )
        snapshots.append(
            {
                "label": label,
                "date": max(item[0] for item in valid),
                "value": weighted_mean,
                "mean": sum(values) / len(values),
                "median": median,
                "sample": len(values),
            }
        )
    snapshots.sort(key=lambda item: item["date"])
    latest = snapshots[-1]
    by_label = {item["label"]: item for item in snapshots}

    def change_from(label):
        comparison = by_label.get(label)
        if not comparison:
            return None
        return latest["value"] - comparison["value"]

    point_map = {}
    try:
        history = json.loads(OPEN_FUND_HISTORY_CACHE.read_text(encoding="utf-8"))
        for point in history.get("points", []):
            dt = as_date(point.get("date"))
            value = numeric(point.get("value"))
            if dt and value is not None:
                point_map[dt.isoformat()] = clean(value, 3)
    except Exception:
        pass
    for item in snapshots:
        point_map[item["date"].isoformat()] = clean(item["value"], 3)
    cutoff = latest["date"] - timedelta(days=366 * 5)
    points = [
        {"date": dt, "value": value}
        for dt, value in sorted(point_map.items())
        if as_date(dt) and as_date(dt) >= cutoff
    ]

    return {
        "path": str(path),
        "asOf": latest["date"].isoformat(),
        "value": clean(latest["value"], 3),
        "mean": clean(latest["mean"], 3),
        "median": clean(latest["median"], 3),
        "sample": latest["sample"],
        "change1D": clean(change_from("上期"), 3),
        "change5D": clean(change_from("5日前"), 3),
        "change1M": clean(change_from("一月前"), 3),
        "points": points,
    }


def read_series(ws, date_col, value_cols, start_row=7, end_row=6407):
    rows = []
    min_col = min([date_col, *value_cols.values()])
    max_col = max([date_col, *value_cols.values()])
    values_iter = ws.iter_rows(
        min_row=start_row,
        max_row=min(ws.max_row, end_row),
        min_col=min_col,
        max_col=max_col,
        values_only=True,
    )
    for values in values_iter:
        dt = as_date(values[date_col - min_col])
        if dt is None:
            continue
        item = {"date": dt}
        valid = False
        for name, col in value_cols.items():
            item[name] = numeric(values[col - min_col])
            valid = valid or item[name] is not None
        if valid:
            rows.append(item)
    rows.sort(key=lambda item: item["date"])
    return rows


def find_price_series(ws, code):
    value_col = None
    for col in range(1, ws.max_column + 1):
        labels = [ws.cell(row, col).value for row in (5, 6)]
        if any(str(label).strip().upper() == code.upper() for label in labels if label is not None):
            value_col = col
            break
    if value_col is None:
        return []
    date_col = value_col - 1
    while date_col > 0:
        labels = [ws.cell(row, date_col).value for row in (5, 6)]
        if any(str(label).strip().lower() in ("date", "日期") for label in labels if label is not None):
            break
        date_col -= 1
    if date_col <= 0:
        return []
    return read_series(ws, date_col, {"value": value_col}, start_row=6)


def rolling_distance(points, window=100):
    output = []
    values = deque()
    running = 0.0
    for point in points:
        value = numeric(point.get("value"))
        if value is None:
            continue
        values.append(value)
        running += value
        if len(values) > window:
            running -= values.popleft()
        if len(values) == window:
            average = running / window
            output.append({
                "date": point["date"].isoformat(),
                "value": round((value / average - 1) * 100, 3),
            })
    return output


def trailing_mean_points(points, window=5):
    output = []
    values = deque()
    running = 0.0
    for point in points:
        value = numeric(point.get("value"))
        if value is None:
            continue
        values.append(value)
        running += value
        if len(values) > window:
            running -= values.popleft()
        if len(values) == window:
            output.append({"date": point["date"], "value": running / window})
    return output


def rolling_percentile_points(points, window=750, min_periods=120):
    output = []
    history = deque()
    for point in points:
        value = numeric(point.get("value"))
        if value is None:
            continue
        history.append(value)
        if len(history) > window:
            history.popleft()
        if len(history) >= min_periods:
            output.append({
                "date": point["date"],
                "value": percentile(list(history), value),
            })
    return output


def wilder_rsi_map(price_by_date, period=14, smoothing_alpha=0.5):
    """Return a causal 14-day Wilder RSI with a three-day EMA."""
    prices = sorted(
        (
            (date_key, numeric(value))
            for date_key, value in price_by_date.items()
            if numeric(value) is not None
        ),
        key=lambda item: item[0],
    )
    gains = deque()
    losses = deque()
    average_gain = None
    average_loss = None
    previous_price = None
    previous_smoothed = None
    output = {}
    for date_key, price in prices:
        if previous_price is None:
            previous_price = price
            continue
        change = price - previous_price
        previous_price = price
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        if average_gain is None or average_loss is None:
            gains.append(gain)
            losses.append(loss)
            if len(gains) < period:
                continue
            average_gain = sum(gains) / period
            average_loss = sum(losses) / period
        else:
            average_gain = (average_gain * (period - 1) + gain) / period
            average_loss = (average_loss * (period - 1) + loss) / period
        if average_loss == 0:
            rsi = 100.0 if average_gain > 0 else 50.0
        else:
            relative_strength = average_gain / average_loss
            rsi = 100 - 100 / (1 + relative_strength)
        smoothed = (
            rsi
            if previous_smoothed is None
            else rsi * smoothing_alpha + previous_smoothed * (1 - smoothing_alpha)
        )
        previous_smoothed = smoothed
        output[date_key] = smoothed
    return output


def blend_breadth_with_rsi(points, price_by_date, rsi_weight=0.20):
    """Blend the independent RQData breadth score with price RSI."""
    rsi_by_date = wilder_rsi_map(price_by_date)
    output = []
    for point in points:
        breadth_score = numeric(point.get("sentiment"))
        rsi = numeric(rsi_by_date.get(point.get("date")))
        if breadth_score is None:
            continue
        blended_score = (
            breadth_score
            if rsi is None
            else breadth_score * (1 - rsi_weight) + rsi * rsi_weight
        )
        output.append({
            **point,
            "originalBreadthSentiment": round(breadth_score, 2),
            "rsi14": round(rsi, 2) if rsi is not None else None,
            "rsiWeight": round(rsi_weight * 100, 1),
            "sentiment": round(max(0.0, min(100.0, blended_score)), 2),
        })
    return apply_optimized_phases(
        output,
        top_threshold=68,
        bottom_threshold=33,
    )


def add_price_breadth_diagnostics(points):
    """Add point-in-time price/breadth divergence and 60-day confirmation.

    Positive divergence means price momentum is stronger than breadth
    momentum, which is a potential top-risk warning. Negative divergence means
    breadth is improving faster than price.
    """
    if not points:
        return points
    price_change = []
    nhnl_change = []
    above_ma_change = []
    for index in range(20, len(points)):
        point = points[index]
        prior = points[index - 20]
        price = numeric(point.get("windAll"))
        prior_price = numeric(prior.get("windAll"))
        metrics = point.get("metrics", {})
        prior_metrics = prior.get("metrics", {})
        nhnl = numeric(metrics.get("nhnlBreadth"))
        prior_nhnl = numeric(prior_metrics.get("nhnlBreadth"))
        above_ma = numeric(metrics.get("aboveMaBreadth"))
        prior_above_ma = numeric(prior_metrics.get("aboveMaBreadth"))
        if price not in (None, 0) and prior_price not in (None, 0):
            price_change.append({
                "date": point["date"],
                "value": (price / prior_price - 1) * 100,
            })
        if nhnl is not None and prior_nhnl is not None:
            nhnl_change.append({"date": point["date"], "value": nhnl - prior_nhnl})
        if above_ma is not None and prior_above_ma is not None:
            above_ma_change.append({"date": point["date"], "value": above_ma - prior_above_ma})

    price_scores = {
        item["date"]: item["value"]
        for item in rolling_percentile_points(price_change)
    }
    nhnl_scores = {
        item["date"]: item["value"]
        for item in rolling_percentile_points(nhnl_change)
    }
    above_scores = {
        item["date"]: item["value"]
        for item in rolling_percentile_points(above_ma_change)
    }
    previous_leading_candidate = None
    for index, point in enumerate(points):
        date_key = point.get("date")
        price_score = numeric(price_scores.get(date_key))
        breadth_values = [
            numeric(nhnl_scores.get(date_key)),
            numeric(above_scores.get(date_key)),
        ]
        breadth_values = [value for value in breadth_values if value is not None]
        divergence = None
        if price_score is not None and breadth_values:
            divergence = round(price_score - sum(breadth_values) / len(breadth_values), 1)
        confirmation60 = numeric(
            point.get("components", {}).get("breadth60Confirmation")
        )
        prior_confirmation60 = (
            numeric(points[index - 10].get("components", {}).get("breadth60Confirmation"))
            if index >= 10
            else None
        )
        confirmation60_change10 = (
            confirmation60 - prior_confirmation60
            if confirmation60 is not None and prior_confirmation60 is not None
            else None
        )
        if divergence is None:
            divergence_label = "待生成"
        elif divergence >= 20:
            divergence_label = "价格领先广度"
        elif divergence <= -20:
            divergence_label = "广度领先价格"
        else:
            divergence_label = "价格广度同步"
        if confirmation60 is None:
            confirmation_label = "待生成"
        elif confirmation60 >= 65:
            confirmation_label = "中期广度强"
        elif confirmation60 <= 35:
            confirmation_label = "中期广度弱"
        else:
            confirmation_label = "中期广度中性"
        phase = point.get("phase")
        if confirmation60 is None:
            cycle_confirmation_label = "等待60日数据"
        elif phase in ("rising", "bottom"):
            cycle_confirmation_label = (
                "中期上行已确认"
                if confirmation60 >= 55
                else "短期修复待确认"
            )
        elif phase in ("falling", "top"):
            cycle_confirmation_label = (
                "中期下行已确认"
                if confirmation60 <= 45
                else "中期广度仍有韧性"
            )
        else:
            cycle_confirmation_label = confirmation_label

        score = numeric(point.get("sentiment"))
        score5 = numeric(points[index - 5].get("sentiment")) if index >= 5 else None
        score_slope5 = score - score5 if score is not None and score5 is not None else None
        recent_scores = [
            numeric(item.get("sentiment"))
            for item in points[max(0, index - 19):index + 1]
        ]
        recent_scores = [value for value in recent_scores if value is not None]
        recent_max = max(recent_scores) if recent_scores else None
        recent_min = min(recent_scores) if recent_scores else None

        def bounded(value):
            return max(0.0, min(100.0, value))

        top_risk = None
        bottom_repair = None
        if (
            recent_max is not None
            and score_slope5 is not None
            and divergence is not None
            and confirmation60 is not None
        ):
            high_level = bounded((recent_max - 65) * 5)
            rollover = bounded(-score_slope5 * 8)
            divergence_risk = bounded(divergence)
            medium_weakness = bounded(100 - confirmation60)
            top_risk = round(
                high_level * 0.35
                + rollover * 0.25
                + divergence_risk * 0.25
                + medium_weakness * 0.15,
                1,
            )
        if (
            recent_min is not None
            and score_slope5 is not None
            and divergence is not None
            and confirmation60_change10 is not None
        ):
            low_extreme = bounded((35 - recent_min) * 5)
            rebound = bounded(score_slope5 * 8)
            breadth_lead = bounded(-divergence)
            medium_turn = bounded(confirmation60_change10 * 8)
            bottom_repair = round(
                low_extreme * 0.30
                + rebound * 0.30
                + breadth_lead * 0.25
                + medium_turn * 0.15,
                1,
            )

        leading_candidate = None
        if (
            top_risk is not None
            and top_risk >= 55
            and score_slope5 is not None
            and score_slope5 < 0
        ):
            leading_candidate = "高位转弱预警"
        elif (
            bottom_repair is not None
            and bottom_repair >= 55
            and score_slope5 is not None
            and score_slope5 > 0
        ):
            leading_candidate = "低位修复预警"
        if leading_candidate and leading_candidate == previous_leading_candidate:
            leading_signal = leading_candidate
        elif leading_candidate:
            leading_signal = "拐点信号观察中"
        else:
            leading_signal = "暂无明确拐点"
        previous_leading_candidate = leading_candidate

        if top_risk is not None and top_risk >= 65 and divergence is not None and divergence >= 20:
            confirmed_phase_label = "顶部风险确认"
        elif top_risk is not None and top_risk >= 45:
            confirmed_phase_label = "高位风险观察"
        elif bottom_repair is not None and bottom_repair >= 65 and confirmation60 is not None and confirmation60 >= 55:
            confirmed_phase_label = "底部反转确认"
        elif bottom_repair is not None and bottom_repair >= 50:
            confirmed_phase_label = "底部修复，等待60日确认"
        else:
            confirmed_phase_label = cycle_confirmation_label
        point["displayPhaseLabel"] = confirmed_phase_label
        point["diagnostics"] = {
            "priceBreadthDivergence": divergence,
            "priceBreadthDivergenceLabel": divergence_label,
            "priceBreadthAsOf": date_key if divergence is not None else None,
            "breadth60Confirmation": clean(confirmation60, 1),
            "breadth60Change10": clean(confirmation60_change10, 1),
            "breadth60ConfirmationLabel": confirmation_label,
            "breadth60AsOf": date_key if confirmation60 is not None else None,
            "cycleConfirmationLabel": cycle_confirmation_label,
            "topRisk": top_risk,
            "bottomRepair": bottom_repair,
            "leadingSignal": leading_signal,
            "leadingSignalAsOf": date_key,
            "confirmedPhaseLabel": confirmed_phase_label,
            "compositeAsOf": date_key if top_risk is not None or bottom_repair is not None else None,
        }
    return points


def sentiment_cycle_series(market, financing, wind_all, wind_distance, breadth, institutional):
    market_by_date = {item["date"]: item for item in market}

    trend_points = [
        {"date": as_date(item["date"]), "value": item["value"]}
        for item in wind_distance
        if as_date(item["date"])
    ]
    turnover_points = [
        {"date": item["date"], "value": item.get("turnover")}
        for item in market
        if numeric(item.get("turnover")) is not None
    ]
    breadth_points = []
    for item in breadth:
        up = numeric(item.get("up"))
        down = numeric(item.get("down"))
        if up is not None and down is not None and up + down > 0:
            breadth_points.append({"date": item["date"], "value": up / (up + down) * 100})

    financing_net_points = []
    financing_activity_points = []
    previous_balance = None
    for item in financing:
        balance = numeric(item.get("balance"))
        buy = numeric(item.get("buy"))
        market_row = market_by_date.get(item["date"], {})
        amount = numeric(market_row.get("amount"))
        if balance is not None and previous_balance is not None and amount not in (None, 0):
            financing_net_points.append({
                "date": item["date"],
                "value": (balance - previous_balance) / amount * 100,
            })
        if buy is not None and amount not in (None, 0):
            financing_activity_points.append({
                "date": item["date"],
                "value": buy / amount * 100,
            })
        if balance is not None:
            previous_balance = balance

    institutional_points = []
    for item in institutional:
        amount = numeric(market_by_date.get(item["date"], {}).get("amount"))
        net = numeric(item.get("net"))
        if net is not None and amount not in (None, 0):
            institutional_points.append({"date": item["date"], "value": net / amount * 100})

    component_points = {
        "trend": rolling_percentile_points(trend_points),
        "breadth": rolling_percentile_points(trailing_mean_points(breadth_points, 5)),
        "activity": rolling_percentile_points(trailing_mean_points(turnover_points, 3)),
        "financingNet": rolling_percentile_points(trailing_mean_points(financing_net_points, 5)),
        "financingActivity": rolling_percentile_points(trailing_mean_points(financing_activity_points, 5)),
        "institutional": rolling_percentile_points(trailing_mean_points(institutional_points, 5)),
    }
    component_maps = {
        name: {item["date"]: item["value"] for item in points}
        for name, points in component_points.items()
    }
    price_map = {
        item["date"]: numeric(item.get("value"))
        for item in wind_all
        if numeric(item.get("value")) is not None
    }

    common_dates = sorted(
        set(component_maps["trend"])
        & set(component_maps["breadth"])
        & set(component_maps["activity"])
        & set(component_maps["financingNet"])
        & set(component_maps["financingActivity"])
        & set(component_maps["institutional"])
        & set(price_map)
    )
    output = []
    previous_score = None
    for dt in common_dates:
        financing_score = (
            component_maps["financingNet"][dt] * 0.4
            + component_maps["financingActivity"][dt] * 0.6
        )
        components = {
            "trend": component_maps["trend"][dt],
            "breadth": component_maps["breadth"][dt],
            "activity": component_maps["activity"][dt],
            "financing": financing_score,
            "institutional": component_maps["institutional"][dt],
        }
        raw_score = (
            components["trend"] * 0.35
            + components["breadth"] * 0.20
            + components["activity"] * 0.25
            + components["financing"] * 0.15
            + components["institutional"] * 0.05
        )
        overheat_penalty = 0.0
        if components["activity"] > 90 and components["breadth"] < 55:
            overheat_penalty += min(4.0, (components["activity"] - 90) * 0.4)
        if components["trend"] > 95:
            overheat_penalty += min(3.0, (components["trend"] - 95) * 0.6)
        adjusted = max(0.0, min(100.0, raw_score - overheat_penalty))
        smoothed = adjusted if previous_score is None else adjusted * 0.5 + previous_score * 0.5
        previous_score = smoothed
        output.append({
            "date": dt.isoformat(),
            "sentiment": round(smoothed, 2),
            "windAll": round(price_map[dt], 2),
            "components": {name: round(value, 1) for name, value in components.items()},
            "overheatPenalty": round(overheat_penalty, 2),
        })
    phase_labels = {
        "rising": "上行",
        "top": "顶部",
        "falling": "下行",
        "bottom": "底部",
        "neutral": "蓄势",
    }
    previous_phase = "neutral"
    for index, item in enumerate(output):
        if index < 10:
            phase = "neutral"
        else:
            slope = item["sentiment"] - output[index - 10]["sentiment"]
            if item["sentiment"] >= 70 and slope <= 0:
                phase = "top"
            elif item["sentiment"] <= 30 and slope >= 0:
                phase = "bottom"
            elif slope > 1:
                phase = "rising"
            elif slope < -1:
                phase = "falling"
            elif item["sentiment"] >= 70:
                phase = "top"
            elif item["sentiment"] <= 30:
                phase = "bottom"
            else:
                phase = previous_phase if previous_phase in ("rising", "falling") else "neutral"
        item["phase"] = phase
        item["phaseLabel"] = phase_labels[phase]
        previous_phase = phase
    return output


def cycle_label(score):
    score = numeric(score)
    if score is None:
        return "数据不足"
    if score >= 80:
        return "亢奋"
    if score >= 65:
        return "活跃"
    if score >= 55:
        return "偏强"
    if score >= 45:
        return "中性"
    if score >= 30:
        return "偏弱"
    return "冰点"


def apply_cycle_phases(points):
    phase_labels = {
        "rising": "上行",
        "top": "顶部",
        "falling": "下行",
        "bottom": "底部",
        "neutral": "蓄势",
    }
    previous_phase = "neutral"
    for index, item in enumerate(points):
        if index < 10:
            phase = "neutral"
        else:
            slope = item["sentiment"] - points[index - 10]["sentiment"]
            if item["sentiment"] >= 70 and slope <= 0:
                phase = "top"
            elif item["sentiment"] <= 30 and slope >= 0:
                phase = "bottom"
            elif slope > 1:
                phase = "rising"
            elif slope < -1:
                phase = "falling"
            elif item["sentiment"] >= 70:
                phase = "top"
            elif item["sentiment"] <= 30:
                phase = "bottom"
            else:
                phase = previous_phase if previous_phase in ("rising", "falling") else "neutral"
        item["phase"] = phase
        item["phaseLabel"] = phase_labels[phase]
        previous_phase = phase
    return points


def difference_points(points, periods=5):
    output = []
    for index in range(periods, len(points)):
        current = numeric(points[index].get("value"))
        previous = numeric(points[index - periods].get("value"))
        if current is not None and previous is not None:
            output.append({"date": points[index]["date"], "value": current - previous})
    return output


def breadth_sentiment_series(breadth, limit_breadth, wind_all):
    advance_points = []
    for item in breadth:
        up = numeric(item.get("up"))
        down = numeric(item.get("down"))
        if up is not None and down is not None and up + down > 0:
            advance_points.append({"date": item["date"], "value": up / (up + down) * 100})

    limit_points = []
    for item in limit_breadth:
        limit_up = numeric(item.get("limitUp"))
        limit_down = numeric(item.get("limitDown"))
        if limit_up is not None and limit_down is not None:
            limit_points.append({"date": item["date"], "value": limit_up - limit_down})

    components = {
        "advanceBreadth": rolling_percentile_points(trailing_mean_points(advance_points, 3)),
        "limitBreadth": rolling_percentile_points(trailing_mean_points(limit_points, 3)),
        "advanceChange": rolling_percentile_points(difference_points(advance_points, 5)),
        "limitChange": rolling_percentile_points(difference_points(limit_points, 5)),
    }
    maps = {
        name: {item["date"]: item["value"] for item in points}
        for name, points in components.items()
    }
    price_map = {
        item["date"]: numeric(item.get("value"))
        for item in wind_all
        if numeric(item.get("value")) is not None
    }
    common_dates = sorted(
        set(maps["advanceBreadth"])
        & set(maps["limitBreadth"])
        & set(maps["advanceChange"])
        & set(maps["limitChange"])
        & set(price_map)
    )
    output = []
    previous_score = None
    for dt in common_dates:
        values = {name: score_map[dt] for name, score_map in maps.items()}
        raw_score = (
            values["advanceBreadth"] * 0.40
            + values["limitBreadth"] * 0.30
            + values["advanceChange"] * 0.15
            + values["limitChange"] * 0.15
        )
        smoothed = raw_score if previous_score is None else raw_score * 0.5 + previous_score * 0.5
        previous_score = smoothed
        output.append({
            "date": dt.isoformat(),
            "sentiment": round(smoothed, 2),
            "windAll": round(price_map[dt], 2),
            "components": {name: round(value, 1) for name, value in values.items()},
        })
    return apply_cycle_phases(output)


def excel_snapshot():
    from openpyxl import load_workbook

    path = resolve_excel()
    workbook = load_workbook(path, data_only=True, read_only=True)
    ws = workbook["综合日频数据源"]

    market = read_series(ws, 1, {"turnover": 2, "amount": 3}, start_row=7)
    financing = read_series(ws, 19, {"balance": 20, "buy": 21}, start_row=7)
    breadth = read_series(ws, 38, {"up": 39, "down": 40}, start_row=7)
    limit_breadth = read_series(ws, 11, {"limitUp": 12, "limitDown": 13}, start_row=7)
    institutional = read_series(ws, 23, {"net": 24}, start_row=7)
    wind_all = find_price_series(ws, "8841388.WI")
    sh_comp = find_price_series(ws, "000001.SH")
    workbook.close()

    market_by_date = {item["date"]: item for item in market}
    latest_market = market[-1] if market else {}
    turnover_rows = [item for item in market if numeric(item.get("turnover")) is not None]
    latest_turnover = turnover_rows[-1] if turnover_rows else {}
    latest_financing = financing[-1] if financing else {}
    previous_financing = financing[-2] if len(financing) >= 2 else {}
    financing_date = latest_financing.get("date")
    aligned_market = market_by_date.get(financing_date, latest_market)

    financing_net = None
    if numeric(latest_financing.get("balance")) is not None and numeric(previous_financing.get("balance")) is not None:
        financing_net = latest_financing["balance"] - previous_financing["balance"]
    financing_activity = None
    if numeric(latest_financing.get("buy")) is not None and numeric(aligned_market.get("amount")) not in (None, 0):
        financing_activity = latest_financing["buy"] / aligned_market["amount"] * 100

    wind_distance = rolling_distance(wind_all)
    sh_distance = rolling_distance(sh_comp)
    cycle_points = sentiment_cycle_series(
        market, financing, wind_all, wind_distance, breadth, institutional
    )
    latest_cycle = cycle_points[-1] if cycle_points else {}
    breadth_cycle_points = breadth_sentiment_series(breadth, limit_breadth, wind_all)
    latest_breadth_cycle = breadth_cycle_points[-1] if breadth_cycle_points else {}

    financing_history = []
    previous_balance = None
    for item in financing:
        balance = numeric(item.get("balance"))
        buy = numeric(item.get("buy"))
        amount = numeric(market_by_date.get(item["date"], {}).get("amount"))
        net = balance - previous_balance if balance is not None and previous_balance is not None else None
        activity = buy / amount * 100 if buy is not None and amount not in (None, 0) else None
        financing_history.append({
            "date": item["date"].isoformat(),
            "net": clean(net, 3),
            "activity": clean(activity, 3),
        })
        if balance is not None:
            previous_balance = balance

    institutional_rows = [
        item for item in institutional if numeric(item.get("net")) is not None
    ]
    latest_institutional = institutional_rows[-1] if institutional_rows else {}
    institutional_values = [item["net"] for item in institutional_rows]
    institutional_5d = sum(institutional_values[-5:]) if institutional_values else None
    institutional_20d = sum(institutional_values[-20:]) if institutional_values else None

    latest_dates = [item.get("date") for item in (latest_market, latest_financing) if item.get("date")]
    if wind_all:
        latest_dates.append(wind_all[-1]["date"])
    if sh_comp:
        latest_dates.append(sh_comp[-1]["date"])
    as_of = max(latest_dates).isoformat() if latest_dates else None

    return {
        "path": str(path),
        "modifiedAt": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "asOf": as_of,
        "marketAsOf": latest_turnover.get("date").isoformat() if latest_turnover.get("date") else None,
        "turnover": clean(latest_turnover.get("turnover"), 3),
        "turnoverPercentile": percentile([item.get("turnover") for item in turnover_rows], latest_turnover.get("turnover")),
        "marketAmount": clean(latest_market.get("amount"), 2),
        "windAllDistance100d": wind_distance[-1]["value"] if wind_distance else None,
        "shCompositeDistance100d": sh_distance[-1]["value"] if sh_distance else None,
        "financingAsOf": financing_date.isoformat() if financing_date else None,
        "financingBalance": clean(latest_financing.get("balance"), 2),
        "financingNet": clean(financing_net, 2),
        "financingBuy": clean(latest_financing.get("buy"), 2),
        "financingActivity": clean(financing_activity, 3),
        "institutionalAsOf": (
            latest_institutional.get("date").isoformat()
            if latest_institutional.get("date")
            else None
        ),
        "institutionalNetBuy": clean(latest_institutional.get("net"), 3),
        "institutionalNetBuy5D": clean(institutional_5d, 3),
        "institutionalNetBuy20D": clean(institutional_20d, 3),
        "sentimentCycle": {
            "asOf": latest_cycle.get("date"),
            "score": latest_cycle.get("sentiment"),
            "label": cycle_label(latest_cycle.get("sentiment")),
            "phase": latest_cycle.get("phase"),
            "phaseLabel": latest_cycle.get("phaseLabel"),
            "components": latest_cycle.get("components", {}),
            "overheatPenalty": latest_cycle.get("overheatPenalty"),
            "weights": {
                "trend": 35,
                "breadth": 20,
                "activity": 25,
                "financing": 15,
                "institutional": 5,
            },
            "points": cycle_points[-2500:],
        },
        "breadthCycle": {
            "asOf": latest_breadth_cycle.get("date"),
            "score": latest_breadth_cycle.get("sentiment"),
            "label": cycle_label(latest_breadth_cycle.get("sentiment")),
            "phase": latest_breadth_cycle.get("phase"),
            "phaseLabel": latest_breadth_cycle.get("phaseLabel"),
            "components": latest_breadth_cycle.get("components", {}),
            "weights": {
                "advanceBreadth": 40,
                "limitBreadth": 30,
                "advanceChange": 15,
                "limitChange": 15,
            },
            "points": breadth_cycle_points[-2500:],
        },
        "windAllPrices": [
            {"date": item["date"].isoformat(), "value": clean(item.get("value"), 2)}
            for item in wind_all[-3000:]
            if numeric(item.get("value")) is not None
        ],
        "shCompositePrices": [
            {"date": item["date"].isoformat(), "value": clean(item.get("value"), 2)}
            for item in sh_comp[-3000:]
            if numeric(item.get("value")) is not None
        ],
        "series": [
            {
                "id": "windall-close-excel",
                "name": "万得全A",
                "unit": "点",
                "points": [
                    {
                        "date": item["date"].isoformat(),
                        "value": clean(item.get("value"), 2),
                    }
                    for item in wind_all[-3000:]
                    if numeric(item.get("value")) is not None
                ],
            },
            {
                "id": "sh-composite-close-excel",
                "name": "上证指数",
                "unit": "点",
                "points": [
                    {
                        "date": item["date"].isoformat(),
                        "value": clean(item.get("value"), 2),
                    }
                    for item in sh_comp[-3000:]
                    if numeric(item.get("value")) is not None
                ],
            },
            {
                "id": "breadth-sentiment",
                "name": "市场广度情绪",
                "unit": "分",
                "points": [
                    {"date": item["date"], "value": item["sentiment"]}
                    for item in breadth_cycle_points[-1260:]
                ],
            },
            {
                "id": "sentiment-cycle",
                "name": "A股短线情绪周期",
                "unit": "分",
                "points": [
                    {"date": item["date"], "value": item["sentiment"]}
                    for item in cycle_points[-1260:]
                ],
            },
            {
                "id": "market-turnover",
                "name": "万得全A等权指数日频换手率",
                "unit": "%",
                "points": [{"date": item["date"].isoformat(), "value": clean(item.get("turnover"), 3)} for item in market[-1260:]],
            },
            {"id": "windall-ma100", "name": "Wind全A距100日均线", "unit": "%", "points": wind_distance[-1260:]},
            {"id": "sh-ma100", "name": "上证综指距100日均线", "unit": "%", "points": sh_distance[-1260:]},
            {
                "id": "financing-net",
                "name": "融资净流入",
                "unit": "亿元",
                "points": [{"date": item["date"], "value": item["net"]} for item in financing_history[-1260:] if item["net"] is not None],
            },
            {
                "id": "financing-activity",
                "name": "融资交易活跃度",
                "unit": "%",
                "points": [{"date": item["date"], "value": item["activity"]} for item in financing_history[-1260:] if item["activity"] is not None],
            },
            {
                "id": "institutional-net-buy",
                "name": "机构主动买入净额",
                "unit": "亿元",
                "points": [
                    {"date": item["date"].isoformat(), "value": clean(item.get("net"), 3)}
                    for item in institutional_rows[-1260:]
                ],
            },
        ],
    }


def load_rqdata_cache():
    if not RQDATA_CACHE.exists():
        return None
    try:
        return json.loads(RQDATA_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_rqdata_breadth_cache():
    if not RQDATA_BREADTH_CACHE.exists():
        return None
    try:
        payload = json.loads(RQDATA_BREADTH_CACHE.read_text(encoding="utf-8"))
        if not isinstance(payload.get("points"), list) or not payload.get("points"):
            return None
        payload["points"] = apply_optimized_phases(payload["points"])
        latest = payload["points"][-1]
        payload["phase"] = latest.get("phase")
        payload["phaseLabel"] = latest.get("phaseLabel")
        payload["phaseMethodology"] = "顶部采用高位回落确认；底部采用低位反弹与广度修复确认，15个交易日内不重复触发"
        return payload
    except Exception:
        return None


def refresh_rqdata_if_needed():
    cached = load_rqdata_cache()
    missing_new_equity_funds = (
        not isinstance(cached, dict)
        or cached.get("newEquityFundCount20D") is None
        or not any(
            item.get("id") == "new-equity-fund-shares"
            for item in cached.get("series", [])
            if isinstance(item, dict)
        )
    )
    stale = (
        missing_new_equity_funds
        or not RQDATA_CACHE.exists()
        or time.time() - RQDATA_CACHE.stat().st_mtime > RQDATA_REFRESH_SECONDS
    )
    if not ENABLE_RQDATA_REFRESH or not stale:
        return cached, None
    if not RQDATA_PYTHON.exists():
        return cached, f"未找到 RQData Python：{RQDATA_PYTHON}"
    try:
        completed = subprocess.run(
            [str(RQDATA_PYTHON), str(RQDATA_SCRIPT), "--output", str(RQDATA_CACHE)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=RQDATA_REFRESH_TIMEOUT,
            check=True,
        )
        return load_rqdata_cache(), None
    except subprocess.TimeoutExpired:
        return cached, f"RQData 刷新超过 {RQDATA_REFRESH_TIMEOUT} 秒，继续使用现有数据"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip().splitlines()
        return cached, (detail[-1] if detail else str(exc))[:240]
    except Exception as exc:
        return cached, str(exc)[:240]


def source_record(name, status, as_of=None, detail=None):
    return {"name": name, "status": status, "asOf": as_of, "detail": detail}


def metric_card(identifier, title, source, as_of, value=None, unit=None, percentile_value=None, note=None, submetrics=None):
    submetrics = submetrics or []
    available = numeric(value) is not None or any(numeric(item.get("value")) is not None for item in submetrics)
    return {
        "id": identifier,
        "title": title,
        "status": "available" if available else "missing",
        "source": source,
        "asOf": as_of,
        "value": clean(value, 3),
        "unit": unit,
        "percentile": clean(percentile_value, 1),
        "note": note,
        "submetrics": submetrics,
    }


def _build_payload():
    if not ENABLE_RQDATA_REFRESH:
        cached_payload = load_page_cache(source_signature())
        if cached_payload is not None:
            return cached_payload

    notes = []
    excel = None
    try:
        excel = excel_snapshot()
    except Exception as exc:
        notes.append(f"Excel 读取失败：{str(exc)[:220]}")

    open_fund_position = None
    try:
        open_fund_position = open_fund_position_snapshot()
    except Exception as exc:
        notes.append(f"股票型基金仓位读取失败：{str(exc)[:220]}")

    derivatives_pcr = None
    try:
        derivatives_pcr = derivatives_pcr_snapshot()
    except Exception as exc:
        notes.append(f"衍生品情绪读取失败：{str(exc)[:220]}")

    margin_risk_excel = None
    try:
        margin_risk_excel = margin_risk_excel_snapshot()
    except Exception as exc:
        notes.append(f"Excel 两融风险指标读取失败：{str(exc)[:220]}")

    new_equity_fund_shares = None
    try:
        new_equity_fund_shares = broad_market_new_equity_fund_shares_snapshot()
    except Exception as exc:
        notes.append(f"新成立偏股型基金份额读取失败：{str(exc)[:220]}")

    medium_term_sentiment = None
    try:
        medium_term_sentiment = broad_market_medium_term_sentiment_snapshot()
    except Exception as exc:
        notes.append(f"中期情绪指标读取失败：{str(exc)[:220]}")

    broad_market_indices = None
    try:
        broad_market_indices = broad_market_excel_index_snapshot()
    except Exception as exc:
        notes.append(f"宽基指数读取失败：{str(exc)[:220]}")

    broad_market_turnover = None
    try:
        broad_market_turnover = broad_market_excel_turnover_snapshot()
    except Exception as exc:
        notes.append(f"宽基指数换手率读取失败：{str(exc)[:220]}")

    excel_land_connect_turnover = None
    try:
        excel_land_connect_turnover = broad_market_excel_land_connect_turnover_snapshot()
    except Exception as exc:
        notes.append(f"陆股通成交总额读取失败：{str(exc)[:220]}")

    rqdata, rq_error = refresh_rqdata_if_needed()
    if rq_error:
        notes.append(f"RQData：{rq_error}")
    rqdata = rqdata or {}

    rq_land_connect_series = next(
        (
            item
            for item in rqdata.get("series", [])
            if item.get("id") == "land-connect-turnover-ma20"
            and item.get("points")
            and (
                "MA5" in str(item.get("name") or "")
                or rqdata.get("landConnectTurnoverMA5") is not None
            )
        ),
        None,
    )
    rq_land_connect_as_of = rqdata.get("landConnectTurnoverAsOf")
    excel_land_connect_as_of = (
        excel_land_connect_turnover.get("asOf")
        if excel_land_connect_turnover
        else None
    )
    if (
        rq_land_connect_series
        and rq_land_connect_as_of
        and (
            not excel_land_connect_as_of
            or rq_land_connect_as_of >= excel_land_connect_as_of
        )
    ):
        land_connect_turnover = {
            "asOf": rq_land_connect_as_of,
            "source": "RQData",
            "series": [rq_land_connect_series],
        }
    else:
        land_connect_turnover = excel_land_connect_turnover

    excel_as_of = excel.get("asOf") if excel else None
    rq_as_of = rqdata.get("asOf")
    cycle = excel.get("sentimentCycle", {}) if excel else {}
    cycle_components = cycle.get("components", {})
    proxy_breadth_cycle = excel.get("breadthCycle", {}) if excel else {}
    breadth_cycle = proxy_breadth_cycle
    breadth_mode = "proxy"
    exact_breadth = load_rqdata_breadth_cache()
    if exact_breadth:
        breadth_cycle = {
            **exact_breadth,
            "label": cycle_label(exact_breadth.get("score")),
        }
        breadth_cycle["points"] = add_price_breadth_diagnostics(
            breadth_cycle.get("points", [])
        )
        if breadth_cycle["points"]:
            breadth_cycle["diagnostics"] = breadth_cycle["points"][-1].get(
                "diagnostics", {}
            )
            breadth_cycle["phaseLabel"] = breadth_cycle["diagnostics"].get(
                "confirmedPhaseLabel", breadth_cycle.get("phaseLabel")
            )
        breadth_mode = "exact"
    benchmark_label = None
    benchmark_by_date = {}
    rq_series = rqdata.get("series", []) if isinstance(rqdata.get("series"), list) else []
    rq_allshare = next((item for item in rq_series if item.get("id") == "allshare-close"), {})
    if rq_allshare:
        benchmark_label = "中证全指"
        benchmark_by_date = {
            item["date"]: item["value"]
            for item in rq_allshare.get("points", [])
            if item.get("date") and numeric(item.get("value")) is not None
        }
    elif excel:
        benchmark_label = "万得全A"
        benchmark_by_date = {
            item["date"]: item["value"]
            for item in excel.get("windAllPrices", [])
            if item.get("date") and numeric(item.get("value")) is not None
        }
    if exact_breadth and benchmark_by_date:
        exact_points = [
            {**item, "windAll": benchmark_by_date[item["date"]]}
            for item in exact_breadth.get("points", [])
            if item.get("date") in benchmark_by_date and numeric(item.get("sentiment")) is not None
        ]
        if exact_points:
            exact_points = blend_breadth_with_rsi(
                exact_points,
                benchmark_by_date,
                rsi_weight=0.20,
            )
            exact_points = add_price_breadth_diagnostics(exact_points)
            breadth_cycle["points"] = exact_points[-2500:]
            latest_blended = exact_points[-1]
            breadth_cycle["asOf"] = latest_blended.get("date")
            breadth_cycle["score"] = latest_blended.get("sentiment")
            breadth_cycle["label"] = cycle_label(latest_blended.get("sentiment"))
            breadth_cycle["phase"] = latest_blended.get("phase")
            breadth_cycle["phaseLabel"] = latest_blended.get("phaseLabel")
            breadth_cycle["originalBreadthSentiment"] = latest_blended.get(
                "originalBreadthSentiment"
            )
            breadth_cycle["rsi14"] = latest_blended.get("rsi14")
            breadth_cycle["weights"] = {
                "marketBreadth": 80,
                "rsi14": 20,
            }
            breadth_cycle["benchmarkLabel"] = benchmark_label
            current_diagnostics = dict(breadth_cycle.get("diagnostics", {}))
            aligned_diagnostics = exact_points[-1].get("diagnostics", {})
            for key in (
                "priceBreadthDivergence",
                "priceBreadthDivergenceLabel",
                "priceBreadthAsOf",
                "topRisk",
                "bottomRepair",
                "leadingSignal",
                "leadingSignalAsOf",
                "confirmedPhaseLabel",
                "compositeAsOf",
            ):
                current_diagnostics[key] = aligned_diagnostics.get(key)
            breadth_cycle["diagnostics"] = current_diagnostics
            breadth_cycle["phaseLabel"] = breadth_cycle["diagnostics"].get(
                "confirmedPhaseLabel", breadth_cycle.get("phaseLabel")
            )
    breadth_components = breadth_cycle.get("components", {})
    breadth_diagnostics = breadth_cycle.get("diagnostics", {})
    if breadth_mode == "exact":
        breadth_metrics = breadth_cycle.get("metrics", {})
        breadth_submetrics = [
            {"label": "周期阶段", "value": None, "text": f"{breadth_cycle.get('phaseLabel', '—')} · {breadth_cycle.get('label', '—')}", "unit": ""},
            {"label": "原始市场广度分", "value": breadth_cycle.get("originalBreadthSentiment"), "unit": "分"},
            {"label": f"{breadth_cycle.get('benchmarkLabel') or '宽基指数'} RSI", "value": breadth_cycle.get("rsi14"), "unit": "分"},
            {"label": "20日新高家数", "value": breadth_metrics.get("newHigh"), "unit": "只"},
            {"label": "20日新低家数", "value": breadth_metrics.get("newLow"), "unit": "只"},
            {"label": "新高-新低广度", "value": breadth_metrics.get("nhnlBreadth"), "unit": "%"},
            {"label": "均线上方广度", "value": breadth_metrics.get("aboveMaBreadth"), "unit": "%"},
            {"label": "60日净新高广度", "value": breadth_metrics.get("nhnlBreadth60"), "unit": "%"},
            {"label": "60日均线上方", "value": breadth_metrics.get("aboveMaBreadth60"), "unit": "%"},
            {"label": "60日广度确认", "value": breadth_diagnostics.get("breadth60Confirmation"), "unit": "分"},
            {
                "label": "60日状态",
                "value": None,
                "text": (
                    f"{breadth_diagnostics.get('cycleConfirmationLabel', '待生成')} · "
                    f"{breadth_diagnostics.get('breadth60AsOf', '—')}"
                ),
                "unit": "",
            },
            {
                "label": "价格—广度背离",
                "value": breadth_diagnostics.get("priceBreadthDivergence"),
                "unit": "分",
            },
            {
                "label": "背离状态",
                "value": None,
                "text": (
                    f"{breadth_diagnostics.get('priceBreadthDivergenceLabel', '待生成')} · "
                    f"{breadth_diagnostics.get('priceBreadthAsOf', '—')}"
                ),
                "unit": "",
            },
            {"label": "顶部风险", "value": breadth_diagnostics.get("topRisk"), "unit": "分"},
            {"label": "底部修复", "value": breadth_diagnostics.get("bottomRepair"), "unit": "分"},
            {
                "label": "前瞻观察",
                "value": None,
                "text": breadth_diagnostics.get("leadingSignal", "暂无明确拐点"),
                "unit": "",
            },
            {"label": "有效样本", "value": breadth_metrics.get("eligible"), "unit": "只"},
        ]
    else:
        breadth_submetrics = [
            {"label": "周期阶段", "value": None, "text": f"{breadth_cycle.get('phaseLabel', '—')} · {breadth_cycle.get('label', '—')}", "unit": ""},
            {"label": "涨跌广度", "value": breadth_components.get("advanceBreadth"), "unit": "分"},
            {"label": "涨跌停广度", "value": breadth_components.get("limitBreadth"), "unit": "分"},
        ]
    top5_history = next(
        (
            item.get("points", [])
            for item in rqdata.get("series", [])
            if item.get("id") == "top5-concentration"
        ),
        [],
    )
    top5_percentile = numeric(
        rqdata.get("top5ConcentrationPercentile250D")
    )
    if top5_percentile is None and top5_history:
        top5_values = [
            numeric(item.get("value"))
            for item in top5_history[-250:]
            if numeric(item.get("value")) is not None
        ]
        if top5_values:
            top5_percentile = percentile(top5_values, top5_values[-1])
    cards = [
        metric_card(
            "breadth-sentiment",
            "市场广度情绪",
            "RQData" if breadth_mode == "exact" else "市场情绪指标.xlsx",
            breadth_cycle.get("asOf"),
            value=breadth_cycle.get("score"),
            unit="分",
            note=(
                "RQData市场广度80%＋中证全指14日Wilder RSI（三日平滑）20%；随最近已完成交易日每日重算。顶部/底部观察阈值为68/33。"
                if breadth_mode == "exact"
                else "广度代理版：上涨家数占比40%、涨停减跌停30%、两项5日变化各15%；750日滚动分位、三日平滑。RQData真实广度缓存生成后会自动替换。"
            ),
            submetrics=breadth_submetrics,
        ),
        metric_card(
            "sentiment-cycle",
            "A股短线情绪周期",
            "市场情绪指标.xlsx",
            cycle.get("asOf"),
            value=cycle.get("score"),
            unit="分",
            note="样本外周期跟踪权重：趋势35%、市场广度20%、换手活跃度25%、融资15%、机构资金5%；三日平滑，仅作周期观察。",
            submetrics=[
                {"label": "周期阶段", "value": None, "text": f"{cycle.get('phaseLabel', '—')} · {cycle.get('label', '—')}", "unit": ""},
                {"label": "趋势", "value": cycle_components.get("trend"), "unit": "分"},
                {"label": "广度", "value": cycle_components.get("breadth"), "unit": "分"},
                {"label": "活跃度", "value": cycle_components.get("activity"), "unit": "分"},
                {"label": "融资", "value": cycle_components.get("financing"), "unit": "分"},
                {"label": "机构资金", "value": cycle_components.get("institutional"), "unit": "分"},
            ],
        ),
        metric_card(
            "medium-term-sentiment",
            "中期情绪指标",
            "市场宽基情绪指标.xlsx",
            medium_term_sentiment.get("asOf") if medium_term_sentiment else None,
            value=medium_term_sentiment.get("score") if medium_term_sentiment else None,
            unit="分",
            note=(
                "ERP、股债收益差、股债位置差、融资活跃度、20日融资净流入、"
                "60日融资余额变化、60日市场广度确认七项子指标等权平均"
            ),
            submetrics=[
                {
                    "label": "ERP",
                    "value": (medium_term_sentiment or {}).get("components", {}).get("erp"),
                    "unit": "分",
                },
                {
                    "label": "股债收益差",
                    "value": (medium_term_sentiment or {}).get("components", {}).get("spread"),
                    "unit": "分",
                },
                {
                    "label": "股债位置差",
                    "value": (medium_term_sentiment or {}).get("components", {}).get("position"),
                    "unit": "分",
                },
                {
                    "label": "融资活跃度",
                    "value": (medium_term_sentiment or {}).get("components", {}).get("financingActivity"),
                    "unit": "分",
                },
                {
                    "label": "20日融资净流入",
                    "value": (medium_term_sentiment or {}).get("components", {}).get("financingNet20D"),
                    "unit": "分",
                },
                {
                    "label": "60日融资余额变化",
                    "value": (medium_term_sentiment or {}).get("components", {}).get("financingBalanceChange60D"),
                    "unit": "分",
                },
                {
                    "label": "60日市场广度",
                    "value": (medium_term_sentiment or {}).get("components", {}).get("breadth60"),
                    "unit": "分",
                },
            ],
        ),
        metric_card(
            "market-turnover",
            "万得全A等权指数日频换手率",
            "RQData",
            rqdata.get("marketTurnoverAsOf") or rq_as_of,
            value=rqdata.get("marketTurnover"),
            unit="%",
            percentile_value=rqdata.get("marketTurnoverPercentile250D"),
            note="RQData逐股日换手率等权平均；历史分位基于近250个交易日，按最近已完成交易日日频增量更新。",
        ),
        metric_card(
            "top5-concentration",
            "成交额前5%个股占比",
            "RQData",
            rqdata.get("top5AsOf") or rq_as_of,
            value=rqdata.get("top5Concentration"),
            unit="%",
            percentile_value=top5_percentile,
            note="读取最近已完成交易日；历史分位基于最近250个交易日，之后每日增量更新。",
        ),
        metric_card(
            "ma-distance",
            "指数距100日均线",
            "RQData",
            rqdata.get("allShareDistance100dAsOf") or rq_as_of,
            note="正值表示指数位于100日均线上方；覆盖上证综指、沪深300与中证全指。",
            submetrics=[
                {"label": "上证综指", "value": rqdata.get("shCompositeDistance100d"), "unit": "%"},
                {"label": "沪深300", "value": rqdata.get("hs300Distance100d"), "unit": "%"},
                {"label": "中证全指", "value": rqdata.get("allShareDistance100d"), "unit": "%"},
            ],
        ),
        metric_card(
            "margin-financing",
            "融资与两融风险",
            "RQData",
            rqdata.get("financingAsOf") or rq_as_of,
            note="融资活跃度 = 沪深融资买入额 / 中证全指成交额。RQData不提供市场整体两融担保比例，以融资余额观察杠杆存量。",
            submetrics=[
                {"label": "融资净流入", "value": rqdata.get("financingNet"), "unit": "亿元"},
                {"label": "融资交易活跃度", "value": rqdata.get("financingActivity"), "unit": "%"},
                {"label": "融资余额", "value": rqdata.get("financingBalance"), "unit": "亿元"},
            ],
        ),
        metric_card(
            "institutional-net-buy",
            "机构主动买入净额",
            "市场情绪指标.xlsx",
            excel.get("institutionalAsOf") if excel else None,
            value=excel.get("institutionalNetBuy") if excel else None,
            unit="亿元",
            note="机构主动买入额减主动卖出额；正值表示机构资金净流入，负值表示净流出。",
            submetrics=[
                {"label": "当日", "value": excel.get("institutionalNetBuy") if excel else None, "unit": "亿元"},
                {"label": "近5日累计", "value": excel.get("institutionalNetBuy5D") if excel else None, "unit": "亿元"},
                {"label": "近20日累计", "value": excel.get("institutionalNetBuy20D") if excel else None, "unit": "亿元"},
            ],
        ),
        metric_card(
            "a-share-new-accounts",
            "A股新增开户数",
            "待接入",
            rqdata.get("newAshareAccountsAsOf") or rq_as_of,
            value=rqdata.get("newAshareAccounts"),
            unit="户",
            percentile_value=rqdata.get("newAshareAccountsPercentile250D"),
            note="已预留资金维度入口；当前RQData SDK未暴露清晰的新增投资者账户统计接口，取得数据后自动展示。",
            submetrics=[
                {"label": "当期新增", "value": rqdata.get("newAshareAccounts"), "unit": "户"},
                {"label": "近12期均值", "value": rqdata.get("newAshareAccountsMa12"), "unit": "户"},
            ],
        ),
        metric_card(
            "dragon-tiger-net-inflow",
            "龙虎榜资金净流入",
            "RQData",
            rq_as_of,
            value=rqdata.get("dragonTigerNetInflow20D"),
            unit="亿元",
            note="基于RQData龙虎榜明细买卖金额计算，主值为近20个龙虎榜披露交易日滚动净流入。",
            submetrics=[
                {"label": "20日滚动", "value": rqdata.get("dragonTigerNetInflow20D"), "unit": "亿元"},
                {"label": "上榜股票数", "value": rqdata.get("dragonTigerStockCount"), "unit": "只"},
            ],
        ),
        metric_card(
            "new-equity-fund-shares",
            "新成立偏股型基金份额",
            "市场宽基情绪指标.xlsx",
            new_equity_fund_shares.get("asOf") if new_equity_fund_shares else None,
            value=(
                new_equity_fund_shares.get("shares20D")
                if new_equity_fund_shares
                else None
            ),
            unit="亿份",
            percentile_value=(
                new_equity_fund_shares.get("shares20DPercentile")
                if new_equity_fund_shares
                else None
            ),
            note=(
                "读取“中国:新成立基金份额:偏股型”；主值为近20日累计，"
                "历史分位也按20日累计序列计算。"
            ),
            submetrics=[
                {
                    "label": "当日",
                    "value": (
                        new_equity_fund_shares.get("shares")
                        if new_equity_fund_shares
                        else None
                    ),
                    "unit": "亿份",
                },
                {
                    "label": "近5日累计",
                    "value": (
                        new_equity_fund_shares.get("shares5D")
                        if new_equity_fund_shares
                        else None
                    ),
                    "unit": "亿份",
                },
                {
                    "label": "近20日累计",
                    "value": (
                        new_equity_fund_shares.get("shares20D")
                        if new_equity_fund_shares
                        else None
                    ),
                    "unit": "亿份",
                },
                {
                    "label": "偏股基金指数月涨跌幅",
                    "value": rqdata.get("partialEquityFundIndexMonthlyReturn"),
                    "unit": "%",
                },
            ],
        ),
        metric_card(
            "stock-fund-position",
            "股票型基金股票投资仓位",
            "开放式基金估算股票投资比例.xlsx",
            open_fund_position.get("asOf") if open_fund_position else None,
            value=(
                open_fund_position.get("value")
                if open_fund_position
                else None
            ),
            unit="%",
            note=(
                "普通股票型基金估算仓位，按基金子份额规模加权；"
                "变动单位为百分点。"
            ),
            submetrics=[
                {
                    "label": "较上期",
                    "value": (
                        open_fund_position.get("change1D")
                        if open_fund_position
                        else None
                    ),
                    "unit": "pct",
                },
                {
                    "label": "较5日前",
                    "value": (
                        open_fund_position.get("change5D")
                        if open_fund_position
                        else None
                    ),
                    "unit": "pct",
                },
                {
                    "label": "较一月前",
                    "value": (
                        open_fund_position.get("change1M")
                        if open_fund_position
                        else None
                    ),
                    "unit": "pct",
                },
                {
                    "label": "中位数",
                    "value": (
                        open_fund_position.get("median")
                        if open_fund_position
                        else None
                    ),
                    "unit": "%",
                },
            ],
        ),
        metric_card(
            "broad-etf-flow",
            "宽基ETF资金流入 / 流出",
            "RQData",
            rq_as_of,
            value=rqdata.get("broadEtfFlow1D"),
            unit="亿元",
            note="ETF净流量 = 份额变化 × 收盘价；仅纳入境内A股规模/宽基ETF。",
            submetrics=[
                {"label": "当日", "value": rqdata.get("broadEtfFlow1D"), "unit": "亿元"},
                {"label": "近5日", "value": rqdata.get("broadEtfFlow5D"), "unit": "亿元"},
                {"label": "近20日", "value": rqdata.get("broadEtfFlow20D"), "unit": "亿元"},
            ],
        ),
    ]

    broad_market_index_series = (
        broad_market_indices.get("series", [])
        if broad_market_indices
        else []
    )
    broad_market_index_ids = {
        item.get("id")
        for item in broad_market_index_series
        if item.get("id")
    }
    series = [
        item
        for item in (excel.get("series", []) if excel else [])
        if item.get("id") not in {
            "market-turnover",
            "windall-ma100",
            "sh-ma100",
            "financing-net",
            "financing-activity",
            "financing-balance",
            *broad_market_index_ids,
        }
    ]
    excel_turnover_series = (
        broad_market_turnover.get("series", [])
        if broad_market_turnover
        else []
    )
    excel_turnover_ids = {
        item.get("id")
        for item in excel_turnover_series
        if item.get("id")
    }
    rq_series_for_page = (
        [
            item
            for item in rqdata.get("series", [])
            if item.get("id") not in {
                "sse50-close",
                "star50-close",
                "new-equity-fund-shares",
                "medium-term-sentiment",
                "medium-erp-score",
                "medium-yield-spread-score",
                "medium-position-score",
                "medium-financing-activity-score",
                "medium-financing-net-20d-score",
                "medium-financing-balance-change-60d-score",
                "medium-breadth60-score",
                "medium-erp",
                "medium-equity-bond-position",
                "medium-equity-bond-relative-return-120d",
                "medium-equity-bond-yield-spread",
                "medium-financing-balance",
                "medium-financing-activity",
                "medium-financing-net-20d",
                "medium-financing-balance-change-60d",
                "medium-dividend-yield-ttm",
                "medium-cdb-10y-yield",
                "land-connect-net-inflow-ma20",
                "land-connect-turnover-ma20",
                *excel_turnover_ids,
            }
        ]
        if isinstance(rqdata.get("series"), list)
        else []
    )
    series.extend(rq_series_for_page)
    series.extend(exact_breadth.get("series", []) if isinstance((exact_breadth or {}).get("series"), list) else [])
    if derivatives_pcr:
        series.extend(derivatives_pcr.get("series", []))
    if margin_risk_excel:
        series.extend(margin_risk_excel.get("series", []))
    if new_equity_fund_shares:
        series.extend(new_equity_fund_shares.get("series", []))
    if medium_term_sentiment:
        series.extend(medium_term_sentiment.get("series", []))
    series.extend(broad_market_index_series)
    series.extend(excel_turnover_series)
    if land_connect_turnover:
        series.extend(land_connect_turnover.get("series", []))
    if open_fund_position and len(open_fund_position.get("points", [])) > 1:
        series.append(
            {
                "id": "stock-fund-position",
                "name": "股票型基金股票投资仓位",
                "unit": "%",
                "points": open_fund_position["points"],
            }
        )
    diagnostic_points = [
        {
            "date": item["date"],
            "value": item.get("diagnostics", {}).get("priceBreadthDivergence"),
        }
        for item in breadth_cycle.get("points", [])
        if numeric(item.get("diagnostics", {}).get("priceBreadthDivergence")) is not None
    ]
    if diagnostic_points:
        series.append({
            "id": "price-breadth-divergence",
            "name": "价格—广度背离",
            "unit": "分",
            "points": diagnostic_points,
        })
    available = sum(card["status"] == "available" for card in cards)
    missing = len(cards) - available

    positive = []
    negative = []
    if numeric(rqdata.get("allShareDistance100d")) is not None:
        (positive if rqdata["allShareDistance100d"] >= 0 else negative).append("中证全指位于100日均线%s" % ("上方" if rqdata["allShareDistance100d"] >= 0 else "下方"))
    if numeric(rqdata.get("financingNet")) is not None:
        (positive if rqdata["financingNet"] >= 0 else negative).append("融资资金%s" % ("净流入" if rqdata["financingNet"] >= 0 else "净流出"))
    turnover_percentile = numeric(rqdata.get("marketTurnoverPercentile250D"))
    if turnover_percentile is not None:
        if turnover_percentile >= 70:
            positive.append("换手率处于近250日较高位置")
        elif turnover_percentile <= 30:
            negative.append("换手率处于近250日较低位置")

    derivatives_as_of = derivatives_pcr.get("asOf") if derivatives_pcr else None
    as_of_candidates = [
        value for value in (excel_as_of, rq_as_of, derivatives_as_of) if value
    ]
    as_of = max(as_of_candidates) if as_of_candidates else None
    sources = [
        source_record("市场情绪指标.xlsx", "available" if excel else "unavailable", excel_as_of, excel.get("path") if excel else "读取失败"),
        source_record(
            "开放式基金估算股票投资比例.xlsx",
            "available" if open_fund_position else "unavailable",
            open_fund_position.get("asOf") if open_fund_position else None,
            (
                open_fund_position.get("path")
                if open_fund_position
                else "读取失败"
            ),
        ),
        source_record(
            "市场宽基情绪指标.xlsx",
            "available" if derivatives_pcr else "unavailable",
            derivatives_as_of,
            derivatives_pcr.get("path") if derivatives_pcr else "读取失败",
        ),
        source_record("RQData", "available" if rqdata.get("asOf") else "unavailable", rq_as_of, rq_error or "本机 RQSDK 计算缓存"),
        source_record(
            "RQData逐股广度",
            "available" if breadth_mode == "exact" else "unavailable",
            exact_breadth.get("asOf") if exact_breadth else None,
            "20/60日新高-新低、均线上方广度及价格—广度背离" if exact_breadth else "尚未生成；当前使用Excel代理广度",
        ),
    ]

    payload = {
        "title": "A股宽基情绪指标",
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "asOf": as_of,
        "availableCount": available,
        "missingCount": missing,
        "summary": {
            "headline": "；".join(positive + negative) if positive or negative else "当前可用数据不足以形成方向判断",
            "positive": positive,
            "negative": negative,
        },
        "cards": cards,
        "series": series,
        "etfDetails": rqdata.get("etfDetails", []) if isinstance(rqdata.get("etfDetails"), list) else [],
        "cycleComparison": {
            "title": "短期情绪指标",
            "description": (
                f"左轴为0–100市场情绪分：RQData市场广度80%＋{benchmark_label}14日Wilder RSI（三日平滑）20%；每天按最近已完成交易日重算。"
                if breadth_mode == "exact" and benchmark_label
                else "0–100广度情绪分；使用750日滚动分位和三日平滑。Excel恢复后自动叠加万得全A。"
            ),
            "priceLabel": benchmark_label,
            "score": breadth_cycle.get("score"),
            "label": breadth_cycle.get("label"),
            "phase": breadth_cycle.get("phase"),
            "phaseLabel": breadth_cycle.get("phaseLabel"),
            "asOf": breadth_cycle.get("asOf"),
            "weights": breadth_cycle.get("weights", {}),
            "diagnostics": breadth_cycle.get("diagnostics", {}),
            "points": breadth_cycle.get("points", []),
            "sourceMode": breadth_mode,
        },
        "sources": sources,
        "notes": notes,
    }
    payload = apply_market_data_sync(payload, BASE_DIR)
    save_page_cache(payload)
    return payload


def _refresh_page_cache_in_background():
    try:
        _build_payload()
    except Exception as exc:
        print(f"宽基情绪后台缓存更新失败：{exc}")
    finally:
        PAYLOAD_BUILD_LOCK.release()


def build_payload():
    signature = source_signature()
    cached_payload = load_page_cache(signature)
    if cached_payload is not None:
        return cached_payload

    stale_payload = load_stale_page_cache(signature)
    if stale_payload is not None:
        if PAYLOAD_BUILD_LOCK.acquire(blocking=False):
            threading.Thread(
                target=_refresh_page_cache_in_background,
                daemon=True,
            ).start()
        return stale_payload

    with PAYLOAD_BUILD_LOCK:
        cached_payload = load_page_cache(source_signature())
        return cached_payload if cached_payload is not None else _build_payload()
