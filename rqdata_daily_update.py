"""Refresh core snapshots as one validated, completed-trading-day batch."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


def refresh_core_snapshots(trade_date, *, directory=BASE_DIR):
    directory = Path(directory)
    env = {**os.environ, "RQDATA_AS_OF": trade_date}
    # Stage all outputs, preserving previous files until every date is verified.
    with tempfile.TemporaryDirectory(prefix=".rqdata-refresh-", dir=directory) as temporary:
        staging = Path(temporary)
        for script, filename, extra in CORE_UPDATES:
            source, target = directory / filename, staging / filename
            if source.is_file():
                shutil.copy2(source, target)
            if read_snapshot(target).get("asOf") == trade_date:
                print(f"Already current: {filename} ({trade_date})", flush=True)
                continue
            print(f"Refreshing {filename} for {trade_date}", flush=True)
            completed = subprocess.run(
                [sys.executable, str(BASE_DIR / script), "--output", str(target), *extra],
                cwd=directory, env=env, capture_output=True, text=True, timeout=1800,
            )
            if completed.returncode:
                detail = (completed.stderr or completed.stdout).strip()[-700:]
                raise RuntimeError(f"{script} failed; previous snapshots retained. "
                                   f"{safe_error(RuntimeError(detail))}")
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
    import rqdatac as rq
    initialize_rqdata()
    target = completed_trading_date(rq).isoformat()
    refresh_core_snapshots(target)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(safe_error(exc), file=sys.stderr)
        sys.exit(1)
