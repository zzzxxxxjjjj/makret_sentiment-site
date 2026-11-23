"""Refresh core snapshots as one validated, completed-trading-day batch."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path

from rqdata_connection import initialize_rqdata, safe_error
from rqdata_trading_day import completed_trading_date

BASE_DIR = Path(__file__).resolve().parent
CORE_UPDATES = (
    ("rqdata_refresh.py", "rqdata-broad-sentiment.json", ()),
    ("rqdata_breadth_refresh.py", "rqdata-breadth-sentiment.json", ("--start", "2018-01-01")),
    ("rqdata_industry_refresh.py", "rqdata-industry-sentiment.json", ()),
)


def read_snapshot(path):
    try:
        data = Path(path).read_text(encoding="utf-8")
        value = json.loads(data)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def snapshot_current(filename,value,trade_date):
    if value.get('asOf')!=trade_date:return False
    if filename=='rqdata-industry-sentiment.json':
        rows=[row for row in value.get('industries',[]) if isinstance(row,dict) and row.get('name')!='综合']
        if not rows:return False
        for row in rows:
            current=next((point for point in reversed(row.get('series',[])) if point.get('date')==trade_date),{})
            if any(current.get(metric) is None for metric in ('netFlow','marginActivity','amountShare')):return False
            if row.get('valuationAsOf')!=trade_date:return False
    if filename=='rqdata-breadth-sentiment.json':
        points=value.get('points',[])
        return bool(points) and isinstance(points[-1],dict) and points[-1].get('date')==trade_date
    return True


def verify_snapshots(directory, trade_date):
    for _, filename, _ in CORE_UPDATES:
        value = read_snapshot(Path(directory) / filename)
        if value.get("asOf") != trade_date:
            raise ValueError(f"{filename} trading date mismatch: expected {trade_date}, "
                             f"actual {value.get('asOf', 'missing')}")
        if filename == "rqdata-breadth-sentiment.json" and not value.get("points"):
            raise ValueError("Market breadth snapshot is empty")
        if filename == "rqdata-industry-sentiment.json" and not value.get("industries"):
            raise ValueError("Industry snapshot is empty")


def refresh_independent_snapshots(trade_date, directory):
    errors=[]
    for script,filename,extra in CORE_UPDATES:
        if snapshot_current(filename,read_snapshot(Path(directory)/filename),trade_date):
            continue
        with tempfile.TemporaryDirectory(prefix='.rqdata-source-',dir=directory) as temporary:
            target=Path(temporary)/filename
            source=Path(directory)/filename
            checkpoint=BASE_DIR/'.rqdata-cache/checkpoints'/trade_date/filename
            if checkpoint.is_file() and snapshot_current(filename,read_snapshot(checkpoint),trade_date):
                shutil.copy2(checkpoint,source)
                continue
            if source.is_file():shutil.copy2(source,target)
            try:
                remaining=float(os.environ.get('RQDATA_RUN_DEADLINE','inf'))-time.time()-15
                if remaining<5:raise TimeoutError('Morning publication budget exhausted')
                result=subprocess.run([sys.executable,str(BASE_DIR/script),'--output',str(target),*extra],cwd=directory,
                    capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=min(1500,remaining),
                    env={**os.environ,'RQDATA_AS_OF':trade_date,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
                value=read_snapshot(target)
                if result.returncode or value.get('asOf')!=trade_date:
                    raise ValueError((result.stderr or result.stdout)[-1200:] or 'Source did not reach target trading date')
                if filename=='rqdata-breadth-sentiment.json' and not value.get('points'):raise ValueError('Empty breadth')
                if filename=='rqdata-industry-sentiment.json' and not value.get('industries'):raise ValueError('Empty industries')
                target.replace(source)
            except Exception as error:
                errors.append({'source':filename,'error':safe_error(error)})
                print('Source delayed: '+filename,flush=True)
    return errors


def refresh_core_snapshots(trade_date, *, directory=BASE_DIR, allow_partial=False):
    if allow_partial:
        return refresh_independent_snapshots(trade_date,Path(directory))
    directory = Path(directory)
    env = {**os.environ, "RQDATA_AS_OF": trade_date, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    # Stage all outputs, preserving previous files until every date is verified.
    with tempfile.TemporaryDirectory(prefix=".rqdata-refresh-", dir=directory) as temporary:
        staging = Path(temporary)
        for script, filename, extra in CORE_UPDATES:
            source, target = directory / filename, staging / filename
            if source.is_file():
                shutil.copy2(source, target)
            checkpoint = BASE_DIR/'.rqdata-cache/checkpoints'/trade_date/filename
            checkpointing = os.environ.get('RQDATA_CHECKPOINTS') == '1'
            if checkpointing and read_snapshot(checkpoint).get('asOf') == trade_date:
                shutil.copy2(checkpoint, target)
            if snapshot_current(filename,read_snapshot(target),trade_date):
                print(f"Already current: {filename} ({trade_date})", flush=True)
                continue
            print(f"Refreshing {filename} for {trade_date}", flush=True)
            completed = subprocess.run(
                [sys.executable, str(BASE_DIR / script), "--output", str(target), *extra],
                cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
            )
            if completed.returncode:
                detail = (completed.stderr or completed.stdout).strip()[-700:]
                raise RuntimeError(f"{script} failed; previous snapshots retained. "
                                   f"{safe_error(RuntimeError(detail))}")
            if checkpointing and read_snapshot(target).get('asOf') == trade_date:
                checkpoint.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(target,checkpoint)
        verify_snapshots(staging, trade_date)
        # Keep rollback copies for replacement errors as well as script errors.
        originals = {filename: (directory / filename).read_bytes()
                     if (directory / filename).is_file() else None
                     for _, filename, _ in CORE_UPDATES}
        try:
            for _, filename, _ in CORE_UPDATES:
                (staging / filename).replace(directory / filename)
        except OSError:
            for filename, content in originals.items():
                path = directory / filename
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            raise
    print(f"Core snapshots verified: {trade_date}", flush=True)


def main():
    from retired_provider import client as rq
    initialize_rqdata()
    target = completed_trading_date(rq).isoformat()
    refresh_core_snapshots(target)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(safe_error(exc), file=sys.stderr)
        sys.exit(1)
