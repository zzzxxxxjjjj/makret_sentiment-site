"""Probe the exact public stock-flow history needed by the SW chart."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from public_recovery import read,save,resolve,finite
from completed_session import completed_target
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 target=os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
 expected=[d for d in read("data-freshness.json")["tradingCalendar"] if d<=target][-20:]
 result={"targetDate":target,"expectedDates":expected,"results":[]}
 for code,market in [("600036","sh"),("000001","sz"),("300750","sz")]:
  try:
   from sw_flow_api import history
   f=history(ak,code,market)
   points={str(r["日期"])[:10]:float(r["主力净流入-净额"]) for r in f.to_dict("records") if str(r["日期"])[:10] in expected and finite(r.get("主力净流入-净额"))}
   result["results"].append({"code":code,"ok":set(points)==set(expected),"returnedRows":len(f),"points":[{"date":d,"value":points[d]} for d in sorted(points)]})
  except Exception as exc:
   result["results"].append({"code":code,"ok":False,"error":type(exc).__name__+": "+str(exc)[:300]})
   # Stop at upstream throttling/disconnection rather than launching thousands of calls.
   save("sw-chart-source-status.json",result);break
  save("sw-chart-source-status.json",result)
 save("sw-chart-source-status.json",result);print(result,flush=True)
if __name__=="__main__":main()
