"""Small public probes before any large option-history batch."""
import requests,json,re,io
from xml.etree import ElementTree as ET
from public_recovery import read,save
def main():
 from akshare_request_policy import install
 install()
 day=read("gap-source-probe.json")["targetDate"];tag=day.replace("-","")
 results=[]
 def attempt(key,fn):
  try:r={"id":key,"ok":True,"detail":fn()}
  except Exception as e:r={"id":key,"ok":False,"error":type(e).__name__+": "+str(e)[:220]}
  results.append(r);save("remaining-public-probe.json",{"targetDate":day,"results":results});print(r,flush=True)
 def kline():
  rows=read("data_sources/public-gap-sse-option-risk.json")["rows"]
  row=next(r for r in rows if str(r["合约交易代码"]).startswith("510050"))
  code=str(row["合约编码"]).split(".")[0]
  url="https://push2his.eastmoney.com/api/qt/stock/kline/get"
  data=requests.get(url,params={"secid":"10."+code,"klt":"101","fqt":"0","beg":"20261119","end":tag,"fields1":"f1,f2,f3,f4,f5,f6","fields2":"f51,f52,f53,f54,f55,f56,f57"},timeout=25).json()
  values=(data.get("data") or {}).get("klines") or []
  if not values:raise ValueError("No dated contract klines")
  save("data_sources/public-option-kline-sample.json",{"code":code,"day":day,"klines":values})
  return {"code":code,"rows":len(values),"sample":values[:1]}
 attempt("sse-contract-daily",kline)
 def cffex():
  url="http://www.cffex.com.cn/sj/hqsj/rtj/"+tag[:6]+"/"+tag[6:]+"/"+tag+"_1.csv"
  r=requests.get(url,timeout=20);r.raise_for_status()
  raw=r.content.decode("gb18030")
  if "MO" not in raw:raise ValueError("No MO contracts in dated file")
  from pathlib import Path
  Path("data_sources/public-cffex-"+tag+"-all.csv").write_text(raw,encoding="utf-8")
  return {"hasMO":True,"bytes":len(r.content)}
 attempt("cffex-http-daily",cffex)
 def pcf():
  url="https://reportdocs.static.szse.cn/files/text/ETFDown/pcf_159919_"+tag+".xml"
  r=requests.get(url,timeout=25);r.raise_for_status()
  root=ET.fromstring(r.content)
  tags=[n.tag.rsplit("}",1)[-1] for n in root if n.tag.rsplit("}",1)[-1]!="Components"]
  return {"rootTags":tags}
 attempt("szse-pcf-metadata",pcf)
if __name__=="__main__":main()
