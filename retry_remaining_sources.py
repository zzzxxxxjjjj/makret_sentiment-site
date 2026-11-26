"""Retry existing collectors once per stage with bounded waits and explicit results."""
import os,sys,subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from public_recovery import read,save
from completed_session import completed_target
target=completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
os.environ["DAILY_TARGET_DATE"]=target
os.environ["DEFER_DASHBOARD_BUILD"]="1"
tasks=[
 ("public-inputs",["public_recovery.py"],480),
 ("index-financing",["index_public_recovery.py","--daily"],360),
 ("index-turnover",["ifind_index_turnover_refresh.py"],120),
 ("margin-risk",["akshare_margin_risk.py"],120),
 ("etf-market",["etf_market_refresh.py"],180),
 ("industry-flow",["sw_flow_refresh.py"],180),
 ("bond-proxy",["ifind_medium_bond_refresh.py"],90),
 ("medium-matching",["public_recovery.py","--medium-only"],180),
 ("fund-exposure",["rqdata_fund_exposure_refresh.py","--output","rqdata-fund-exposure.json","--timeout","20"],120),
 ("style-crowding",["aido_style_crowding_refresh.py"],120),
]
report={"targetDate":target,"attempts":[]}
for name,command,timeout in tasks:
 if name in ("fund-exposure","style-crowding") and not os.environ.get("AIDO_API_KEY"):
  report["attempts"].append({"stage":name,"ok":False,"reason":"AIDO_API_KEY unavailable"})
 else:
  try:
   done=subprocess.run([sys.executable,*command],timeout=timeout,check=False)
   report["attempts"].append({"stage":name,"ok":done.returncode==0,"exitCode":done.returncode})
  except subprocess.TimeoutExpired:report["attempts"].append({"stage":name,"ok":False,"reason":"Bounded retry timed out"})
 save("remaining-retry-status.json",report);print(report["attempts"][-1],flush=True)
