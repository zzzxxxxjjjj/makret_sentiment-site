"""Verify the public deployment contains the exact new source-date report."""
import json, time, urllib.request
from pathlib import Path
expected=json.loads(Path('data-freshness.json').read_text(encoding='utf-8-sig'))
url='https://makret-sentiment-site.pages.dev/data-freshness.json'
for attempt in range(24):
    try:
        request=urllib.request.Request(url+'?verify='+str(time.time_ns()),headers={'Cache-Control':'no-cache','User-Agent':'MarketSentimentPublicationCheck/1.0'})
        with urllib.request.urlopen(request,timeout=15) as response:
            actual=json.load(response)
        if actual.get('checkedAt')==expected['checkedAt'] and actual.get('targetDate')==expected['targetDate']:
            print('Public deployment verified for '+expected['targetDate'])
            break
    except (OSError,ValueError):
        pass
    time.sleep(15)
else:
    raise SystemExit('Public website did not receive the new date report within six minutes')
