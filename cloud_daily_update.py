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
import time
from pathlib import Path

from rqdata_connection import initialize_rqdata, safe_error
from rqdata_trading_day import completed_trading_date
from rqdata_daily_update import CORE_UPDATES, refresh_core_snapshots, snapshot_current
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
    return all(snapshot_current(filename,read_cache(filename),trade_date) for _, filename, _ in CORE_UPDATES)


def run_stage(script, arguments, *, required=True):
    print(f"Running {script}", flush=True)
    deadline=float(os.environ.get('RQDATA_RUN_DEADLINE','inf'))
    remaining=deadline-time.time()-15
    if remaining<5:
        if required:raise TimeoutError('Morning publication budget exhausted')
        print('Retry postponed to protect morning publication: '+script,flush=True)
        return False
    timeout=min(900,remaining)
    # Capture provider logs so credentials are not inadvertently echoed.
    try:
        completed = subprocess.run(
            [sys.executable, str(BASE_DIR / script), *arguments],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}, timeout=timeout,
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
    import rqdatac as rq

    print("Stage: initialize RQData connection", flush=True)
    initialize_rqdata()
    print("Stage: read completed trading date", flush=True)
    trade_date = completed_trading_date(rq).isoformat()
    # Freeze the target for every subprocess, even if the run crosses midnight.
    os.environ["RQDATA_AS_OF"] = trade_date
    print(f"Target completed trading date: {trade_date} (Asia/Shanghai)", flush=True)
    from datetime import datetime, time as clock_time
    from rqdata_trading_day import CHINA_TIME
    now=datetime.now(CHINA_TIME)
    if clock_time(6,0)<=now.time()<clock_time(9,30):
        deadline=now.replace(hour=9,minute=22,second=0,microsecond=0)
        os.environ['RQDATA_RUN_DEADLINE']=str(deadline.timestamp())
    errors=[]
    if caches_current(trade_date):
        print("Core snapshots current; retry supplementary data and rebuild dashboard")
    else:
        errors=refresh_core_snapshots(trade_date, allow_partial=True) or []
    if not errors:
        verify_core_dates(trade_date)
    run_stage("cloud_market_refresh.py", (), required=False)
    run_stage("rotation_history_refresh.py", ("--output", "rqdata-industry-rotation.json"), required=False)

    # These supplementary services may not be included in every RQData license.
    run_stage("rqdata_late_market_refresh.py", ("--output", "rqdata-broad-sentiment.json"), required=False)
    run_stage("rqdata_options_refresh.py", ("--output", "rqdata-options-pcr.json"), required=False)
    run_stage("rqdata_second_industry_flow_refresh.py",
              ("--output", "rqdata-industry-sentiment.json"), required=False)
    run_stage("rqdata_fund_position_refresh.py",
              ("--cloud-universe", "--output", "rqdata-fund-stock-position-history.json", "--start", "2021-07-01"),
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
    if not payload.get("cards") or not payload.get("series"):
        raise ValueError("Dashboard rebuild returned no indicators")
    from sentiment_update import synthesis_status
    status = synthesis_status(payload, trade_date)
    if not status['shortTerm']['current']:
        errors.append({'source':'shortTerm','error':'Short-term synthesis did not reach target date'})
    payload['synthesisStatus'] = status
    broad_sentiment.save_page_cache(payload)
    print(json.dumps(status, ensure_ascii=True), flush=True)
    from data_freshness import write_report
    from datetime import date, timedelta
    calendar=[str(item)[:10] for item in rq.get_trading_dates(date.fromisoformat(trade_date)-timedelta(days=90),date.fromisoformat(trade_date)+timedelta(days=90))]
    report=write_report(trade_date,errors=errors,calendar=calendar)
    print(f"Daily readiness: {report['currentDailyCount']}/{report['dailyCount']} metrics for {trade_date}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Cloud refresh failed: {safe_error(exc)}", file=sys.stderr)
        sys.exit(1)
