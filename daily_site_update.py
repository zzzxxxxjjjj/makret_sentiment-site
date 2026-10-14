"""Local daily chain: Wind refresh -> RQData -> saved inputs -> verified synthesis."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from rqdata_connection import initialize_rqdata, safe_error
from rqdata_daily_update import refresh_core_snapshots
from rqdata_trading_day import CHINA_TIME, completed_trading_date
from sentiment_update import rebuild

BASE_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh-excel', action='store_true')
    args = parser.parse_args()
    import rqdatac as rq
    initialize_rqdata()
    target = completed_trading_date(rq).isoformat()
    os.environ['RQDATA_AS_OF'] = target
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    report = {'targetDate': target, 'startedAt': datetime.now(CHINA_TIME).isoformat(timespec='seconds'), 'stages': []}
    def stage(name, command, *, required=True):
        print(f'Updating {name}', flush=True)
        result = subprocess.run(command, cwd=BASE_DIR, env=env, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=1800)
        report['stages'].append({'name': name, 'ok': result.returncode == 0, 'required': required})
        if result.returncode:
            print(safe_error(RuntimeError(result.stderr or result.stdout)), flush=True)
        return result.returncode == 0
    try:
        if args.refresh_excel:
            import broad_sentiment as broad
            source = broad.resolve_broad_market_excel()
            stage('Wind Excel refresh', ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                  str(BASE_DIR/'refresh_excel_sources.ps1'), '-MarketWorkbook', str(source)])
        refresh_core_snapshots(target)
        for script, output in [('rqdata_late_market_refresh.py', 'rqdata-broad-sentiment.json'),
                               ('rqdata_options_refresh.py', 'rqdata-options-pcr.json'),
                               ('wind_market_refresh.py', 'wind-market-supplement.json'),
                               ('wind_synthesis_refresh.py', 'wind-synthesis-inputs.json')]:
            stage(script, [sys.executable, '-X', 'utf8', str(BASE_DIR/script), '--output', output])
        for script, output in [('rqdata_second_industry_flow_refresh.py','rqdata-industry-sentiment.json'),
                               ('rqdata_fund_position_refresh.py','rqdata-fund-stock-position-history.json'),
                               ('rqdata_fund_exposure_refresh.py','rqdata-fund-exposure.json')]:
            stage(script, [sys.executable, '-X', 'utf8', str(BASE_DIR/script), '--output', output], required=False)
        report['synthesis'] = rebuild(target)
        stage('Static build', [sys.executable, '-X', 'utf8', str(BASE_DIR/'build_static_site.py')])
        report['ok'] = all(s['ok'] for s in report['stages'] if s['required'])
    except Exception as exc:
        report['ok'] = False
        report['error'] = safe_error(exc)
        raise
    finally:
        (BASE_DIR/'daily-update-status.json').write_text(json.dumps(report, ensure_ascii=True), encoding='utf-8')
    if not report['ok']:
        raise RuntimeError('Some daily stages failed; see daily-update-status.json')


if __name__ == '__main__':
    lock = BASE_DIR/'.daily-site-update.lock'
    if lock.exists() and time.time()-lock.stat().st_mtime > 4*3600:
        lock.unlink()
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit('Another daily update is already running')
    try:
        os.close(descriptor)
        main()
    finally:
        lock.unlink(missing_ok=True)
