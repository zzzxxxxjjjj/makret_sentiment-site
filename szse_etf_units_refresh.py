"""Fetch dated SZSE ETF units via AKShare; public market data only."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from completed_session import completed_target
from public_recovery import read,save,finite
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 target=os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
 start=os.environ.get("ETF_UNITS_START","2026-11-18")
 status={"targetDate":target,"startDate":start,"source":"AKShare fund_scale_daily_szse","ok":False}
 try:
  frame=ak.fund_scale_daily_szse(start_date=start.replace("-",""),end_date=target.replace("-",""),symbol="ETF")
  rows=[];seen=set()
  for r in frame.to_dict("records"):
   day=str(r.get("日期",""))[:10];code=str(r.get("基金代码","")).zfill(6);units=r.get("基金份额")
   if not(start<=day<=target) or len(code)!=6 or not code.isdigit() or not finite(units) or float(units)<=0:raise ValueError("Invalid dated SZSE units")
   if (day,code) in seen:raise ValueError("Duplicate units")
   seen.add((day,code));rows.append({"date":day,"code":code,"name":str(r.get("基金简称","")),"shares":float(units)})
  dates=sorted({r["date"] for r in rows})
  status.update(rows=len(rows),dates=dates,codes=len({r["code"] for r in rows}),columns=list(frame.columns))
  if not rows or target not in dates:raise ValueError("Requested final session missing")
  save("szse-etf-dated-units.json",{"source":status["source"],"asOf":target,"rows":rows})
  status["ok"]=True
 except Exception as exc:
  status["error"]=type(exc).__name__+": "+str(exc)[:250]
 save("szse-etf-units-status.json",status);print(status,flush=True)
 if not status["ok"]:raise SystemExit(1)
if __name__=="__main__":main()
