"""Small public-data probe; log status/date coverage, no credentials."""
import json
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import akshare as ak
import requests

original = requests.sessions.Session.request
def bounded(self, method, url, **kwargs):
    kwargs['timeout'] = 12
    return original(self, method, url, **kwargs)
requests.sessions.Session.request = bounded
now=datetime.now(ZoneInfo('Asia/Shanghai'))
end=now.date() if now.hour>=18 else now.date()-timedelta(days=1)
dates=[str(d) for d in ak.tool_trade_date_hist_sina()['trade_date'] if str(d)<=end.isoformat()][-20:]
for code,market in [('600519','sh'),('000001','sz'),('600036','sh'),('300750','sz'),('688981','sh')]:
    try:
        frame=ak.stock_individual_fund_flow(stock=code,market=market)
        good=[]
        for row in frame.to_dict('records'):
            try:v=float(row['主力净流入-净额'])
            except (ValueError,TypeError):continue
            day=str(row['日期'])[:10]
            if math.isfinite(v):good.append(day)
        print(json.dumps(dict(code=code,rows=len(frame),first=min(good,default=None),last=max(good,default=None),
            validRequestedDays=len(set(good)&set(dates)),missing=[d for d in dates if d not in good])),flush=True)
    except Exception as exc:
        print(json.dumps(dict(code=code,errorType=type(exc).__name__,message=str(exc)[:220])),flush=True)
