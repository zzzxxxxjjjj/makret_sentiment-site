from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from retired_provider import client as rq

from rqdata_connection import initialize_rqdata
from openpyxl import load_workbook
from retired_provider import client as fund


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL = Path(
    r"C:\Wind\Wind.NET.Client\WindNET\tmp\开放式基金估算股票投资比例20260729(3).xlsx"
)
LOCAL_EXCEL = BASE_DIR / "open-fund-stock-position.xlsx"


def batches(items, size=250):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def read_stock_fund_codes(path):
    workbook = load_workbook(path, data_only=True, read_only=True)
    worksheet = workbook["sheet1"]
    codes = []
    for row in worksheet.iter_rows(
        min_row=3,
        max_row=worksheet.max_row,
        min_col=1,
        max_col=21,
        values_only=True,
    ):
        if str(row[20] or "").strip() != "普通股票型基金":
            continue
        code = str(row[1] or "").strip().split(".")[0]
        if code:
            codes.append(code)
    workbook.close()
    return sorted(set(codes))


def main_codes(codes):
    mapping = {}
    for group in batches(codes):
        related = fund.get_related_code(group)
        if related is None or related.empty:
            continue
        related = related.reset_index(drop=True)
        for row in related.to_dict("records"):
            primary = str(row.get("main_code") or "").strip().split(".")[0]
            secondary = str(row.get("related_code") or "").strip().split(".")[0]
            if primary and secondary:
                mapping[secondary] = primary
                mapping.setdefault(primary, primary)
    return sorted({mapping.get(code, code) for code in codes})


def load_history(codes, start_date):
    frames = []
    for group in batches(codes):
        allocation = fund.get_asset_allocation(group)
        if allocation is None or allocation.empty:
            continue
        frame = allocation.reset_index()
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
        frame["stock"] = pd.to_numeric(frame["stock"], errors="coerce")
        frame["net_asset"] = pd.to_numeric(frame["net_asset"], errors="coerce")
        frame = frame[
            (frame["datetime"] >= pd.Timestamp(start_date))
            & frame["stock"].notna()
            & frame["net_asset"].notna()
            & (frame["net_asset"] > 0)
        ]
        if not frame.empty:
            frames.append(frame[["order_book_id", "datetime", "stock", "net_asset"]])
    if not frames:
        return []

    data = pd.concat(frames, ignore_index=True)
    data = data.drop_duplicates(["order_book_id", "datetime"], keep="last")
    data["weighted_stock"] = data["stock"] * data["net_asset"]
    grouped = data.groupby("datetime", as_index=False).agg(
        weighted_stock=("weighted_stock", "sum"),
        total_weight=("net_asset", "sum"),
    )
    grouped["value"] = grouped["weighted_stock"] / grouped["total_weight"] * 100
    grouped = grouped.sort_values("datetime")
    return [
        {
            "date": row.datetime.date().isoformat(),
            "value": round(float(row.value), 3),
        }
        for row in grouped.itertuples()
    ]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cloud-universe", action="store_true")
    parser.add_argument("--excel", default=str(DEFAULT_EXCEL))
    parser.add_argument(
        "--output",
        default=str(BASE_DIR / "rqdata-fund-stock-position-history.json"),
    )
    parser.add_argument("--start", default="2021-07-01")
    return parser.parse_args()


def run():
    args = parse_args()
    initialize_rqdata()
    excel_path = Path(args.excel)
    if args.cloud_universe:
        instruments = fund.all_instruments()
        stock_codes = instruments.loc[instruments.fund_type == 'Stock', 'order_book_id'].astype(str).tolist()
    else:
        if not excel_path.exists(): excel_path = LOCAL_EXCEL
        stock_codes = read_stock_fund_codes(excel_path)
    if not stock_codes: raise RuntimeError('No ordinary stock funds returned')
    primary_codes = main_codes(stock_codes)
    points = load_history(primary_codes, args.start)
    if not points:
        raise RuntimeError("RQData 未返回基金历史资产配置")

    payload = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "RQData基金定期报告资产配置",
        "universe": "RQData普通股票型基金主代码去重" if args.cloud_universe else excel_path.name,
        "frequency": "quarterly",
        "start": args.start,
        "end": points[-1]["date"],
        "fundCount": len(primary_codes),
        "points": points,
    }
    output_path = Path(args.output)
    temporary = output_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output_path)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "fundCount": len(primary_codes),
                "pointCount": len(points),
                "start": points[0]["date"],
                "end": points[-1]["date"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    run()
