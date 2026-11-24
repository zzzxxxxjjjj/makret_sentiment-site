"""Recover index financing only after exchange totals and index membership validate."""
import json,os,math,socket
from pathlib import Path
import pandas as pd
from public_recovery import read,save,resolve,finite
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 target=read("public-recovery-status.json")["targetDate"];stamp=target.replace("-","")
 status={"targetDate":target,"results":[]};out={"targetDate":target,"series":[]}
 def attempt(name,fn):
  try:status["results"].append({"id":name,"ok":True,"detail":fn()})
  except Exception as e:status["results"].append({"id":name,"ok":False,"error":str(e)[:500]})
  save("index-recovery-status.json",status);print(status["results"][-1],flush=True)
 def indexes():
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
    response=requests.get("https://query.sse.com.cn/marketdata/tradedata/queryMargin.do",params=params,headers={"Referer":"https://www.sse.com.cn/","User-Agent":"Mozilla/5.0"},timeout=30)
    response.raise_for_status();data=response.json();rows=data.get("result") or []
    if page==1:
     help=data.get("pageHelp") or {};total=int(help.get("total") or help.get("totalCount") or 0)
     save("recovery-sse-pagination.json",{"pageHelp":help,"keys":list(rows[0]) if rows else [],"sample":rows[:1]})
    if not rows:break
    records.extend(rows)
    if total and len(records)>=total:break
   frame=pd.DataFrame(records)
   if frame.shape[1]!=13:raise ValueError("Unknown SSE pagination schema")
   frame.columns=["_0","信用交易日期","_2","_3","_4","_5","_6","_7","融资买入额","_9","_10","_11","标的证券代码"]
   frame=frame.drop_duplicates(["信用交易日期","标的证券代码"])
   frame["融资买入额"]=pd.to_numeric(frame["融资买入额"],errors="raise")
   sh=frame[frame["信用交易日期"].astype(str)==stamp]
  if len(sht)!=1 or len(szt)!=1:raise ValueError("Missing exchange totals")
  for frame,total in [(sh,float(sht.iloc[0]["融资买入额"])),(sz,float(szt.iloc[0]["融资买入额"])*1e8)]:
   actual=pd.to_numeric(frame["融资买入额"],errors="raise").sum()
   if abs(actual-total)>max(100,total*0.00001):raise ValueError("Exchange detail incomplete: "+str(actual)+" versus "+str(total))
  values={}
  for frame,col in [(sh,"标的证券代码"),(sz,"证券代码")]:
   values.update({str(r[col]).zfill(6):float(r["融资买入额"]) for r in frame.to_dict("records")})
  snapshot=read("ifind-stock-snapshot.json")
  if snapshot.get("asOf")!=target or len(snapshot.get("rows",[]))<4000:raise ValueError("Exact-date all-share amount snapshot missing")
  amounts={str(r["代码"]).zfill(6):float(r["成交额"]) for r in snapshot["rows"] if finite(r.get("成交额"))}
  results=[]
  for code,prefix,name,count in [("000016","sse50","上证50",50),("000300","hs300","沪深300",300),("000852","csi1000","中证1000",1000),("000688","star50","科创50",50)]:
   f=resolve(ak,"index_stock_cons_csindex")(symbol=code)
   save("recovery-members-"+prefix+".json",{"columns":list(f.columns),"rows":len(f),"sample":json.loads(f.head(2).to_json(orient="records",force_ascii=False,date_format="iso"))})
   if "日期" not in f or set(pd.to_datetime(f["日期"]).dt.strftime("%Y-%m-%d"))!={target}:raise ValueError("Exact-date membership unavailable for "+code)
   members=set(f["成分券代码"].astype(str).str.zfill(6))
   if len(members)!=count or members-amounts.keys():raise ValueError("Missing constituent amounts "+code)
   buy=sum(values.get(c,0) for c in members)/1e8
   amount=sum(amounts[c] for c in members)/1e8
   if amount<=0:raise ValueError("Invalid denominator")
   for suffix,label,val,unit in [("financing-buy","融资买入额",buy,"亿元"),("turnover-amount","成交额",amount,"亿元"),("financing-activity","融资买入额占比",buy/amount*100,"%")]:
    out["series"].append({"id":prefix+"-"+suffix,"name":name+label,"unit":unit,"source":"AKShare沪深交易所融资明细（核对全市场总额）＋中证指数当日成分；iFind当日个股成交额","points":[{"date":target,"value":val}]})
   results.append({"code":code,"buy":buy,"amount":amount})
  save("public-index-inputs.json",out);return results
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
 attempt("breadth-baostock-universe",bao)
if __name__=="__main__":main()
