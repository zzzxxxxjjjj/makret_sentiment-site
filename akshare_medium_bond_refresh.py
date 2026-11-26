"""Public AkShare SW mixed-bond fund index, complete independently named history."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from public_recovery import read,save,resolve,finite
from completed_session import completed_target
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 target=os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"])
 old=read("akshare-medium-bond.json")
 if old.get("code")=="807330.SW" and old.get("asOf")==target:print("Bond proxy already current",target);return
 frame=resolve(ak,"index_hist_fund_sw")(symbol="807330",period="day")
 points={str(r["日期"])[:10]:float(r["收盘指数"]) for r in frame.to_dict("records") if str(r["日期"])[:10]<=target and finite(r.get("收盘指数")) and float(r["收盘指数"])>0}
 if len(points)<1000 or max(points)!=target:raise ValueError("Incomplete public mixed-bond history")
 save("akshare-medium-bond.json",{"code":"807330.SW","name":"申万宏源混合偏债基金指数","source":"AKShare / 申万基金指数","asOf":max(points),"replaces":"701014.TI","methodology":"采用独立申万混合偏债基金指数；完整历史重算，不拼接原iFind代理值","points":[{"date":d,"value":points[d]} for d in sorted(points)]})
 print("Public mixed-bond proxy",len(points),max(points),flush=True)
if __name__=="__main__":main()
