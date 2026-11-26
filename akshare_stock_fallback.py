"""Dated public stock snapshots; never turn a live quote into a historical close."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from public_recovery import read,save,finite
def collect(target):
 cached=read("akshare-stock-snapshot.json")
 if cached.get("asOf")==target and cached.get("complete") and len(cached.get("rows",[]))>=5000:return cached["rows"]
 now=datetime.now(ZoneInfo("Asia/Shanghai"))
 if target!=now.date().isoformat() or now.hour<18:
  raise ValueError("AkShare historical all-A snapshot not yet cached; current intraday quotes cannot replace "+target)
 import akshare as ak
 frame=ak.stock_zh_a_spot_em()
 rows=[]
 for r in frame.to_dict("records"):
  code=str(r.get("代码","")).zfill(6)
  if not code.startswith(("00","30","60","68","43","83","87","88","92")):continue
  a,t=r.get("成交额"),r.get("换手率")
  if not finite(a) or not finite(t) or float(a)<0 or not 0<=float(t)<=100:continue
  rows.append({"代码":code,"成交额":float(a),"换手率":float(t)})
 if len(rows)<5000 or len({r["代码"] for r in rows})!=len(rows) or sum(r["代码"].startswith(("43","83","87","88","92")) for r in rows)<300:
  raise ValueError("Incomplete public SH/SZ/BJ snapshot")
 save("akshare-stock-snapshot.json",{"asOf":target,"source":"AKShare / 东方财富已收盘全A快照","complete":True,"rows":rows})
 return rows
