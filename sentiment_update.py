"""Force synthesis after refreshing inputs and expose lagging components."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from rqdata_trading_day import CHINA_TIME

BASE_DIR = Path(__file__).resolve().parent


def synthesis_status(payload, target):
    by_id = {s['id']: s for s in payload.get('series', [])}
    short = payload.get('cycleComparison', {})
    medium = by_id.get('medium-term-sentiment', {})
    inputs = {}
    for sid in ('medium-erp-score', 'medium-yield-spread-score', 'medium-position-score',
                'medium-financing-activity-score', 'medium-financing-net-20d-score',
                'medium-financing-balance-change-60d-score', 'medium-breadth60-score'):
        dates = [p['date'] for p in by_id.get(sid, {}).get('points', []) if p.get('value') is not None]
        inputs[sid] = max(dates, default=None)
    short_date = max((p['date'] for p in short.get('points', []) if p.get('sentiment') is not None), default=None)
    medium_date = max((p['date'] for p in medium.get('points', []) if p.get('value') is not None), default=None)
    return {'targetDate': target, 'shortTerm': {'asOf': short_date, 'current': short_date == target},
            'mediumTerm': {'asOf': medium_date, 'current': medium_date == target, 'inputs': inputs,
                           'laggingInputs': [sid for sid, dt in inputs.items() if dt != target]}}


def rebuild(target, *, strict=True):
    import broad_sentiment as broad
    os.environ['RQDATA_AS_OF'] = target
    broad.ENABLE_RQDATA_REFRESH = False
    payload = broad._build_payload(force=True)
    status = synthesis_status(payload, target)
    payload['synthesisStatus'] = status
    broad.save_page_cache(payload)
    (BASE_DIR/'synthesis-status.json').write_text(json.dumps({
        'checkedAt': datetime.now(CHINA_TIME).isoformat(timespec='seconds'), **status}, ensure_ascii=True), encoding='utf-8')
    if not status['shortTerm']['current']:
        raise ValueError(f'Short-term synthesis is not current: {status["shortTerm"]["asOf"]}, expected {target}')
    if strict and not status['mediumTerm']['current']:
        raise ValueError(f'Medium-term synthesis is not current: {status["mediumTerm"]}')
    return status


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--allow-delayed-medium', action='store_true')
    args = parser.parse_args()
    print(json.dumps(rebuild(args.as_of, strict=not args.allow_delayed_medium), ensure_ascii=True))
