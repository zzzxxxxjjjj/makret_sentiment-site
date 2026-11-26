"""Dated Shanghai/Shenzhen units + unadjusted closes, no authenticated source."""
import os,ast,json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from public_recovery import read,save,finite,resolve
from completed_session import completed_target
from etf_net_subscription_refresh import TARGET
ROOT=Path(__file__).resolve().parent
SOURCE="AKShare沪深交易所历史总份额差×当日未复权收盘价；价格缺失时BaoStock补查"
def constants():
 tree=ast.parse((ROOT/"rqdata_refresh.py").read_text(encoding="utf-8"))
 out={}
 for node in tree.body:
  if isinstance(node,ast.Assign):
   for name in node.targets:
    if isinstance(name,ast.Name) and name.id in ("BROAD_KEYWORDS","EXCLUDE_KEYWORDS"):out[name.id]=ast.literal_eval(node.value)
 return out
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 target=os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
 calendar=sorted(d for d in read("data-freshness.json")["tradingCalendar"] if d<=target)
 # First bootstrap fills only the unrefreshed tail. Subsequent runs reuse all verified observations.
 previous=read("public-etf-flow.json")
 last=max((p["date"] for s in previous.get("series",[]) for p in s.get("points",[])),default="2026-11-18")
 days=[d for d in calendar if max("2026-11-18",last)<=d<=target]
 if len(days)<2:days=calendar[-2:]
 status={"targetDate":target,"ok":False,"errors":[],"days":days,"source":SOURCE}
 history=read("etf-shares-history.json");entries={r["date"]:r for r in history.get("entries",[])}
 names={r["code"]:r.get("name","") for r in read("etf-market.json").get("rows",[])}
 def entry(day):return entries.setdefault(day,{"date":day,"shares":{},"close":{}})
 def merge_units(day,code,units,name,provider):
  e=entry(day);e.setdefault("shares",{})[code]=units;e.setdefault("verifiedUnits",{})[code]=provider
  if name and not names.get(code):names[code]=name
 # Import all dated SZSE records, not a realtime snapshot.
 from szse_etf_units_refresh import main as szse
 cached=read("szse-etf-dated-units.json")
 available={r["date"] for r in cached.get("rows",[])}
 if not set(days)<=available:
  os.environ["ETF_UNITS_START"]=days[0];os.environ["DAILY_TARGET_DATE"]=target;szse();cached=read("szse-etf-dated-units.json")
 for r in cached.get("rows",[]):
  if r["date"] in days:merge_units(r["date"],r["code"],r["shares"],r["name"],"SZSE dated units (份)")
 for day in days:
  e=entry(day)
  if sum(c.startswith("5") and p=="SSE dated units (份)" for c,p in e.get("verifiedUnits",{}).items())>500:continue
  try:
   frame=resolve(ak,"fund_etf_scale_sse")(date=day.replace("-",""))
   records=frame.to_dict("records")
   if len(records)<500:raise ValueError("SSE universe incomplete")
   seen=set()
   for r in records:
    if str(r["统计日期"])[:10]!=day:raise ValueError("SSE date mismatch")
    code=str(r["基金代码"]).zfill(6);units=r["基金份额"]
    if code in seen or not finite(units) or float(units)<=0:raise ValueError("Invalid SSE units")
    seen.add(code);merge_units(day,code,float(units),str(r["基金简称"]),"SSE dated units (份)")
  except Exception as exc:status["errors"].append({"source":"SSE","date":day,"error":type(exc).__name__})
 config=constants()
 def broad(code):
  label=names.get(code,"")
  return any(w in label for w in config["BROAD_KEYWORDS"]) and not any(w in label for w in config["EXCLUDE_KEYWORDS"])
 universe={day:sorted(c for c in entry(day).get("verifiedUnits",{}) if broad(c)) for day in days}
 codes=sorted(set(TARGET)|{c for cs in universe.values() for c in cs})
 # Try dated market cache and AKShare unadjusted daily bars before BaoStock.
 market=read("etf-market.json")
 for r in market.get("rows",[]):
  if r.get("asOf") in days and finite(r.get("close")) and r["close"]>0:entry(r["asOf"]).setdefault("close",{})[r["code"]]=r["close"]
 ak_failures=0;missing=[]
 for code in codes:
  if all(finite(entry(d).get("close",{}).get(code)) and entry(d)["close"][code]>0 for d in days):continue
  if ak_failures<2:
   try:
    f=resolve(ak,"fund_etf_hist_em")(symbol=code,period="daily",start_date=days[0].replace("-",""),end_date=target.replace("-",""),adjust="")
    for r in f.to_dict("records"):
     d=str(r["日期"])[:10];v=r["收盘"]
     if d in days and finite(v) and float(v)>0:entry(d).setdefault("close",{})[code]=float(v)
   except Exception:ak_failures+=1
  if not all(finite(entry(d).get("close",{}).get(code)) and entry(d)["close"][code]>0 for d in days):missing.append(code)
 if missing:
  import baostock as bs
  login=bs.login()
  if login.error_code!="0":status["errors"].append({"source":"BaoStock","error":"Login failed"})
  else:
   try:
    for i,code in enumerate(missing):
     q=bs.query_history_k_data_plus(("sh." if code.startswith("5") else "sz.")+code,"date,close",start_date=days[0],end_date=target,adjustflag="3")
     while q.error_code=="0" and q.next():
      r=dict(zip(q.fields,q.get_row_data()));v=r.get("close")
      if r["date"] in days and finite(v) and float(v)>0:entry(r["date"]).setdefault("close",{})[code]=float(v)
     if i%50==0:print("ETF prices",i,len(missing),flush=True)
   finally:bs.logout()
 # Retain every historical date and successful partial observation.
 history["entries"]=[entries[d] for d in sorted(entries)];save("etf-shares-history.json",history)
 def flow(code,prev,day):
  a,b=entry(prev),entry(day)
  if code not in a.get("verifiedUnits",{}) or code not in b.get("verifiedUnits",{}):return None
  p=b.get("close",{}).get(code)
  if not finite(p) or p<=0:return None
  return (b["shares"][code]-a["shares"][code])*p/1e8
 focus_old=read("etf-net-subscription.json");oldrows={r["code"]:r for r in focus_old.get("rows",[])}
 rows=[];focus_series=[]
 for code in TARGET:
  row=dict(oldrows.get(code,{}));pts={p["date"]:p for p in row.get("points",[])}
  for prev,day in zip(days,days[1:]):
   v=flow(code,prev,day)
   if v is not None:pts[day]={"date":day,"value":round(v,6)}
  value=flow(code,days[-2],target)
  row.update(code=code,name=names.get(code,code),asOf=target if value is not None else row.get("asOf"),shares=entry(target).get("shares",{}).get(code),flow1D=round(value,3) if value is not None else None,points=[pts[d] for d in sorted(pts)],flow5D=None)
  last5=calendar[-5:]
  if all(d in pts for d in last5):row["flow5D"]=round(sum(pts[d]["value"] for d in last5),3)
  rows.append(row)
 coverage=sum(r["flow1D"] is not None for r in rows)
 save("etf-net-subscription.json",{"available":coverage>0,"asOf":target if coverage else focus_old.get("asOf"),"source":SOURCE,"note":"ETF整体净申赎估算，不代表汇金自身买卖；5日累计仅在连续5个交易日数据齐全时计算。","rows":rows,"currentCoverage":coverage,"expectedCoverage":len(TARGET)})
 oldpoints={p["date"]:p for s in previous.get("series",[]) if s["id"]=="broad-etf-flow" for p in s.get("points",[])}
 checks=[]
 for prev,day in zip(days,days[1:]):
  selected=universe[day];values={c:flow(c,prev,day) for c in selected};missing=[c for c,v in values.items() if v is None]
  exchanges={c[0] for c in selected}
  good=len(selected)>=100 and "5" in exchanges and "1" in exchanges and not missing
  checks.append({"date":day,"count":len(selected),"missing":missing,"ok":good})
  if good:oldpoints[day]={"date":day,"value":round(sum(values.values()),6)}
 status.update(focusCoverage=coverage,focusExpected=len(TARGET),broadDays=checks,ok=coverage==len(TARGET) and bool(checks) and checks[-1]["ok"])
 save("public-etf-flow.json",{"source":SOURCE,"asOf":max(oldpoints,default=None),"selection":"沿用原宽基关键词及排除词；基金名称来自交易所和ETF行情名单","universe":universe.get(target,[]),"series":[{"id":"broad-etf-flow","name":"宽基ETF日净流量","unit":"亿元","source":SOURCE,"points":[oldpoints[d] for d in sorted(oldpoints)]}]})
 save("etf-share-recovery-status.json",status);print(status,flush=True)
 if not status["ok"]:raise SystemExit(1)
if __name__=="__main__":main()
