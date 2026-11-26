"""Bootstrap complete public adjusted A-share prices; preserve original breadth formulas."""
import os,sys,json,gzip,socket,time
from pathlib import Path
from datetime import datetime,timedelta,date
from zoneinfo import ZoneInfo
import pandas as pd
from public_recovery import read,save,resolve,finite
from completed_session import completed_target
ROOT=Path(__file__).resolve().parent
CACHE=ROOT/".breadth-public-cache";CACHE.mkdir(exist_ok=True)
def target_day():
 return os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
def dump(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 with gzip.open(path,"wt",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=False)
def load(path):
 with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)
def worker(provider,shard,shards):
 target=target_day();start=(pd.Timestamp(target)-pd.Timedelta(days=140)).strftime("%Y-%m-%d")
 output={"provider":provider,"asOf":target,"stocks":{},"errors":[],"universe":[]}
 if provider=="bao":
  import baostock as bs
  socket.setdefaulttimeout(20)
  r=bs.login()
  if r.error_code!="0":raise ValueError("Baostock login "+r.error_code)
  try:
   q=bs.query_all_stock(day=target);master=[];paused=set()
   while q.error_code=="0" and q.next():
    row=dict(zip(q.fields,q.get_row_data()));c=row.get("code","")
    if c.startswith(("sh.60","sh.68","sz.00","sz.30")):
     master.append(c)
     if row.get("tradeStatus")=="0":paused.add(c)
   if q.error_code!="0" or len(master)<5000:raise ValueError("Incomplete SH/SZ universe")
   codes=sorted(set(master))[shard::shards];output["universe"]=codes
   for i,c in enumerate(codes):
    path=CACHE/(c+".json.gz")
    if path.exists() and load(path).get("asOf")==target:output["stocks"][c]=load(path)["points"];continue
    try:
     q=bs.query_history_k_data_plus(c,"date,code,close,volume",start_date=start,end_date=target,adjustflag="2")
     points=[]
     while q.error_code=="0" and q.next():
      row=dict(zip(q.fields,q.get_row_data()))
      if finite(row.get("close")) and finite(row.get("volume")):
       points.append({"date":row["date"],"close":float(row["close"]),"volume":float(row["volume"])})
     if q.error_code!="0" or not points:raise ValueError("No verified price history")
     if points[-1]["date"]!=target and c not in paused:raise ValueError("Active stock target session missing")
     output["stocks"][c]=points;dump(path,{"asOf":target,"points":points})
    except Exception as e:output["errors"].append({"code":c,"error":type(e).__name__})
    if i%100==0:print(provider,shard,i,len(codes),flush=True)
  finally:bs.logout()
 else:
  import akshare as ak
  from akshare_request_policy import install
  install()
  master=sorted({str(r["代码"]) for r in read("ifind-stock-snapshot.json").get("rows",[]) if str(r["代码"]).startswith(("43","83","87","88","92"))})
  if len(master)<200:raise ValueError("No verified Beijing universe")
  exclusions={r["code"].split(".")[1] for r in read("verified-listing-exclusions.json").get("records",[]) if r["announcementDate"]<=target<=r["notListedThrough"]}
  master=[c for c in master if c not in exclusions]
  codes=master[shard::shards];output["universe"]=["bj."+c for c in codes]
  em_failures=0
  for i,c in enumerate(codes):
   key="bj."+c;path=CACHE/(key+".json.gz")
   if path.exists() and load(path).get("asOf")==target:output["stocks"][key]=load(path)["points"];continue
   try:
    try:
     if em_failures>=2:raise ValueError("Switch source after repeated Eastmoney failure")
     f=resolve(ak,"stock_zh_a_hist")(symbol=c,period="daily",start_date=start.replace("-",""),end_date=target.replace("-",""),adjust="qfq")
     points=[{"date":str(r["日期"])[:10],"close":float(r["收盘"]),"volume":float(r["成交量"])} for r in f.to_dict("records") if finite(r.get("收盘")) and finite(r.get("成交量")) and str(r["日期"])[:10]<=target]
     if not points or points[-1]["date"]!=target:raise ValueError("Stale Eastmoney history")
    except Exception:
     em_failures+=1
     f=resolve(ak,"stock_zh_a_hist_tx")(symbol="bj"+c,start_date=start.replace("-",""),end_date=target.replace("-",""),adjust="qfq")
     points=[{"date":str(r["date"])[:10],"close":float(r["close"]),"volume":float(r["volume"])} for r in f.to_dict("records") if finite(r.get("close")) and finite(r.get("volume")) and str(r["date"])[:10]<=target]
    if not points or points[-1]["date"]!=target:raise ValueError("BJ target session missing")
    output["stocks"][key]=points;dump(path,{"asOf":target,"points":points})
   except Exception as e:output["errors"].append({"code":key,"error":type(e).__name__})
   if i%10==0:print(provider,shard,i,len(codes),flush=True)
 dump(ROOT/"breadth-parts"/(provider+"-"+str(shard)+".json.gz"),output)
 print({"provider":provider,"shard":shard,"count":len(output["stocks"]),"errors":len(output["errors"])},flush=True)
def combine():
 from rqdata_breadth_refresh import calculate_batch,merge_daily,build_sentiment
 target=target_day();old=read("rqdata-breadth-sentiment.json")
 counts=old.get("dailyCounts",[])
 if not counts:raise ValueError("Verified historical breadth counts missing")
 last=max(r["date"] for r in counts);output_start=date.fromisoformat(last)+timedelta(days=1)
 prices={};errors=[];expected=set()
 for p in (ROOT/"breadth-parts").rglob("*.json.gz"):
  part=load(p)
  if part["asOf"]!=target:raise ValueError("Part target mismatch")
  if expected.intersection(part["universe"]):raise ValueError("Overlapping shard universe")
  expected.update(part["universe"]);prices.update(part["stocks"]);errors.extend(part["errors"])
 save("breadth-public-status.json",{"targetDate":target,"universe":len(expected),"received":len(prices),"errors":errors,"beijing":sum(c.startswith("bj.") for c in prices)})
 if errors:
  import baostock as bs
  socket.setdefaulttimeout(20);login=bs.login();remaining=[]
  if login.error_code!="0":raise ValueError("Failed-stock repair login failed")
  try:
   for err in errors:
    c=err["code"]
    if c.startswith("bj."):remaining.append(err);continue
    start=(pd.Timestamp(target)-pd.Timedelta(days=140)).strftime("%Y-%m-%d")
    q=bs.query_history_k_data_plus(c,"date,code,close,volume",start_date=start,end_date=target,adjustflag="2");repaired=[]
    while q.error_code=="0" and q.next():
     row=dict(zip(q.fields,q.get_row_data()))
     if finite(row.get("close")) and finite(row.get("volume")):repaired.append({"date":row["date"],"close":float(row["close"]),"volume":float(row["volume"])})
    if repaired and repaired[-1]["date"]==target:prices[c]=repaired;continue
    try:
     import akshare as ak
     from akshare_request_policy import install
     install()
     f=resolve(ak,"stock_zh_a_hist_tx")(symbol=c.replace(".",""),start_date=start.replace("-",""),end_date=target.replace("-",""),adjust="qfq")
     alternative=[{"date":str(r["date"])[:10],"close":float(r["close"]),"volume":float(r["volume"])} for r in f.to_dict("records") if finite(r.get("close")) and finite(r.get("volume")) and str(r["date"])[:10]<=target]
     if alternative and alternative[-1]["date"]==target:prices[c]=alternative;continue
    except Exception:pass
    sessions=[d for d in read("data-freshness.json")["tradingCalendar"] if last<d<=target]
    paused=True
    for day in sessions:
     q=bs.query_all_stock(day=day);match=None
     while q.error_code=="0" and q.next():
      row=dict(zip(q.fields,q.get_row_data()))
      if row.get("code")==c:match=row;break
     if not match or match.get("tradeStatus")!="0":paused=False;break
    if paused:prices[c]=[];continue
    q=bs.query_stock_basic(code=c);info=[]
    while q.error_code=="0" and q.next():info.append(dict(zip(q.fields,q.get_row_data())))
    warm=[d for d in read("data-freshness.json")["tradingCalendar"] if d<=target][-20:]
    if len(info)==1 and info[0].get("ipoDate","")>warm[0]:prices[c]=[];continue
    remaining.append(err)
  finally:bs.logout()
  errors=remaining
  save("breadth-public-status.json",{"targetDate":target,"universe":len(expected),"received":len(prices),"errors":errors,"beijing":sum(c.startswith("bj.") for c in prices)})
 if errors or set(prices)!=expected or len(prices)<5300:raise ValueError("Public price universe incomplete; retaining old breadth")
 records=[{"order_book_id":c,"date":p["date"],"close":p["close"],"volume":p["volume"]} for c,pts in prices.items() for p in pts]
 recent=calculate_batch(pd.DataFrame(records),output_start)
 if recent.empty or str(recent["date"].max())!=target:raise ValueError("No target breadth observations")
 history=pd.DataFrame(counts);history["date"]=pd.to_datetime(history["date"]).dt.date
 daily=pd.concat([history[history.date<output_start],recent],ignore_index=True).sort_values("date")
 points=build_sentiment(daily)
 if not points or points[-1]["date"]!=target:raise ValueError("Target score not computed")
 latest=points[-1]
 mapping=[("rqdata-nhnl-breadth","20日新高-新低广度","metrics","nhnlBreadth","%"),("rqdata-above-ma20-breadth","20日均线上方广度","metrics","aboveMaBreadth","%"),("rqdata-nhnl-breadth60","60日新高-新低广度","metrics","nhnlBreadth60","%"),("rqdata-above-ma60-breadth","60日均线上方广度","metrics","aboveMaBreadth60","%"),("rqdata-breadth60-confirmation","60日广度确认","components","breadth60Confirmation","分")]
 old.update(asOf=target,source="BaoStock沪深＋AkShare北交所逐股前复权日线；原20/60日公式及历史统计保留",stockMasterCount=len(prices),points=points,dailyCounts=[{**r,"date":str(r["date"])} for r in daily.to_dict("records")],score=latest["sentiment"],components=latest["components"],metrics=latest["metrics"],phase=latest.get("phase"),phaseLabel=latest.get("phaseLabel"))
 old["series"]=[{"id":sid,"name":name,"unit":unit,"points":[{"date":p["date"],"value":p[section][key]} for p in points]} for sid,name,section,key,unit in mapping]
 old["series"].append({"id":"rqdata-breadth-sentiment","name":"全A市场广度情绪","unit":"分","points":[{"date":p["date"],"value":p["sentiment"]} for p in points]})
 save("rqdata-breadth-sentiment.json",old);print("Breadth updated",target,len(prices),flush=True)
if __name__=="__main__":
 if sys.argv[1]=="combine":combine()
 else:worker(sys.argv[1],int(sys.argv[2]),int(sys.argv[3]))
