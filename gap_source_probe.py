"""Probe public exchange data only; no credentials or authenticated raw payloads."""
import json,io
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import pandas as pd,requests
from public_recovery import read,save,resolve
from completed_session import completed_target
ROOT=Path(__file__).resolve().parent
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 target=completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"]);tag=target.replace("-","")
 status={"targetDate":target,"results":[]}
 def attempt(key,fn):
  try:r={"id":key,"ok":True,"detail":fn()}
  except Exception as e:r={"id":key,"ok":False,"errorType":type(e).__name__,"error":str(e)[:250]}
  status["results"].append(r);save("gap-source-probe.json",status);print(json.dumps(r,ensure_ascii=False),flush=True)
 def frame(key,name,kwargs):
  f=resolve(ak,name)(**kwargs)
  save("data_sources/public-gap-"+key+".json",{"targetDate":target,"rows":json.loads(f.to_json(orient="records",date_format="iso",force_ascii=False))})
  return {"rows":len(f),"columns":list(f.columns)}
 (ROOT/"data_sources").mkdir(exist_ok=True)
 def cffex():
  url="https://www.cffex.com.cn/sj/hqsj/rtj/"+tag[:6]+"/"+tag[6:]+"/"+tag+"_2.csv"
  r=requests.get(url,timeout=25);r.raise_for_status();raw=r.content.decode("gb18030")
  if "<html" in raw.lower():raise ValueError("Not CSV")
  (ROOT/"data_sources"/("public-cffex-"+tag+".csv")).write_text(raw,encoding="utf-8")
  f=pd.read_csv(io.StringIO(raw));return {"rows":len(f),"columns":list(f.columns)}
 attempt("cffex-option-daily",cffex)
 attempt("sse-option-risk",lambda:frame("sse-option-risk","option_risk_indicator_sse",{"date":tag}))
 attempt("etf-spot",lambda:frame("etf-spot","fund_etf_spot_em",{}))
 def bj():
  codes=[str(r["代码"]) for r in read("ifind-stock-snapshot.json").get("rows",[]) if str(r["代码"]).startswith(("43","83","87","88","92"))]
  if not codes:raise ValueError("No verified BJ master")
  start=(pd.Timestamp(target)-pd.Timedelta(days=130)).strftime("%Y%m%d")
  return {"master":len(codes),"probe":frame("bj-history","stock_zh_a_hist",{"symbol":codes[0],"period":"daily","start_date":start,"end_date":tag,"adjust":"qfq"})}
 attempt("beijing-history",bj)
 attempt("etf-share-interfaces",lambda:{"matches":[n for n in dir(ak) if "etf" in n and any(t in n for t in ("share","scale","change"))]})
if __name__=="__main__":main()
