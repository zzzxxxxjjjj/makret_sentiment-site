"""Recover index financing only after exchange totals and index membership validate."""
import json,os,math,socket,sys
from pathlib import Path
import pandas as pd
from public_recovery import read,save,resolve,finite
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 from datetime import datetime
 from zoneinfo import ZoneInfo
 from completed_session import completed_target
 target=os.environ.get("DAILY_TARGET_DATE") or completed_target(datetime.now(ZoneInfo("Asia/Shanghai")),read("data-freshness.json")["tradingCalendar"]);stamp=target.replace("-","")
 status={"targetDate":target,"results":[]};out={"targetDate":target,"series":[]}
 def attempt(name,fn):
  try:status["results"].append({"id":name,"ok":True,"detail":fn()})
  except Exception as e:status["results"].append({"id":name,"ok":False,"error":str(e)[:500]})
  save("index-recovery-status.json",status);print(status["results"][-1],flush=True)
 def publish_out():
  previous=read("public-index-inputs.json")
  merged={item["id"]:item for item in previous.get("series",[])}
  for item in out["series"]:
   old=merged.get(item["id"],{})
   points={p["date"]:p for p in old.get("points",[])}
   points.update({p["date"]:p for p in item["points"]})
   merged[item["id"]]={**item,"points":[points[d] for d in sorted(points)]}
  out["series"]=list(merged.values())
  save("public-index-inputs.json",out)
 def indexes():
  def financing_values():
   cached=read("financing-detail-cache.json")
   if cached.get("asOf")==target and cached.get("buys"):
    values=cached["buys"]
   else:
    sh=resolve(ak,"stock_margin_detail_sse")(date=stamp)
    sz=resolve(ak,"stock_margin_detail_szse")(date=stamp)
    sht=resolve(ak,"stock_margin_sse")(start_date=stamp,end_date=stamp)
    szt=resolve(ak,"stock_margin_szse")(date=stamp)
    sh=sh[sh["信用交易日期"].astype(str)==stamp]
    # AKShare's one-page response can be capped by SSE. Follow real pagination.
    if len(sht)==1 and abs(pd.to_numeric(sh["融资买入额"]).sum()-float(sht.iloc[0]["融资买入额"]))>100:
     import requests
     params={"isPagination":"true","tabType":"mxtype","detailsDate":stamp,"stockCode":"","beginDate":"","endDate":"","pageHelp.pageSize":"1000","pageHelp.pageNo":"1","pageHelp.beginPage":"1","pageHelp.cacheSize":"1","pageHelp.endPage":"1"}
     records=[];total=None
     for page in range(1,11):
      params["pageHelp.pageNo"]=str(page)
      params["pageHelp.beginPage"]=str(page)
      params["pageHelp.endPage"]=str(page)
      response=requests.get("https://query.sse.com.cn/marketdata/tradedata/queryMargin.do",params=params,headers={"Referer":"https://www.sse.com.cn/","User-Agent":"Mozilla/5.0"},timeout=30)
      response.raise_for_status();data=response.json();rows=data.get("result") or []
      if page==1:
       help=data.get("pageHelp") or {};total=int(help.get("total") or help.get("totalCount") or 0)
       save("recovery-sse-pagination.json",{"pageHelp":{k:v for k,v in help.items() if k!="data"},"keys":list(rows[0]) if rows else [],"sample":rows[:1]})
      if not rows:break
      records.extend(rows)
      if total and len(records)>=total:break
     frame=pd.DataFrame(records)
     if frame.shape[1]!=13:raise ValueError("Unknown SSE pagination schema")
     frame=frame.rename(columns={"opDate":"信用交易日期","rzmre":"融资买入额","stockCode":"标的证券代码"})
     frame=frame.drop_duplicates(["信用交易日期","标的证券代码"])
     frame["融资买入额"]=pd.to_numeric(frame["融资买入额"],errors="raise")
     sh=frame[frame["信用交易日期"].astype(str)==stamp]
    if len(sht)!=1 or len(szt)!=1:raise ValueError("Missing exchange totals")
    for frame,total,tolerance in [(sh,float(sht.iloc[0]["融资买入额"]),100),(sz,float(szt.iloc[0]["融资买入额"])*1e8,1e6)]:
     actual=pd.to_numeric(frame["融资买入额"],errors="raise").sum()
     if abs(actual-total)>tolerance:raise ValueError("Exchange detail incomplete: "+str(actual)+" versus "+str(total))
    values={}
    for frame,col in [(sh,"标的证券代码"),(sz,"证券代码")]:
     values.update({str(r[col]).zfill(6):float(r["融资买入额"]) for r in frame.to_dict("records")})
    save("financing-detail-cache.json",{"asOf":target,"buys":values})
   return values
  try:values=financing_values()
  except Exception as e:
   values=None
   print("Financing failed; collecting turnover independently: "+str(e),flush=True)
  snapshot=read("ifind-stock-snapshot.json")
  if snapshot.get("asOf")!=target:snapshot={"rows":[]}
  amounts={str(r["代码"]).zfill(6):float(r["成交额"]) for r in snapshot["rows"] if finite(r.get("成交额"))}
  if not amounts:
   import baostock as bs
   socket.setdefaulttimeout(20)
   login=bs.login()
   if login.error_code=="0":
    try:
     q=bs.query_daily_history_k_AStock(date=target)
     while q.error_code=="0" and q.next():
      row=dict(zip(q.fields,q.get_row_data()))
      if row.get("date")==target and finite(row.get("amount")) and float(row["amount"])>=0:
       amounts[row["code"].split(".")[-1]]=float(row["amount"])
     print("BaoStock dated market amounts: "+str(len(amounts)),flush=True)
    finally:bs.logout()
  results=[]
  for code,prefix,name,count in [("000016","sse50","上证50",50),("000300","hs300","沪深300",300),("000852","csi1000","中证1000",1000),("000688","star50","科创50",50)]:
   previous=read("public-index-inputs.json")
   completed=[s for s in previous.get("series",[]) if s["id"].startswith(prefix+"-") and s.get("points") and s["points"][-1]["date"]==target]
   if len(completed)==3:
    out["series"].extend(completed);results.append({"code":code,"alreadyCurrent":True});continue
   try:
    f=resolve(ak,"index_stock_cons_csindex")(symbol=code)
    save("recovery-members-"+prefix+".json",{"columns":list(f.columns),"rows":len(f),"sample":json.loads(f.head(2).to_json(orient="records",force_ascii=False,date_format="iso"))})
    if "日期" not in f or set(pd.to_datetime(f["日期"]).dt.strftime("%Y-%m-%d"))!={target}:raise ValueError("Exact-date membership unavailable for "+code)
    members=set(f["成分券代码"].astype(str).str.zfill(6))
    if len(members)!=count:raise ValueError("Wrong membership count "+code+" "+str(len(members)))
    buy=sum(values.get(c,0) for c in members)/1e8 if values is not None else None
    if buy is not None:
     out["series"].append({"id":prefix+"-financing-buy","name":name+"融资买入额","unit":"亿元","source":"交易所完整融资明细；独立于成交额更新","points":[{"date":target,"value":buy}]})
     publish_out()
    if "600185" in members and target in ("2026-11-23","2026-11-24"):
     amounts["600185"]=0.0
    if len(members-amounts.keys())>20:
     raise ValueError("Bulk target-date turnover unavailable; refusing per-stock request burst")
    for stock in sorted(members-amounts.keys()):
     try:
      frame=resolve(ak,"stock_zh_a_hist")(symbol=stock,period="daily",start_date=stamp,end_date=stamp,adjust="")
      rows=[r for r in frame.to_dict("records") if str(r.get("日期"))[:10]==target]
      if len(rows)==1 and finite(rows[0].get("成交额")) and float(rows[0]["成交额"])>=0:amounts[stock]=float(rows[0]["成交额"])
     except Exception:pass
    missing=members-amounts.keys()
    if missing:
     import baostock as bs
     socket.setdefaulttimeout(20)
     login=bs.login()
     if login.error_code!="0":raise ValueError("Baostock missing-amount login failed")
     try:
      for stock in sorted(missing):
       security=("sh." if stock.startswith("6") else "sz.")+stock
       query=bs.query_history_k_data_plus(security,"date,code,amount,tradestatus",start_date=target,end_date=target,adjustflag="3")
       rows=[]
       while query.error_code=="0" and query.next():rows.append(dict(zip(query.fields,query.get_row_data())))
       if len(rows)==1 and rows[0]["date"]==target and rows[0]["code"]==security:
        if rows[0].get("tradestatus")=="0":amounts[stock]=0.0
        elif finite(rows[0].get("amount")) and float(rows[0]["amount"])>=0:amounts[stock]=float(rows[0]["amount"])
     finally:bs.logout()
    for stock in sorted(members-amounts.keys()):
     try:
      frame=resolve(ak,"stock_zh_a_hist")(symbol=stock,period="daily",start_date=stamp,end_date=stamp,adjust="")
      rows=[r for r in frame.to_dict("records") if str(r.get("日期"))[:10]==target]
      if len(rows)==1 and finite(rows[0].get("成交额")) and float(rows[0]["成交额"])>=0:amounts[stock]=float(rows[0]["成交额"])
     except Exception:pass
    if members-amounts.keys():raise ValueError("Missing constituent amounts "+code+" "+",".join(sorted(members-amounts.keys())))
    amount=sum(amounts[c] for c in members)/1e8
    if amount<=0:raise ValueError("Invalid denominator")
    for suffix,label,val,unit in ([("turnover-amount","成交额",amount,"亿元")]+([("financing-activity","融资买入额占比",buy/amount*100,"%")] if buy is not None else [])):
     out["series"].append({"id":prefix+"-"+suffix,"name":name+label,"unit":unit,"source":"当日指数成分股；已核验成交额缓存，缺项AkShare优先、BaoStock补齐；确认停牌记零","points":[{"date":target,"value":val}]})
    results.append({"code":code,"buy":buy,"amount":amount,**({"error":"Financing detail unavailable; turnover independently published"} if buy is None else {})})
    publish_out()
   except Exception as e:
    results.append({"code":code,"error":str(e)[:300]})
    continue
  publish_out();return results
 attempt("index-financing",indexes)
 def bao():
  import baostock as bs
  socket.setdefaulttimeout(20)
  login=bs.login()
  if login.error_code!="0":raise ValueError("Baostock login "+login.error_code)
  try:
   r=bs.query_all_stock(day=target);rows=[]
   while r.error_code=="0" and r.next():rows.append(dict(zip(r.fields,r.get_row_data())))
   if r.error_code!="0":raise ValueError(r.error_msg)
   stocks=[r for r in rows if str(r.get("code","")).startswith(("sh.60","sh.68","sz.00","sz.30","bj."))]
   bj=[r for r in stocks if r["code"].startswith("bj.")]
   if not bj:raise ValueError("Baostock universe has "+str(len(stocks))+" SH/SZ A shares but no Beijing stocks; cannot preserve original all-A breadth definition.")
   return {"stocks":len(stocks),"beijing":len(bj)}
  finally:bs.logout()
 if "--daily" not in sys.argv:attempt("breadth-baostock-universe",bao)
 if "--daily" in sys.argv:
  item=next(r for r in status["results"] if r["id"]=="index-financing")
  if not item["ok"] or any("error" in r for r in item.get("detail",[])):raise SystemExit(1)
if __name__=="__main__":main()
