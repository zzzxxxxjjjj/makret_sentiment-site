"""Reuse prior six artifacts; re-fetch only affected shard 2, at low frequency."""
import hashlib
import json
import math
import time
from pathlib import Path
from sw_history import write, merge

ROOT=Path(__file__).resolve().parent


def main():
    import akshare as ak
    import requests
    from sw_flow_api import history as stock_history
    from akshare_request_policy import install
    install()
    original=requests.sessions.Session.request
    def bounded(self,method,url,**kwargs):
        kwargs['timeout']=15
        return original(self,method,url,**kwargs)
    requests.sessions.Session.request=bounded
    path=ROOT/'sw-history-parts/part-2.json'
    previous=json.loads(path.read_text(encoding='utf-8'))
    members=sorted(json.loads((ROOT/'sw-flow-members.json').read_text(encoding='utf-8'))['members'],key=lambda m:m['code'])
    signature=hashlib.sha256(json.dumps(members,sort_keys=True).encode()).hexdigest()
    if signature!=previous['signature']:raise ValueError('Membership changed; refuse mixed reconstruction')
    dates=previous['dates'];group=members[2::6];codes=sorted({c for m in group for c in m['stocks']})
    histories={};failures=[]
    print('Reusing five prior shards; repair shard 2 stocks='+str(len(codes)),flush=True)
    for i,code in enumerate(codes,1):
        market='sh' if code.startswith('6') else 'bj' if code.startswith(('4','8','9')) else 'sz'
        cache=ROOT/'sw-repair-cache'/(code+'.json')
        if cache.exists():
            saved=json.loads(cache.read_text(encoding='utf-8'))
            if saved.get('dates')==dates:
                histories[code]=saved['values'];continue
        values={}
        try:
            frame=stock_history(ak,code,market)
            for row in frame.to_dict('records'):
                day=str(row['日期'])[:10]
                try:v=float(row['主力净流入-净额'])
                except (ValueError,TypeError):continue
                if day in dates and math.isfinite(v):values[day]=v
        except Exception as exc:
            print(json.dumps(dict(code=code,error=type(exc).__name__,message=str(exc)[:180])),flush=True)
            if 'RateLimit' in type(exc).__name__:raise RuntimeError('Provider rate limit detected; requests stopped immediately') from exc
            failures.append(dict(code=code,error=type(exc).__name__))
        histories[code]=values
        if values:write(cache,dict(dates=dates,values=values))
        if i%50==0:print(f'Repair progress {i}/{len(codes)}',flush=True)
        time.sleep(1)
    days=[]
    for day in dates:
        rows=[]
        for m in group:
            values=[histories[c][day] for c in m['stocks'] if day in histories[c]]
            covered,total=len(values),len(m['stocks'])
            rows.append(dict(code=m['code'],name=m['name'],covered=covered,total=total,value=sum(values)/1e8 if covered/total>=.9 else None))
        days.append(dict(date=day,rows=rows))
    write(path,dict(previous,days=days))
    print('Repair result: '+json.dumps(dict(stocks=len(codes),empty=sum(not v for v in histories.values()),errors=failures)),flush=True)
    merge()


if __name__=='__main__':main()
