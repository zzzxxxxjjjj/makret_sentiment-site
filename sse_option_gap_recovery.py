"""Recover SSE amount PCR using dated contract master and verified historical bars."""
import json,os,sys,requests
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from public_recovery import read,save,resolve,finite
from completed_session import completed_target
ROOT=Path(__file__).resolve().parent
MAP={"510050":"sz50","510300":"hs300","588000":"star50"}
def target_day():
 return os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
def plan():
 import akshare as ak
 from akshare_request_policy import install
 install();target=target_day()
 days=[d for d in read("data-freshness.json")["tradingCalendar"] if "2026-11-18"<d<=target and datetime.fromisoformat(d).weekday()<5]
 master={};expected={}
 for day in days:
  f=resolve(ak,"option_risk_indicator_sse")(date=day.replace("-",""))
  rows=[]
  for r in f.to_dict("records"):
   trade=str(r["合约交易代码"]);under=trade[:6]
   if under not in MAP:continue
   if str(r["交易日期"])[:10]!=day:raise ValueError("Contract master date mismatch")
   side=trade[6:7]
   if side not in ("C","P"):raise ValueError("Unknown option side")
   code=str(r["合约编码"]).split(".")[0]
   rows.append({"code":code,"under":under,"side":side})
  if len({r["code"] for r in rows})!=len(rows):raise ValueError("Duplicate dated contracts")
  stats=resolve(ak,"option_daily_stats_sse")(date=day.replace("-",""))
  expected[day]={}
  for row in stats.to_dict("records"):
   code=str(row["合约标的代码"]).split(".")[0]
   if code in MAP:expected[day][code]={"contracts":int(row["合约数量"]),"callVolume":float(row["认购成交量"]),"putVolume":float(row["认沽成交量"]),"totalAmount":float(row["总成交额"])}
  for under in MAP:
   if under not in expected[day] or sum(r["under"]==under for r in rows)!=expected[day][under]["contracts"]:raise ValueError("Contract master coverage differs from daily statistics")
  master[day]=rows
 save("sse-option-plan.json",{"targetDate":target,"master":master,"expected":expected})
 print("SSE plan",len({r["code"] for rows in master.values() for r in rows}),days,flush=True)
def worker(shard,shards):
 from akshare_request_policy import install
 install()
 config=read("sse-option-plan.json");days=sorted(config["master"]);target=config["targetDate"]
 codes=sorted({r["code"] for rows in config["master"].values() for r in rows})[shard::shards]
 cache=ROOT/".option-bar-cache";cache.mkdir(exist_ok=True)
 output={"targetDate":target,"bars":{},"errors":[]}
 for i,code in enumerate(codes):
  p=cache/(code+".json")
  if p.exists():
   old=json.loads(p.read_text())
   if old.get("targetDate")==target:output["bars"][code]=old["bars"];continue
  try:
   data=requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",params={"secid":"10."+code,"klt":"101","fqt":"0","beg":days[0].replace("-",""),"end":target.replace("-",""),"fields1":"f1,f2,f3,f4,f5,f6","fields2":"f51,f52,f53,f54,f55,f56,f57"},timeout=(8,25)).json()
   raw=(data.get("data") or {}).get("klines") or []
   bars={}
   for line in raw:
    fields=line.split(",");day=fields[0]
    if day not in days:continue
    if len(fields)<7 or not finite(fields[5]) or not finite(fields[6]):raise ValueError("Invalid contract bar")
    volume,amount=float(fields[5]),float(fields[6])
    if volume<0 or amount<0:raise ValueError("Negative contract amount")
    bars[day]={"volume":volume,"amount":amount}
   if not bars:raise ValueError("Empty contract daily bars")
   output["bars"][code]=bars;p.write_text(json.dumps({"targetDate":target,"bars":bars}),encoding="utf-8")
  except Exception as e:output["errors"].append({"code":code,"error":type(e).__name__})
  if i%10==0:print("option shard",shard,i,len(codes),flush=True)
 save("option-bar-parts/shard-"+str(shard)+".json",output)
def combine():
 config=read("sse-option-plan.json");bars={};errors=[]
 for p in (ROOT/"option-bar-parts").rglob("shard-*.json"):
  data=json.loads(p.read_text())
  if data["targetDate"]!=config["targetDate"]:raise ValueError("Option shard date mismatch")
  if bars.keys()&data["bars"].keys():raise ValueError("Duplicate shard contracts")
  bars.update(data["bars"]);errors.extend(data["errors"])
 payload=read("akshare-options-pcr.json");series={s["id"]:s for s in payload.get("series",[])}
 status={"targetDate":config["targetDate"],"contractErrors":errors,"days":[]}
 for day,master in config["master"].items():
  for under,key in MAP.items():
   try:
    rows=[r for r in master if r["under"]==under]
    sums={side:{"volume":0.,"amount":0.} for side in ("C","P")}
    for row in rows:
     bar=bars.get(row["code"],{}).get(day)
     if not bar:raise ValueError("Missing contract/day "+row["code"])
     for metric in ("volume","amount"):sums[row["side"]][metric]+=bar[metric]
    expected=config["expected"][day][under]
    if sums["C"]["volume"]!=expected["callVolume"] or sums["P"]["volume"]!=expected["putVolume"]:raise ValueError("Contract volume totals differ from exchange")
    amount=sums["C"]["amount"]+sums["P"]["amount"]
    if min(abs(amount-expected["totalAmount"]*scale)/max(amount,1) for scale in (1,10000))>.001:raise ValueError("Contract amount totals differ from exchange")
    if sums["C"]["amount"]<=0:raise ValueError("No call amount")
    sid="pcr-amount-"+key
    item=series.setdefault(sid,{"id":sid,"unit":"倍","points":[]})
    points={p["date"]:p for p in item["points"]};points[day]={"date":day,"value":round(sums["P"]["amount"]/sums["C"]["amount"],6)}
    item.update(points=[points[d] for d in sorted(points)],source="AkShare上交所日期合约清单＋东方财富历史成交额；核对交易所成交量及总成交额")
    status["days"].append({"date":day,"underlying":under,"ok":True,"contracts":len(rows)})
   except Exception as e:status["days"].append({"date":day,"underlying":under,"ok":False,"error":str(e)})
 payload.update(series=list(series.values()))
 save("akshare-options-pcr.json",payload);save("sse-option-gap-status.json",status);print(status,flush=True)
if __name__=="__main__":
 if sys.argv[1]=="plan":plan()
 elif sys.argv[1]=="combine":combine()
 else:worker(int(sys.argv[1]),int(sys.argv[2]))
