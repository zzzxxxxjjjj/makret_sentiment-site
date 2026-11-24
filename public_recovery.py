"""Recover supported public inputs, preserve dates and report unsupported definitions."""
import json,math,os,subprocess,sys
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pandas as pd
ROOT=Path(__file__).resolve().parent
def read(n):
 p=ROOT/n
 return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
def save(n,d):
 p=ROOT/n;t=p.with_suffix(".tmp");t.write_text(json.dumps(d,ensure_ascii=False,allow_nan=False),encoding="utf-8");t.replace(p)
def resolve(ak,name):
 try:return getattr(ak,name)
 except AttributeError as e:
  import re
  m=re.search(r"改用 ak\.([A-Za-z_0-9]+)",str(e))
  if not m:raise
  return getattr(ak,m[1])
def finite(v):
 try:return math.isfinite(float(v))
 except (TypeError,ValueError):return False
def merge(a,b):
 d={p["date"]:p for p in a};d.update({p["date"]:p for p in b})
 return [d[k] for k in sorted(d)]
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 from completed_session import completed_target
 target=os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
 os.environ["DAILY_TARGET_DATE"]=target
 result={"targetDate":target,"checkedAt":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),"results":[]}
 def attempt(name,fn):
  try:
   value=fn();result["results"].append({"id":name,"ok":True,"detail":value});print(name+": "+str(value),flush=True)
  except Exception as e:
   result["results"].append({"id":name,"ok":False,"error":str(e)[:500]});print(name+": "+type(e).__name__+" "+str(e)[:200],flush=True)
  save("medium-recovery-status.json" if "--medium-only" in sys.argv else "flows-recovery-status.json" if "--flows-only" in sys.argv else "public-recovery-status.json",result)
 start=(pd.Timestamp(target)-timedelta(days=40)).strftime("%Y%m%d")
 end=target.replace("-","")
 # Fetch missing public inputs using existing validated exchange conversion.
 if not any(v in sys.argv for v in ("--medium-only","--flows-only")): attempt("public-inputs",lambda: subprocess.run([sys.executable,"akshare_public_refresh.py","--sources-only"],timeout=240,check=True).returncode)
 public=read("akshare-public-inputs.json")
 series={s["id"]:s for s in public.get("series",[])}
 base=read("rqdata-broad-sentiment.json")
 def put(sid,name,points,source,unit="亿元"):
  old=series.get(sid,{})
  merged=merge(old.get("points",[]),points)
  if not merged:raise ValueError("No valid data: "+sid)
  series[sid]={**old,"id":sid,"name":name,"unit":unit,"points":merged,"source":source}
  public["series"]=list(series.values());save("akshare-public-inputs.json",public)
 def financing_net():
  balance=series.get("financing-balance",{}).get("points",[])
  if not balance or balance[-1]["date"]!=target:raise ValueError("Exchange financing balance not current")
  data=pd.Series({p["date"]:p["value"] for p in balance}).sort_index()
  # Daily balance difference, not financing purchases.
  points=[{"date":d,"value":float(v)} for d,v in data.diff().dropna().items()]
  put("financing-net","融资净流入",points,"沪深交易所融资余额差分；亿元")
  return {"asOf":points[-1]["date"],"count":len(points)}
 if not any(v in sys.argv for v in ("--medium-only","--flows-only")): attempt("financing-net",financing_net)
 def institutional():
  existing=series.get("institutional-buy",{}).get("points",[])
  if existing and existing[-1]["date"]==target:return {"asOf":target,"alreadyCurrent":True}
  fetch_start=(pd.Timestamp(existing[-1]["date"])+timedelta(days=1)).strftime("%Y%m%d") if existing else start
  f=resolve(ak,"stock_lhb_jgmmtj_em")(start_date=fetch_start,end_date=end)
  save("recovery-lhb-schema.json",{"columns":list(f.columns),"rows":len(f),"sample":json.loads(f.head(3).to_json(orient="records",force_ascii=False,date_format="iso"))})
  needed={"上榜日期","代码","机构买入总额","上榜原因"}
  if not needed.issubset(f.columns):raise ValueError("Unexpected institution schema "+str(list(f.columns)))
  # Multi-session disclosures cannot be allocated to a single session.
  f=f[~f["上榜原因"].astype(str).str.contains(r"连续|累计|三[个]?交易日|[35]个交易日",regex=True)].copy()
  f["date"]=pd.to_datetime(f["上榜日期"]).dt.strftime("%Y-%m-%d")
  f["value"]=pd.to_numeric(f["机构买入总额"],errors="coerce")
  if f["value"].isna().any() or (f["value"]<0).any():raise ValueError("Invalid institutional amount")
  keys=["date","代码"]
  # Different listing reasons duplicate a stock's institution totals.
  if (f.groupby(keys)["value"].nunique()>1).any():raise ValueError("Ambiguous repeated institutional totals")
  f=f.drop_duplicates(keys)
  sums=f.groupby("date")["value"].sum()/1e8
  if sums.empty or sums.index.max()!=target:raise ValueError("No verified target-date institutional disclosure")
  pts=[{"date":d,"value":float(v)} for d,v in sums.items() if d<=target]
  put("institutional-buy","机构买入额（龙虎榜单日榜）",pts,"AKShare / 东方财富机构买卖每日统计；剔除多日累计，按股票日期去重")
  old=next((s.get("points",[]) for s in base.get("series",[]) if s["id"]=="institutional-buy"),[])
  allp=merge(old,series["institutional-buy"]["points"])
  vals=pd.Series({p["date"]:p["value"] for p in allp}).sort_index().rolling(5,min_periods=5).mean().dropna()
  put("institutional-buy-ma5","机构买入额 MA5",[{"date":d,"value":float(v)} for d,v in vals.items()],"AKShare / 机构专用单日榜买入额5日均线")
  return {"asOf":pts[-1]["date"],"days":len(pts)}
 if "--medium-only" not in sys.argv: attempt("institutional-buy",institutional)
 def lhb_net():
  existing=series.get("dragon-tiger-net-inflow",{}).get("points",[])
  if existing and existing[-1]["date"]==target:return {"asOf":target,"alreadyCurrent":True}
  cache=read("lhb-daily-cache.json").get("points",[])
  fetch_start=(pd.Timestamp(cache[-1]["date"])+timedelta(days=1)).strftime("%Y%m%d") if cache else start
  f=resolve(ak,"stock_lhb_detail_em")(start_date=fetch_start,end_date=end)
  f=f[~f["上榜原因"].astype(str).str.contains(r"连续|累计|三[个]?交易日|[35]个交易日",regex=True)].copy()
  f["date"]=pd.to_datetime(f["上榜日"]).dt.strftime("%Y-%m-%d")
  f["value"]=pd.to_numeric(f["龙虎榜净买额"],errors="coerce")
  if f["value"].isna().any():raise ValueError("Missing LHB net amount")
  if (f.groupby(["date","代码"])["value"].nunique()>1).any():raise ValueError("Ambiguous duplicate LHB stock/date totals")
  f=f.drop_duplicates(["date","代码"])
  sums=f.groupby("date")["value"].sum()/1e8
  days=[d for d in read("data-freshness.json")["tradingCalendar"] if start<=d.replace("-","")<=end]
  if len(days)<20 or sums.empty or max(sums.index)!=target:raise ValueError("Insufficient verified LHB range")
  daily={p["date"]:p["value"] for p in cache}
  daily.update({d:float(sums.get(d,0)) for d in days if d.replace("-","")>=fetch_start})
  save("lhb-daily-cache.json",{"points":[{"date":d,"value":daily[d]} for d in sorted(daily)]})
  vals=pd.Series(daily).sort_index().rolling(20,min_periods=20).sum().dropna()
  put("dragon-tiger-net-inflow","龙虎榜资金净流入（20日滚动）",[{"date":d,"value":float(v)} for d,v in vals.items()],"AKShare / 龙虎榜单日榜买卖净额，股票日期去重，20交易日累计")
  return {"asOf":max(vals.index),"count":len(vals)}
 if "--medium-only" not in sys.argv: attempt("lhb-net-20d",lhb_net)
 def medium():
  cloud=read("cloud-market-inputs.json")
  if cloud.get("modelVersion")!="cloud-v2":raise ValueError("Unknown medium model")
  # Remove only non-session equity observations introduced during this recovery.
  for key in ("pe","equity","dividend","bond"):
   cloud["inputs"][key]=[p for p in cloud["inputs"][key] if p["date"]<="2026-11-18" or datetime.fromisoformat(p["date"]).weekday()<5]
  evidence={}
  def append_checked(key,incoming):
   old=cloud["inputs"][key];prior={p["date"]:p["value"] for p in old}
   pairs=[(prior[p["date"]],p["value"]) for p in incoming if p["date"] in prior]
   evidence[key+"RecentOverlap"]=[{"date":p["date"],"old":prior[p["date"]],"new":p["value"]} for p in incoming if p["date"] in prior][-5:]
   if len(pairs)<3:raise ValueError(key+": need >=3 overlap observations to verify definition")
   err=max(abs(a-b)/max(abs(a),1e-8) for a,b in pairs)
   evidence[key]={"overlap":len(pairs),"maxRelativeError":err}
   if err>.001:raise ValueError(key+": source definition differs in overlap "+str(err))
   new=[p for p in incoming if p["date"]>old[-1]["date"] and p["date"]<=target and (key=="yield" or datetime.fromisoformat(p["date"]).weekday()<5)]
   cloud["inputs"][key]=merge(old,new)
   save("cloud-market-inputs.json",cloud)
  latest=read("akshare-medium-inputs.json")
  for key,sid in [("pe","csi-all-share-pe-rolling"),("equity","csi-all-share-close"),("dividend","csi-all-share-dividend-yield")]:
   try:append_checked(key,next(s["points"] for s in latest["series"] if s["id"]==sid))
   except Exception as e:evidence[key]={"error":str(e)}
  try:
   f=resolve(ak,"bond_china_yield")(start_date=start,end_date=end)
   f=f[f["曲线名称"]=="中债国债收益率曲线"]
   incoming=[{"date":str(r["日期"])[:10],"value":float(r["10年"])} for r in f.to_dict("records") if finite(r["10年"])]
   append_checked("yield",incoming)
  except Exception as e:evidence["yield"]={"error":str(e)}
  try:
   f=resolve(ak,"stock_zh_index_hist_csindex")(symbol="000012",start_date=start,end_date=end)
   append_checked("bond",[{"date":str(r["日期"])[:10],"value":float(r["收盘"])} for r in f.to_dict("records") if finite(r["收盘"])])
  except Exception as e:evidence["bond"]={"error":str(e)}
  cloud["asOf"]=min(v[-1]["date"] for v in cloud["inputs"].values())
  save("cloud-market-inputs.json",cloud)
  evidence["dates"]={k:{"first":v[0]["date"],"last":v[-1]["date"],"count":len(v)} for k,v in cloud["inputs"].items()}
  save("medium-input-audit.json",evidence)
  return evidence
 if "--flows-only" not in sys.argv: attempt("medium-model-inputs",medium)
 # Capture exact schemas for the remaining missing metrics for subsequent verified adapters.
 probes=[
 ("financing-detail-sh","stock_margin_detail_sse",{"date":end}),
 ("financing-detail-sz","stock_margin_detail_szse",{"date":end}),
 ("lhb-net","stock_lhb_detail_em",{"start_date":start,"end_date":end}),
 ("options-sse","option_daily_stats_sse",{"date":end}),
 ("options-cffex","option_cffex_zz1000_daily_sina",{"symbol":"mo2612C6000"}),
 ]
 for key,name,kwargs in ([] if any(v in sys.argv for v in ("--medium-only","--flows-only")) else probes):
  def probe(name=name,kwargs=kwargs,key=key):
   f=resolve(ak,name)(**kwargs)
   save("recovery-"+key+".json",{"columns":list(f.columns),"rows":len(f),"sample":json.loads(f.head(3).to_json(orient="records",force_ascii=False,date_format="iso"))})
   return {"rows":len(f),"columns":list(f.columns)}
  attempt(key,probe)
 save("public-recovery-status.json",result)
if __name__=="__main__":main()
