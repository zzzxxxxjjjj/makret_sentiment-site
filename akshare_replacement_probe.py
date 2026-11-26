"""Public AkShare replacement capability checks; no authenticated providers."""
import json
from public_recovery import save,resolve
def main():
 import akshare as ak
 from akshare_request_policy import install
 install()
 result={"checks":[]}
 for category in ("基础一级","基础二级"):
  try:
   f=resolve(ak,"index_realtime_fund_sw")(symbol=category)
   result["checks"].append({"id":"fund-catalog-"+category,"ok":True,"rows":f.to_dict("records")})
  except Exception as e:result["checks"].append({"id":"fund-catalog-"+category,"ok":False,"error":type(e).__name__+": "+str(e)[:300]})
  save("akshare-replacement-probe.json",result)
 print(result,flush=True)
if __name__=="__main__":main()
