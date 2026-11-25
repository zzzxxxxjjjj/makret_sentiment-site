"""Query dated ETF units; persist only allowlisted market numbers, never raw authenticated payloads."""
import os,json,math
from datetime import datetime
from zoneinfo import ZoneInfo
from public_recovery import read,save,finite
from completed_session import completed_target
def main():
 from ifind_client import Client
 target=completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
 calendar=[d for d in read("data-freshness.json")["tradingCalendar"] if "2026-11-18"<=d<=target]
 codes=["159919.SZ","159901.SZ","159915.SZ","159952.SZ","159977.SZ","159922.SZ","159845.SZ","159629.SZ"]
 status={"targetDate":target,"ok":False,"acceptedObservations":0}
 try:
  data=Client().post("cmd_history_quotation",{"codes":",".join(codes),"indicators":"totalShares","startdate":calendar[0],"enddate":target,"functionpara":{"Fill":"Omit"}})
  accepted=[]
  for table in data.get("tables") or []:
   code=table.get("thscode")
   if code not in codes:continue
   values=(table.get("table") or {}).get("totalShares") or []
   for day,value in zip(table.get("time") or [],values):
    stamp=str(day)[:10]
    if stamp in calendar and finite(value) and float(value)>0:
     accepted.append({"code":code.split(".")[0],"date":stamp,"shares":float(value)})
  # Only normalized exchange code/date/units are retained. No account metadata.
  if accepted:save("data_sources/verified-ifind-etf-units.json",{"source":"iFind historical totalShares","rows":accepted})
  status.update(ok=bool(accepted),acceptedObservations=len(accepted),codeCount=len({r["code"] for r in accepted}))
 except Exception as e:
  # The client exposes only HTTP status/error codes, not credentials or payloads.
  status["error"]=str(e)[:160]
 save("etf-units-gap-status.json",status);print(status,flush=True)
if __name__=="__main__":main()
