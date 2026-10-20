"""Fetch validated AIDO style crowding; never alter timing scores or positions."""
from __future__ import annotations

import argparse
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from rqdata_fund_exposure_refresh import resolve_api_key

FIELDS = ('crowding_score', 'crowding_pct', 'structure_z', 'turnover_z', 'trend_z', 'valuation_z')
CODES = {'SIZE', 'MIDCAP', 'GROWTH', 'VALUE', 'DIVYILD', 'BETA', 'RESVOL', 'MOMENTUM',
         'EARNQLTY', 'EARNVAR', 'INVSQLTY', 'LEVERAGE', 'LIQUIDITY', 'LTREVRSL', 'Other', 'PROFIT'}


def band(score):
    if score >= 1.5: return '显著拥挤'
    if score >= 1: return '偏拥挤'
    if score <= -1.5: return '显著低位'
    if score <= -1: return '偏低位'
    return '中性'


def rows(snapshot):
    as_of = snapshot.get('as_of')
    date.fromisoformat(as_of)
    if as_of > datetime.now(timezone(timedelta(hours=8))).date().isoformat():
        raise ValueError('Future crowding observation')
    data = snapshot.get('data')
    if not isinstance(data, list) or len(data) != 16 or {r.get('code') for r in data} != CODES:
        raise ValueError('Expected 16 unique style factors')
    result = []
    for row in data:
        if row.get('category') != 'style' or row.get('trade_date') != as_of:
            raise ValueError('Mixed crowding categories or dates')
        if not isinstance(row.get('name'), str) or not row['name'] or '\ufffd' in row['name']:
            raise ValueError('Invalid factor name')
        if any(isinstance(row.get(k), bool) or not isinstance(row.get(k), (int, float)) or
               not math.isfinite(row[k]) for k in FIELDS):
            raise ValueError('Missing or invalid crowding values')
        if not 0 <= row['crowding_pct'] <= 100:
            raise ValueError('Invalid percentile')
        result.append({k: row[k] for k in ('code', 'name', *FIELDS)})
    return as_of, result


def build_snapshot(latest, previous=None):
    as_of, items = rows(latest)
    prior_date, prior = rows(previous) if previous is not None else (None, [])
    if prior_date and prior_date >= as_of:
        raise ValueError('Comparison must precede latest date')
    prior = {r['code']: r for r in prior}
    for row in items:
        row['level'] = band(row['crowding_score'])
        row['directionVerified'] = False
        row['change'] = round(row['crowding_score'] - prior[row['code']]['crowding_score'], 4) if prior else None
    return {'available': True, 'asOf': as_of, 'comparisonDate': prior_date,
            'updatedAt': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
            'source': 'AIDO Research · 东北证券金融工程', 'mode': 'risk-only',
            'directionStatus': 'unverified', 'factors': sorted(items, key=lambda r: -r['crowding_score'])}


def validate_snapshot(data):
    if data.get('available') is not True or data.get('mode') != 'risk-only' or data.get('directionStatus') != 'unverified':
        raise ValueError('Invalid crowding snapshot mode')
    raw = {'as_of': data.get('asOf'), 'data': [dict(r, category='style', trade_date=data.get('asOf')) for r in data.get('factors', [])]}
    rows(raw)
    comparison = data.get('comparisonDate')
    if comparison:
        date.fromisoformat(comparison)
        if comparison >= data['asOf']: raise ValueError('Invalid comparison date')
    for r in data['factors']:
        change = r.get('change')
        if r.get('directionVerified') is not False or r.get('level') != band(r['crowding_score']):
            raise ValueError('Unverified direction or incorrect band')
        if comparison:
            if isinstance(change, bool) or not isinstance(change, (int, float)) or not math.isfinite(change):
                raise ValueError('Invalid comparison value')
        elif change is not None: raise ValueError('Change without source date')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='style-crowding.json')
    args = parser.parse_args()
    key = resolve_api_key(None)
    def fetch(path, params):
        request = urllib.request.Request('http://81.70.32.217'+path+'?'+urllib.parse.urlencode(params),
            headers={'Authorization':'Bearer '+key, 'Accept':'application/json', 'User-Agent':'MarketSentimentCrowding/1.0'})
        try:
            with urllib.request.urlopen(request, timeout=20) as response: return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 403: raise SystemExit('HTTP 403: crowding module is not authorized')
            raise SystemExit('Crowding source HTTP '+str(exc.code))
    latest = fetch('/v1/crowding/latest', {'category': 'style'})
    as_of, _ = rows(latest)
    # Snapshot endpoint returns an actual source date; never label it as exactly five sessions.
    prior = fetch('/v1/crowding/snapshot', {'category': 'style', 'date': (date.fromisoformat(as_of)-timedelta(days=7)).isoformat()})
    snapshot = build_snapshot(latest, prior)
    validate_snapshot(snapshot)
    path = Path(args.output)
    if path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        if previous.get('asOf', '') > as_of: raise ValueError('Refusing crowding date rollback')
        if {k:v for k,v in previous.items() if k != 'updatedAt'} == {k:v for k,v in snapshot.items() if k != 'updatedAt'}:
            print('Crowding unchanged: '+as_of)
            return
    content = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    temporary = path.with_suffix('.tmp')
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(path)
    print(json.dumps({'asOf':as_of,'comparisonDate':snapshot['comparisonDate'],'factors':16}, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Provider errors may contain response metadata. Report only the type, never credentials.
        raise SystemExit('Style crowding refresh failed: '+type(exc).__name__)
