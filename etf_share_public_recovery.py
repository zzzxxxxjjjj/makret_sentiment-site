"""Recover dated SSE ETF share history; never date SZSE undated current scale as history."""
import os,json
from public_recovery import read,save,resolve,finite
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 target=read("public-recovery-status.json")["targetDate"]
 calendar=[d for d in read("data-freshness.json")["tradingCalendar"] if d<=target]
 days=calendar[-2:]
 from etf_net_subscription_refresh import TARGET,compute
 codes=[c for c in TARGET if c.startswith("5")]
 market=read("etf-market.json")
 if market.get("asOf")!=target:raise ValueError("Target-date ETF close missing")
 close={r["code"]:r["close"] for r in market["rows"]}
 history=read("etf-shares-history.json");entries={r["date"]:r for r in history.get("entries",[])}
 result={"targetDate":target,"sseCodes":len(codes),"szseStatus":"Current-scale endpoint has no observation-date field; not used as dated history."}
 for day in days:
  f=resolve(ak,"fund_etf_scale_sse")(date=day.replace("-",""))
  records={}
  for r in f.to_dict("records"):
   if str(r["统计日期"])[:10]!=day:raise ValueError("SSE share observation date mismatch")
   c=str(r["基金代码"]).zfill(6)
   if c in codes and finite(r["基金份额"]) and float(r["基金份额"])>0:records[c]=float(r["基金份额"])
  if set(records)!=set(codes):raise ValueError("Missing SSE key ETF shares: "+str(set(codes)-records.keys()))
  # Keep original observations for other dates; new date contains only verified shares.
  entry=entries.setdefault(day,{"date":day,"shares":{},"close":{}})
  entry["shares"].update(records)
  if day==target:entry["close"].update({c:close[c] for c in codes})
  entry["shareSource"]="AKShare / SSE dated ETF units"
 history["entries"]=[entries[d] for d in sorted(entries)]
 save("etf-shares-history.json",history)
 value=compute()
 for row in value["rows"]:
  row["asOf"]=target if row["code"] in codes else None
  if row["code"] not in codes:row.update(flow1D=None,flow5D=None,shares=None)
  # The previous six cache entries may have gaps; do not label them five trading days.
  row["flow5D"]=None
 value.update(source="AKShare / 上交所指定日期份额差 × 当日收盘价",note="仅沪市重点ETF核验日净申赎；深市历史份额未齐，保留缺失，不填零；5日累计待连续份额与每日价格核验。",currentCoverage=len(codes),expectedCoverage=len(TARGET))
 save("etf-net-subscription.json",value);result["ok"]=True;result["asOf"]=value["asOf"]
 save("etf-share-recovery-status.json",result);print(result)
if __name__=="__main__":
 try:main()
 except Exception as e:
  save("etf-share-recovery-status.json",{"ok":False,"error":str(e)[:500]});raise
