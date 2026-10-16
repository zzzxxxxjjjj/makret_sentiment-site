import os
from pathlib import Path
from data_freshness import read, write_report
os.environ['ENABLE_RQDATA_REFRESH']='0'
import broad_sentiment as broad
broad.ENABLE_RQDATA_REFRESH=False
payload=broad._build_payload(force=True)
broad.save_page_cache(payload)
base=Path(__file__).resolve().parent
previous=read(base,'data-freshness.json')
target=previous.get('targetDate') or payload['asOf']
write_report(target,calendar=previous.get('tradingCalendar',[]),errors=previous.get('errors',[]))
