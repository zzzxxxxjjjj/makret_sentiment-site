"""Run the public replacements independently; preserve success when another source fails."""
import os,sys,subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from completed_session import completed_target
from public_recovery import read,save
target=completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
os.environ["DAILY_TARGET_DATE"]=target
status={"targetDate":target,"results":[]}
for name,script,timeout in [("index-turnover","akshare_index_turnover_refresh.py",180),("mixed-bond","akshare_medium_bond_refresh.py",180)]:
 try:
  r=subprocess.run([sys.executable,script],timeout=timeout)
  status["results"].append({"id":name,"ok":r.returncode==0,"exitCode":r.returncode})
 except subprocess.TimeoutExpired:status["results"].append({"id":name,"ok":False,"error":"Public source timed out"})
 save("akshare-replacement-status.json",status)
 print(status["results"][-1],flush=True)
