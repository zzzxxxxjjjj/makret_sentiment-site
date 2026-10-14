"""Export Wind-dependent raw model inputs for cloud-side daily recomputation."""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
import broad_sentiment as broad
from rqdata_trading_day import CHINA_TIME

INPUT_IDS = {'medium-erp', 'medium-equity-bond-yield-spread', 'medium-equity-bond-position',
             'medium-equity-bond-relative-return-120d', 'medium-pe-ttm',
             'medium-dividend-yield-ttm', 'medium-cdb-10y-yield'}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(broad.BASE_DIR/'wind-synthesis-inputs.json'))
    args = parser.parse_args()
    snapshot = broad.broad_market_medium_term_sentiment_snapshot()
    result = []
    for item in snapshot['series']:
        if item['id'] in INPUT_IDS and item.get('points'):
            cutoff = (datetime.fromisoformat(item['points'][-1]['date']).date()-timedelta(days=150)).isoformat()
            result.append({**item, 'points': [p for p in item['points'] if p['date'] >= cutoff]})
    if {s['id'] for s in result} != INPUT_IDS:
        raise ValueError('Incomplete Wind synthesis inputs; previous export retained')
    output = Path(args.output)
    temporary = output.with_suffix('.json.tmp')
    temporary.write_text(json.dumps({'exportedAt':datetime.now(CHINA_TIME).isoformat(timespec='seconds'),
                                    'series':result}, ensure_ascii=True), encoding='utf-8')
    temporary.replace(output)
    print(json.dumps({s['id']:s['points'][-1]['date'] for s in result},ensure_ascii=True))

if __name__ == '__main__':
    main()
