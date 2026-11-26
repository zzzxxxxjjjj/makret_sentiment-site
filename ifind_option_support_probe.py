"""Verify current iFind access without exposing credentials or raw responses."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from ifind_client import Client
from pathlib import Path
status={"checkedAt":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),"usable":False,"results":[]}
c=Client()
try:
 c.authenticate()
 status["authentication"]="ok"
 for name in ("上证50ETF","沪深300ETF","科创50ETF"):
  try:
   r=c.post("smart_stock_picking",{"searchstring":"2026年11月25日"+name+"期权认购成交额、认沽成交额","searchtype":"option"})
   tables=r.get("tables") or []
   columns=[str(k) for t in tables for k in (t.get("table") or {})]
   status["results"].append({"underlying":name,"columns":columns,"returnedTables":len(tables),"note":"返回字段仍需按日期、单位及覆盖范围核验；不自动发布"})
  except Exception as e:status["results"].append({"underlying":name,"error":str(e)})
except Exception as e:status["authentication"]="failed";status["error"]=str(e)
Path("ifind-option-support-status.json").write_text(json.dumps(status,ensure_ascii=False),encoding="utf-8")
print(json.dumps(status,ensure_ascii=False))
