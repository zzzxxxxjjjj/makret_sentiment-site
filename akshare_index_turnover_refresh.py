"""Public AkShare index turnover; avoid an unrelated all-market code lookup."""
import os,importlib
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from public_recovery import read,save,resolve,finite
from completed_session import completed_target
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 target=os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
 old=read("akshare-index-turnover.json");prior={s["id"]:s for s in old.get("series",[])}
 legacy={s["id"]:s for s in read("ifind-index-turnover.json").get("series",[])}
 out=[];status={"targetDate":target,"source":"AKShare / 东方财富指数日线","results":[]}
 module=importlib.import_module("akshare.index.index_zh_em")
 original=module.index_code_id_map_em
 module.index_code_id_map_em=lambda:{"000300":1,"000852":1,"000688":1}
 try:
  for code,sid,name in [("000300","hs300-turnover","沪深300换手率"),("000852","csi1000-turnover","中证1000换手率"),("000688","star50-turnover","科创50换手率")]:
   try:
    previous=prior.get(sid,{})
    if previous.get("points") and previous["points"][-1]["date"]==target:out.append(previous);status["results"].append({"id":sid,"ok":True,"cached":True});continue
    # The explicit official SH market codes avoid a failing unrelated list request.
    frame=resolve(ak,"index_zh_a_hist")(symbol=code,period="daily",start_date="20150101",end_date=target.replace("-",""))
    values={str(r["日期"])[:10]:float(r["换手率"]) for r in frame.to_dict("records") if str(r["日期"])[:10]<=target and finite(r.get("换手率")) and 0<=float(r["换手率"])<=100}
    if len(values)<126 or max(values)!=target or not any(values[d] for d in sorted(values)[-20:]):raise ValueError("Target index turnover history incomplete")
    out.append({"id":sid,"name":name,"unit":"%","source":status["source"],"methodology":"采用同源公开完整历史，不混接iFind换手率","points":[{"date":d,"value":values[d]} for d in sorted(values)]})
    status["results"].append({"id":sid,"ok":True,"asOf":max(values),"count":len(values)})
   except Exception as exc:
    if sid in prior:out.append(prior[sid])
    status["results"].append({"id":sid,"ok":False,"error":type(exc).__name__+": "+str(exc)[:240]})
 finally:module.index_code_id_map_em=original
 save("akshare-index-turnover.json",{"series":out,"source":status["source"]});save("akshare-index-turnover-status.json",status);print(status,flush=True)
 if not all(s["ok"] for s in status["results"]):raise SystemExit(1)
if __name__=="__main__":main()
