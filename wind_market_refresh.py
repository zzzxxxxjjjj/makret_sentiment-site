"""Export saved Wind workbook values for static publication; never launch Wind."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import broad_sentiment as broad
from rqdata_trading_day import CHINA_TIME


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(broad.BASE_DIR / "wind-market-supplement.json"))
    args = parser.parse_args()
    # Resolver copies a newer saved original into the project, with a locked-file fallback.
    broad.resolve_broad_market_excel()
    shares = broad.broad_market_new_equity_fund_shares_snapshot()
    connect = broad.broad_market_excel_land_connect_turnover_snapshot()
    series = []
    for snapshot in (shares, connect):
        if not snapshot.get("series") or not snapshot.get("asOf"):
            raise ValueError("Wind workbook has no valid saved observations; existing export retained")
        cutoff = (datetime.fromisoformat(snapshot["asOf"]).date() - timedelta(days=120)).isoformat()
        for item in snapshot["series"]:
            series.append({**item, "source": "Wind��� �� �г���������ָ��.xlsx",
                           "points": [p for p in item["points"] if p["date"] >= cutoff]})
    payload = {"source": "Wind��� �� �г���������ָ��.xlsx",
               "exportedAt": datetime.now(CHINA_TIME).isoformat(timespec="seconds"),
               "series": series,
               "fundShares": {k: v for k, v in shares.items() if k not in {"path", "series"}}}
    path = Path(args.output)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    print(f"Saved Wind values exported: fund shares {shares['asOf']}; stock connect {connect['asOf']}")


if __name__ == "__main__":
    main()
