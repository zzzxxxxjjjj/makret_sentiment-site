"""Aggregate dated public CFFEX option contracts without price-times-volume proxies."""
import io,json,re,os
import requests,pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from public_recovery import read,save
from completed_session import completed_target
def parse(frame,day):
 frame.columns=[str(c).strip() for c in frame.columns]
 codecol=next((c for c in frame if "合约" in c and ("代码" in c or c=="合约")) ,None)
 if not codecol:raise ValueError("Missing contract code")
 codes=frame[codecol].astype(str).str.strip().str.upper()
 mask=codes.str.match(r"^MO\d{4}-?[CP]-?\d+(?:\.\d+)?$")
 f=frame.loc[mask].copy();f["contract"]=codes[mask]
 if len(f)<30 or f["contract"].duplicated().any():raise ValueError("Incomplete or duplicate MO contracts")
 f["side"]=f["contract"].str.extract(r"MO\d{4}-?([CP])")[0]
 call=set(f.loc[f.side=="C","contract"].str.replace("C","X",regex=False))
 put=set(f.loc[f.side=="P","contract"].str.replace("P","X",regex=False))
 if call!=put:raise ValueError("Unpaired MO contract universe")
 output={};totals={}
 for metric,terms in [("amount",["成交金额","成交额"]),("volume",["成交量"]),("oi",["持仓量"])]:
  col=next((c for c in f if any(t in c for t in terms) and "变化" not in c),None)
  if not col:raise ValueError("Missing "+metric+" in "+str(list(f.columns)))
  v=pd.to_numeric(f[col].astype(str).str.replace(",","",regex=False),errors="coerce")
  if v.isna().any() or (v<0).any():raise ValueError("Invalid option "+metric)
  c=float(v[f.side=="C"].sum());p=float(v[f.side=="P"].sum())
  if c<=0:raise ValueError("Zero call denominator")
  output["pcr-"+metric+"-csi1000"]={"date":day,"value":round(p/c,6)}
  totals[metric]={"call":c,"put":p}
 return output,{"contracts":len(f),"totals":totals}
def main():
 from akshare_request_policy import install
 install()
 target=os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
 days=[d for d in read("data-freshness.json")["tradingCalendar"] if "2026-11-18"<d<=target]
 payload=read("akshare-options-pcr.json");series={s["id"]:s for s in payload.get("series",[])}
 status={"targetDate":target,"days":[]}
 for day in days:
  required=["pcr-"+metric+"-csi1000" for metric in ("amount","volume","oi")]
  if all(any(p["date"]==day for p in series.get(sid,{}).get("points",[])) for sid in required):
   status["days"].append({"date":day,"ok":True,"cached":True});continue
  tag=day.replace("-","");errors=[];values=None
  for suffix in ("1","2"):
   try:
    url="http://www.cffex.com.cn/sj/hqsj/rtj/"+tag[:6]+"/"+tag[6:]+"/"+tag+"_"+suffix+".csv"
    r=requests.get(url,timeout=25);r.raise_for_status()
    raw=r.content.decode("gb18030")
    f=pd.read_csv(io.StringIO(raw))
    values,detail=parse(f,day);detail.update(date=day,url=url);break
   except Exception as e:errors.append(type(e).__name__+": "+str(e)[:180])
  if values:
   for sid,point in values.items():
    item=series.setdefault(sid,{"id":sid,"unit":"倍","points":[]})
    points={p["date"]:p for p in item["points"]};points[day]=point
    item.update(points=[points[d] for d in sorted(points)],source="中金所日期CSV；中证1000全部MO认沽/认购合约汇总")
   status["days"].append({"date":day,"ok":True,**detail})
   payload.update(series=list(series.values()),asOf=max(payload.get("asOf",""),day))
   save("akshare-options-pcr.json",payload)
  else:status["days"].append({"date":day,"ok":False,"errors":errors})
  save("option-gap-recovery-status.json",status);print(status["days"][-1],flush=True)
 save("option-gap-recovery-status.json",status)
 if not all(any(p["date"]==target for p in series.get("pcr-"+metric+"-csi1000",{}).get("points",[])) for metric in ("amount","volume","oi")):
  raise SystemExit("Target CFFEX PCR incomplete; earlier successful days retained")
if __name__=="__main__":main()
