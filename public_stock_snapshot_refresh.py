"""Dated public all-A snapshots: BaoStock bulk SH/SZ and AkShare Tencent Beijing."""
import os,sys,json,importlib
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from public_recovery import read,save,resolve,finite
from completed_session import completed_target
ROOT=Path(__file__).resolve().parent
def target_day():
 return os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
def plan():
 import akshare as ak
 import baostock as bs
 from akshare_request_policy import install
 install();target=target_day()
 cached=read("akshare-stock-snapshot.json")
 if cached.get("complete") and cached.get("asOf")==target:
  save("public-snapshot-plan.json",{"targetDate":target,"days":[],"beijing":[],"base":{},"alreadyCurrent":True})
  print("Public snapshot already current",target,flush=True);return
 calendar=read("data-freshness.json")["tradingCalendar"];days=[d for d in calendar if (cached.get("asOf") or "2026-11-22")<d<=target]
 if len(days)>8:days=days[-3:]
 listed=resolve(ak,"stock_info_bj_name_code")()
 bj={str(r["证券代码"]).split(".")[0].zfill(6) for r in listed.to_dict("records") if str(r.get("上市日期",""))[:10]<=target}
 if len(bj)<300:raise ValueError("Official Beijing listed-stock universe incomplete")
 excluded={r["code"].split(".")[-1] for r in read("verified-listing-exclusions.json").get("records",[]) if r["announcementDate"]<=target<=r["notListedThrough"]}
 bj=sorted(bj-excluded)
 login=bs.login()
 if login.error_code!="0":raise ValueError("Historical bulk backup login failed")
 base={};errors=[]
 try:
  for day in days:
   q=bs.query_all_stock(day=day);master={}
   while q.error_code=="0" and q.next():
    r=dict(zip(q.fields,q.get_row_data()));c=r.get("code","")
    if c.startswith(("sh.60","sh.68","sz.00","sz.30")):master[c]=r.get("tradeStatus")
   if q.error_code!="0" or len(master)<5000:raise ValueError("Incomplete dated SH/SZ stock master")
   q=bs.query_daily_history_k_AStock(date=day);rows={}
   while q.error_code=="0" and q.next():
    r=dict(zip(q.fields,q.get_row_data()));c=r.get("code","")
    if c in master and r.get("date")==day and finite(r.get("amount")) and finite(r.get("turn")) and float(r["amount"])>=0 and 0<=float(r["turn"])<=100:
     rows[c]={"代码":c.split(".")[-1],"成交额":float(r["amount"]),"换手率":float(r["turn"])}
   if q.error_code!="0":raise ValueError("Incomplete public stock batch")
   for c,status in master.items():
    if status=="0":
     if c in rows and rows[c]["成交额"]>0:raise ValueError("Suspension/turnover inconsistency")
     rows[c]={"代码":c.split(".")[-1],"成交额":0.,"换手率":0.,"confirmedSuspended":True}
   missing=set(master)-set(rows)
   if len(missing)>20:raise ValueError("Too many SH/SZ bulk gaps")
   for c in sorted(missing):
    q=bs.query_history_k_data_plus(c,"date,code,amount,turn,tradestatus",start_date=day,end_date=day,adjustflag="3")
    values=[]
    while q.error_code=="0" and q.next():values.append(dict(zip(q.fields,q.get_row_data())))
    if len(values)==1 and values[0]["date"]==day:
     r=values[0]
     if r.get("tradestatus")=="0":rows[c]={"代码":c.split(".")[-1],"成交额":0.,"换手率":0.,"confirmedSuspended":True}
     elif finite(r.get("amount")) and finite(r.get("turn")) and float(r["amount"])>=0 and 0<=float(r["turn"])<=100:
      rows[c]={"代码":c.split(".")[-1],"成交额":float(r["amount"]),"换手率":float(r["turn"])}
   if set(rows)!=set(master):raise ValueError("Missing dated SH/SZ amount/turnover: "+",".join(sorted(set(master)-set(rows))))
   base[day]=list(rows.values());print("Verified SH/SZ snapshot",day,len(rows),flush=True)
 finally:bs.logout()
 save("public-snapshot-plan.json",{"targetDate":target,"days":days,"beijing":bj,"base":base,"source":"AkShare腾讯北交所历史日线＋BaoStock沪深历史整批补缺；非实时盘中快照"})
 print("Public snapshot plan",target,len(bj),flush=True)
def worker(shard,total):
 import akshare as ak
 from akshare_request_policy import install
 install();config=read("public-snapshot-plan.json");target=config["targetDate"];days=config["days"]
 codes=config["beijing"][shard::total]
 cache=ROOT/".daily-cache"/("beijing-snapshot-"+target);cache.mkdir(parents=True,exist_ok=True)
 output={"targetDate":target,"codes":codes,"rows":{},"errors":[]}
 # The API's listing-date lookup is redundant for an explicit dated range and
 # a verified listed-stock master. Avoid that discovery request, not quote pacing.
 module=importlib.import_module("akshare.stock.quote.stock_hist_tx")
 original=module.get_tx_start_year
 module.get_tx_start_year=lambda symbol:"2000-01-01"
 try:
  for i,code in enumerate(codes):
   path=cache/(code+".json")
   try:
    if path.exists():values=json.loads(path.read_text(encoding="utf-8"))
    else:
     f=resolve(ak,"stock_zh_a_hist_tx")(symbol="bj"+code,start_date=days[0].replace("-",""),end_date=target.replace("-",""),adjust="")
     values=[]
     for r in f.to_dict("records"):
      day=str(r.get("date",""))[:10];amount=r.get("amount");turn=r.get("turnover")
      if day in days and finite(amount) and finite(turn) and float(amount)>=0 and 0<=float(turn)*100<=100:
       values.append({"date":day,"代码":code,"成交额":float(amount),"换手率":float(turn)*100})
     if not any(r["date"]==target for r in values):raise ValueError("Target Beijing amount/turnover missing")
     path.write_text(json.dumps(values),encoding="utf-8")
    output["rows"][code]=values
   except Exception as e:output["errors"].append({"code":code,"error":type(e).__name__+": "+str(e)[:180]})
   save("public-snapshot-part-"+str(shard)+".json",output)
   if i%10==0:print("Beijing quotes",shard,i,len(codes),flush=True)
 finally:module.get_tx_start_year=original
 save("public-snapshot-part-"+str(shard)+".json",output)
def combine():
 config=read("public-snapshot-plan.json");target=config["targetDate"];allrows={};errors=[]
 if config.get("alreadyCurrent"):
  print("Verified public snapshot already retained",target,flush=True);return
 for path in ROOT.glob("public-snapshot-part-*.json"):
  part=json.loads(path.read_text(encoding="utf-8"))
  if part["targetDate"]!=target:raise ValueError("Snapshot shard date mismatch")
  if set(allrows)&set(part["rows"]):raise ValueError("Duplicate Beijing snapshot shard")
  allrows.update(part["rows"]);errors.extend(part["errors"])
 status={"targetDate":target,"expectedBeijing":len(config["beijing"]),"receivedBeijing":len(allrows),"errors":errors,"complete":False}
 save("akshare-stock-snapshot-status.json",status)
 if set(allrows)!=set(config["beijing"]):raise ValueError("Full SH/SZ/BJ snapshot not complete; old data retained")
 metrics={sid:[] for sid in ("market-turnover","top5-concentration","alla-turnover-amount")}
 latest_rows=None
 import math
 for day in config["days"]:
  rows=list(config["base"][day])
  for code in config["beijing"]:
   current=[r for r in allrows[code] if r["date"]==day]
   if len(current)!=1:raise ValueError("Dated Beijing observation missing or duplicated: "+code+" "+day)
   rows.append({k:v for k,v in current[0].items() if k!="date"})
  if len({r["代码"] for r in rows})!=len(rows):raise ValueError("Duplicate public stock snapshot")
  active=[r for r in rows if r["成交额"]>0 and r["换手率"]>=0]
  if len(active)<4000:raise ValueError("Incomplete active all-A sample")
  amounts=sorted((r["成交额"] for r in active),reverse=True)
  values={"market-turnover":sum(r["换手率"] for r in active)/len(active),"top5-concentration":sum(amounts[:math.ceil(len(active)*.05)])/sum(amounts)*100,"alla-turnover-amount":sum(amounts)/1e8}
  for sid,value in values.items():metrics[sid].append({"date":day,"value":value})
  if day==target:latest_rows=rows
 if latest_rows is None:raise ValueError("No target snapshot")
 save("akshare-stock-snapshot.json",{"asOf":target,"source":config["source"],"complete":True,"rows":latest_rows})
 status.update(complete=True,total=len(latest_rows),metrics=metrics);save("akshare-stock-snapshot-status.json",status);print({**status,"metrics":{k:v[-1] for k,v in metrics.items()}},flush=True)

if __name__=="__main__":
 if sys.argv[1]=="plan":plan()
 elif sys.argv[1]=="combine":combine()
 else:worker(int(sys.argv[1]),int(sys.argv[2]))
