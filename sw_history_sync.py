"""Maintain the latest complete 20-session SW flow window from verified close records."""
import copy,math,os
from datetime import datetime
from zoneinfo import ZoneInfo
from public_recovery import read,save
from completed_session import completed_target
def valid_day(day):
 rows=day.get("rows",[])
 if len(rows)!=30 or len({r.get("code") for r in rows})!=30:return False
 usable=0
 for r in rows:
  total,covered=r.get("total",0),r.get("covered",0)
  if not isinstance(total,(int,float)) or total<=0 or not 0<=covered<=total:return False
  v=r.get("value")
  if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and covered/total>=.9:usable+=1
 return usable>=27
def synchronize(history,flow,calendar,target,archive=None):
 history=copy.deepcopy(history);archive=copy.deepcopy(archive or {})
 sessions=sorted(set(d for d in calendar if d<=target))
 if len(sessions)<20:raise ValueError("Verified trading calendar has fewer than 20 completed sessions")
 retained={d["date"]:d for d in archive.get("days",[]) if d.get("date") in sessions and valid_day(d)}
 for d in history.get("days",[]):
  if d.get("date") in sessions and valid_day(d):
   retained.setdefault(d["date"],{**d,"membershipDate":history.get("membershipDate"),"source":"AKShare历史个股主力资金重构"})
 ignored=[]
 for p in flow.get("snapshots",[]):
  source=p.get("source",flow.get("source",""))
  # Old iFind main-money classifications are not spliced into Eastmoney history.
  if not p.get("completedSession") or not str(source).lower().startswith("akshare"):
   ignored.append(p.get("date"));continue
  if p.get("date") not in sessions or not valid_day(p):continue
  retained[p["date"]]={**p,"source":source}
 published=None
 for i in range(len(sessions)-1,18,-1):
  dates=sessions[i-19:i+1]
  if all(d in retained for d in dates):
   published=dates;break
 if published:
  days=[retained[d] for d in published]
  if history.get("asOf","")<=published[-1]:
   history.update(available=True,asOf=published[-1],days=days,
    method="申万2021一级行业；按各采集批次记录的成分股归属汇总。每日收盘净额累计，非分钟数据；低于90%覆盖的行业日留空，不跨缺失交易日累计。",
    coverage={"validIndustryDays":sum(sum(isinstance(r.get("value"),(int,float)) and math.isfinite(r["value"]) for r in d["rows"]) for d in days),"totalIndustryDays":600})
 expected=sessions[-20:];missing=[d for d in expected if d not in retained]
 complete=not missing and history.get("asOf")==target
 status={"targetDate":target,"asOf":history.get("asOf"),"complete":complete,
  "latestObservedDate":max(retained,default=None),"latestSingleDayDate":flow.get("asOf"),
  "missingDates":missing,"windowStart":expected[0],"windowEnd":expected[-1],
  "ignoredUnverifiedSnapshotDates":sorted(set(d for d in ignored if d)),
  "policy":"只累计连续20个交易日；失败保留旧完整窗口；不把缺失填零，不拼接iFind主力划分"}
 history["updateStatus"]=status
 archive={"classification":"申万2021一级（剔除综合）","days":[retained[d] for d in sorted(retained)]}
 return history,archive,status
def main():
 from pathlib import Path
 from public_recovery import ROOT
 target=os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
 history,archive,status=synchronize(read("sw-industry-history.json"),read("sw-industry-flow.json"),read("data-freshness.json")["tradingCalendar"],target,read("sw-industry-history-archive.json"))
 status["checkedAt"]=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
 history["updateStatus"]=status
 save("sw-industry-history-archive.json",archive)
 save("sw-industry-history.json",history)
 save("sw-industry-history-status.json",status)
 print(status,flush=True)
if __name__=="__main__":main()
