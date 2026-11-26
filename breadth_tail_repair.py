"""Repair only failed cached breadth observations; keep the original universe and formulas."""
import os,json
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from public_recovery import read,save,resolve,finite
from breadth_public_refresh import ROOT,load,dump,combine
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 target=os.environ["DAILY_TARGET_DATE"]
 if read("rqdata-breadth-sentiment.json").get("asOf","")>=target:
  print("Breadth already current for cached target",target,flush=True);return
 audit={"targetDate":target,"repairs":[]}
 listing=None
 for path in (ROOT/"breadth-parts").rglob("*.json.gz"):
  part=load(path);remaining=[]
  for error in part["errors"]:
   code=error["code"]
   if not code.startswith("bj."):remaining.append(error);continue
   exclusion=next((r for r in read("verified-listing-exclusions.json").get("records",[]) if r["code"]==code and r["announcementDate"]<=target<=r["notListedThrough"]),None)
   if exclusion:
    part["universe"].remove(code)
    part["stocks"].pop(code,None)
    audit["repairs"].append({**exclusion,"status":"Excluded verified pre-listing subscription code from listed-A-share universe"})
    continue
   repaired=False
   for method in ("stock_zh_a_hist","stock_zh_a_hist_tx"):
    try:
     start=(pd.Timestamp(target)-pd.Timedelta(days=140)).strftime("%Y%m%d")
     if method.endswith("_tx"):
      frame=resolve(ak,method)(symbol=code.replace(".",""),start_date=start,end_date=target.replace("-",""),adjust="qfq")
      cols=("date","close","volume")
     else:
      frame=resolve(ak,method)(symbol=code.split(".")[1],period="daily",start_date=start,end_date=target.replace("-",""),adjust="qfq");cols=("日期","收盘","成交量")
     points=[{"date":str(r[cols[0]])[:10],"close":float(r[cols[1]]),"volume":float(r[cols[2]])} for r in frame.to_dict("records") if finite(r.get(cols[1])) and finite(r.get(cols[2])) and str(r[cols[0]])[:10]<=target]
     if not points or points[-1]["date"]!=target:raise ValueError("Target date missing")
     part["stocks"][code]=points;repaired=True
     audit["repairs"].append({"code":code,"source":method,"rows":len(points),"asOf":points[-1]["date"]});break
    except Exception as exc:audit["repairs"].append({"code":code,"source":method,"error":type(exc).__name__})
   if not repaired:
    try:
     if listing is None:listing=resolve(ak,"stock_info_bj_name_code")()
     rows=listing.to_dict("records")
     matched=[r for r in rows if any(str(r.get(k,"")).split(".")[0].zfill(6)==code.split(".")[1] for k in ("证券代码","代码"))]
     if len(matched)!=1:raise ValueError("Listing record not verified")
     ipo=str(matched[0].get("上市日期",""))[:10]
     warm=[d for d in read("data-freshness.json")["tradingCalendar"] if d<=target][-20:]
     if len(ipo)!=10 or not warm[0]<ipo<=target:raise ValueError("Cannot establish 20-session ineligibility")
     part["stocks"][code]=[];repaired=True
     audit["repairs"].append({"code":code,"ipoDate":ipo,"status":"Verified new listing; fewer than 20 sessions, ineligible under original formula"})
    except Exception as exc:audit["repairs"].append({"code":code,"source":"listing-date-check","error":type(exc).__name__})
   if not repaired:remaining.append(error)
  part["errors"]=remaining;dump(path,part)
 save("breadth-tail-repair-status.json",audit);print(audit,flush=True)
 combine()
if __name__=="__main__":main()
