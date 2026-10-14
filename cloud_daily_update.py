"""Refresh RQData snapshots and rebuild the dashboard on a GitHub runner.

Authentication is provided by the RQDATAC_CONF environment variable, never files.
This script does not commit, push, or publish; the workflow performs those steps
only after the complete refresh and static build succeed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from rqdata_connection import initialize_rqdata, safe_error
from rqdata_trading_day import completed_trading_date
from rqdata_daily_update import CORE_UPDATES, refresh_core_snapshots
from sentiment_update import rebuild


BASE_DIR = Path(__file__).resolve().parent
UPDATED_FILES = (
    "rqdata-broad-sentiment.json", "rqdata-breadth-sentiment.json",
    "rqdata-industry-sentiment.json", "rqdata-fund-stock-position-history.json",
    "rqdata-fund-exposure.json", "broad-sentiment-page-cache.json",
    "rqdata-options-pcr.json",
)


def read_cache(filename):
    try:
        value = json.loads((BASE_DIR / filename).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def caches_current(trade_date):
    return all(read_cache(filename).get("asOf") == trade_date for _, filename, _ in CORE_UPDATES)


def run_stage(script, arguments, *, required=True):
    print(f"Running {script}", flush=True)
    # Capture provider logs so credentials are not inadvertently echoed.
    try:
        completed = subprocess.run(
            [sys.executable, str(BASE_DIR / script), *arguments],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}, timeout=1800,
        )
    except subprocess.TimeoutExpired:
        if required:
            raise
        print(f"Optional update skipped: {script} (timeout)", flush=True)
        return False
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[-700:]
        if detail:
            print(safe_error(RuntimeError(detail)), file=sys.stderr, flush=True)
        message = f"{script} failed (exit {completed.returncode}); previous published version retained"
        if required:
            raise RuntimeError(message)
        print(f"Optional update skipped: {script} (exit {completed.returncode})", flush=True)
        return False
    return True


def verify_core_dates(trade_date):
    for _, filename, _ in CORE_UPDATES:
        value = read_cache(filename)
        if value.get("asOf") != trade_date:
            raise ValueError(
                f"{filename} trading date mismatch: expected {trade_date}, "
                f"actual {value.get('asOf', 'missing')}"
            )
    if not read_cache("rqdata-breadth-sentiment.json").get("points"):
        raise ValueError("Market breadth snapshot is empty")
    if not read_cache("rqdata-industry-sentiment.json").get("industries"):
        raise ValueError("Industry snapshot is empty")


def main():
    if not os.environ.get("RQDATAC_CONF", "").strip():
        raise ValueError("Set the GitHub Actions secret RQDATAC_CONF before running this workflow")
    import rqdatac as rq

    print("Stage: initialize RQData connection", flush=True)
    initialize_rqdata()
    print("Stage: read completed trading date", flush=True)
    trade_date = completed_trading_date(rq).isoformat()
    # Freeze the target for every subprocess, even if the run crosses midnight.
    os.environ["RQDATA_AS_OF"] = trade_date
    print(f"Target completed trading date: {trade_date} (Asia/Shanghai)", flush=True)
    if caches_current(trade_date):
        print("Core snapshots current; retry supplementary data and rebuild dashboard")
    else:
        refresh_core_snapshots(trade_date)
    verify_core_dates(trade_date)

    # These supplementary services may not be included in every RQData license.
    run_stage("rqdata_late_market_refresh.py", ("--output", "rqdata-broad-sentiment.json"), required=False)
    run_stage("rqdata_options_refresh.py", ("--output", "rqdata-options-pcr.json"), required=False)
    run_stage("rqdata_second_industry_flow_refresh.py",
              ("--output", "rqdata-industry-sentiment.json"), required=False)
    if (BASE_DIR / "open-fund-stock-position.xlsx").is_file():
        run_stage("rqdata_fund_position_refresh.py",
                  ("--excel", "open-fund-stock-position.xlsx", "--output",
                   "rqdata-fund-stock-position-history.json", "--start", "2021-07-01"),
                  required=False)
    if os.environ.get("AIDO_API_KEY", "").strip():
        run_stage("rqdata_fund_exposure_refresh.py",
                  ("--output", "rqdata-fund-exposure.json"), required=False)
    else:
        print("AIDO_API_KEY not configured; fund exposure retains its actual prior date", flush=True)

    import broad_sentiment
    broad_sentiment.ENABLE_RQDATA_REFRESH = False
    # Synchronous generation avoids publishing an old payload while background
    # calculation is still in progress. The changed source signatures invalidate
    # the previous page cache without deleting it.
    payload = broad_sentiment._build_payload(force=True)
    if payload.get("asOf") != trade_date or not payload.get("cards") or not payload.get("series"):
        raise ValueError("Dashboard rebuild failed to include the new trading date")
    from sentiment_update import synthesis_status
    status = synthesis_status(payload, trade_date)
    if not status['shortTerm']['current']:
        raise ValueError('Short-term synthesis did not reach the completed trading date')
    payload['synthesisStatus'] = status
    broad_sentiment.save_page_cache(payload)
    print(json.dumps(status, ensure_ascii=True), flush=True)
    print(f"RQData snapshots and dashboard ready for {trade_date}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Cloud refresh failed: {safe_error(exc)}", file=sys.stderr)
        sys.exit(1)
