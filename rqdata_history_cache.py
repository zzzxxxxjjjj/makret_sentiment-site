"""Persist successful RQData responses and fetch only the missing date tail.

Cache is private runtime state produced by this application, never a web asset.
"""
from __future__ import annotations
import hashlib
import json
from datetime import timedelta
from pathlib import Path
import pandas as pd
BASE_DIR=Path(__file__).resolve().parent
CACHE=BASE_DIR/'.rqdata-cache/responses'

def cache_path(method, args, kwargs):
    key=json.dumps([method,args,kwargs],default=str,sort_keys=True,ensure_ascii=True)
    CACHE.mkdir(parents=True,exist_ok=True)
    return CACHE/(hashlib.sha256(key.encode()).hexdigest()+'.pkl.gz')

def save(path, value):
    temporary=path.with_suffix('.tmp')
    pd.to_pickle(value,temporary,compression='gzip')
    temporary.replace(path)

def snapshot(rq, method, *args, **kwargs):
    path=cache_path(method,args,kwargs)
    if path.exists():
        return pd.read_pickle(path,compression='gzip')
    value=getattr(rq,method)(*args,**kwargs)
    if value is not None and not getattr(value,'empty',False):
        save(path,value)
    return value

def frame_dates(data):
    if data is None or data.empty:
        return None
    for name in ('date','datetime','trading_date','tradedate'):
        if name in data.index.names:
            return pd.DatetimeIndex(pd.to_datetime(data.index.get_level_values(name)))
        if name in data.columns:
            return pd.DatetimeIndex(pd.to_datetime(data[name]))
    if isinstance(data.index,pd.DatetimeIndex):
        return data.index
    return None

def history(rq,method,ids,start,end,**kwargs):
    start,end=pd.Timestamp(start).date(),pd.Timestamp(end).date()
    path=cache_path(method,[ids],kwargs)
    cached=pd.read_pickle(path,compression='gzip') if path.exists() else None
    first=start
    if cached is not None and cached['start']<=start:
        # Requery a small overlap for late provider corrections and T+1 margin data.
        first=max(start,cached['end']-timedelta(days=7))
    else:
        cached=None
    incoming=getattr(rq,method)(ids,start_date=first,end_date=end,**kwargs)
    if incoming is None or incoming.empty:
        return cached['data'] if cached else incoming
    data=pd.concat([cached['data'],incoming]) if cached else incoming
    data=data.loc[~data.index.duplicated(keep='last')].sort_index()
    dates=frame_dates(data)
    if dates is None:
        return incoming
    save(path,{'start':cached['start'] if cached else first,'end':dates.max().date(),'data':data})
    return data[(dates.date>=start)&(dates.date<=end)]
