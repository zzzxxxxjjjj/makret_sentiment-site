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
  save("public-recovery-status.json",result)
 start=(pd.Timestamp(target)-timedelta(days=40)).strftime("%Y%m%d")
 end=target.replace("-","")
 # Fetch missing public inputs using existing validated exchange conversion.
 attempt("public-inputs",lambda: subprocess.run([sys.executable,"akshare_public_refresh.py","--sources-only"],timeout=240).returncode)
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
 attempt("financing-net",financing_net)
 def institutional():
  f=resolve(ak,"stock_lhb_jgmmtj_em")(start_date=start,end_date=end)
  save("recovery-lhb-schema.json",{"columns":list(f.columns),"rows":len(f),"sample":json.loads(f.head(3).to_json(orient="records",force_ascii=False,date_format="iso"))})
  needed={"上榜日期","代码","机构买入总额","上榜原因"}
  if not needed.issubset(f.columns):raise ValueError("Unexpected institution schema "+str(list(f.columns)))
  # Multi-session disclosures cannot be allocated to a single session.
  f=f[~f["上榜原因"].astype(str).str.contains("三|3|五|5|累计",regex=True)].copy()
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
 attempt("institutional-buy",institutional)
 def medium():
  cloud=read("cloud-market-inputs.json")
  if cloud.get("modelVersion")!="cloud-v2":raise ValueError("Unknown medium model")
  evidence={}
  def append_checked(key,incoming):
   old=cloud["inputs"][key];prior={p["date"]:p["value"] for p in old}
   pairs=[(prior[p["date"]],p["value"]) for p in incoming if p["date"] in prior]
   if len(pairs)<3:raise ValueError(key+": need >=3 overlap observations to verify definition")
   err=max(abs(a-b)/max(abs(a),1e-8) for a,b in pairs)
   evidence[key]={"overlap":len(pairs),"maxRelativeError":err}
   if err>.001:raise ValueError(key+": source definition differs in overlap "+str(err))
   new=[p for p in incoming if p["date"]>old[-1]["date"] and p["date"]<=target]
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
 attempt("medium-model-inputs",medium)
 # Capture exact schemas for the remaining missing metrics for subsequent verified adapters.
 probes=[
 ("financing-detail-sh","stock_margin_detail_sse",{"date":end}),
 ("financing-detail-sz","stock_margin_detail_szse",{"date":end}),
 ("lhb-net","stock_lhb_detail_em",{"start_date":start,"end_date":end}),
 ("options-sse","option_daily_stats_sse",{"date":end}),
 ("options-cffex","option_cffex_mo_daily_sina",{"symbol":"mo"}),
 ]
 for key,name,kwargs in probes:
  def probe(name=name,kwargs=kwargs,key=key):
   f=resolve(ak,name)(**kwargs)
   save("recovery-"+key+".json",{"columns":list(f.columns),"rows":len(f),"sample":json.loads(f.head(3).to_json(orient="records",force_ascii=False,date_format="iso"))})
   return {"rows":len(f),"columns":list(f.columns)}
  attempt(key,probe)
 save("public-recovery-status.json",result)
if __name__=="__main__":main()
