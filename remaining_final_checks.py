"""Final bounded public checks; publish ETF quotes only when all 23 displayed funds verify."""
import os,sys,json,subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from public_recovery import read,save,finite,resolve
from completed_session import completed_target
target=completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
report={"targetDate":target,"checks":[]}
def record(name,fn):
 try:report["checks"].append({"id":name,"ok":True,"detail":fn()})
 except Exception as e:report["checks"].append({"id":name,"ok":False,"error":type(e).__name__+": "+str(e)[:700]})
 save("remaining-final-checks.json",report);print(report["checks"][-1],flush=True)
def etf():
 from baostock_etf_fallback import build
 from etf_net_subscription_refresh import TARGET
 done=subprocess.run([sys.executable,"baostock_etf_fallback.py",target],capture_output=True,text=True,timeout=120)
 if done.returncode:raise ValueError("BaoStock public ETF batch failed")
 lines=[l.split("BAOSTOCK_ETF=",1)[1] for l in done.stdout.splitlines() if l.startswith("BAOSTOCK_ETF=")]
 if len(lines)!=1:raise ValueError("No unique dated batch")
 rows=json.loads(lines[0])["rows"];old=read("etf-market.json");exceptions=read("etf-trading-exceptions.json")
 valid={str(r.get("code","")).split(".")[-1] for r in rows if r.get("date")==target and finite(r.get("close")) and float(r["close"])>0 and finite(r.get("amount")) and float(r["amount"])>=0 and r.get("adjustflag","3")=="3"}
 if set(TARGET)-valid:raise ValueError("Displayed key ETF quotes missing: "+",".join(sorted(set(TARGET)-valid)))
 try:value=build(rows,old,target,exceptions);missing=[]
 except ValueError as exc:
  expected={r["code"] for r in old.get("rows",[])}-{c for c,e in exceptions.items() if e.get("inactiveFrom","9999")<=target}
  missing=sorted(expected-valid)
  subset={**old,"rows":[r for r in old["rows"] if r["code"] in valid]}
  value=build(rows,subset,target,exceptions)
  value.update(expectedCoverage=len(expected),unavailableCodes=missing,
   unavailableRows=[r for r in old["rows"] if r["code"] in missing],partialUniverse=True,
   note="23只展示用重点ETF全部核验为同日数据；原行情清单中未返回有效行情的其他ETF保留旧日期，不记零、不计入当前合计。")
  report["checks"].append({"id":"full-etf-universe","ok":False,"error":str(exc)[:700],"missing":missing})
 if old.get("asOf","")>target:raise ValueError("Refusing rollback")
 save("etf-market.json",value)
 return {"asOf":target,"keyCoverage":len(TARGET),"currentRows":len(value["rows"]),"otherMissing":missing}
record("key-etf-turnover",etf)
import akshare as ak
from akshare_request_policy import install
install()
def option_counts():
 f=resolve(ak,"option_risk_indicator_sse")(date=target.replace("-",""))
 g=resolve(ak,"option_daily_stats_sse")(date=target.replace("-",""))
 rows=[]
 for under in ("510050","510300","588000"):
  rows.append({"underlying":under,"riskMasterCount":sum(str(r["合约交易代码"]).startswith(under) for r in f.to_dict("records")),"exchangeStatistics":[{k:str(r[k]) for k in ("合约标的代码","合约数量","认购成交量","认沽成交量","总成交额")} for r in g.to_dict("records") if str(r["合约标的代码"]).split(".")[0]==under]})
 return rows
record("sse-dated-contract-coverage",option_counts)
def macro():
 done=subprocess.run([sys.executable,"macro_tracking_refresh.py","--output","macro-retry-candidate.json"],capture_output=True,text=True,timeout=90)
 if done.returncode:
  lines=[l for l in done.stderr.splitlines() if "Error" in l]
  raise ValueError((lines[-1] if lines else "Existing macro collector failed")[:500])
 return {"candidateWritten":True,"note":"Candidate only; definition validation required before replacing macro history"}
record("existing-macro-collector",macro)
