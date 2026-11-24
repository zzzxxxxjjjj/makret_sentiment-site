"""Read-only checks for provider fallback fields; no production writes."""
import json
from ifind_client import Client
client=Client()
cases=[
 ("flow_wencai","smart_stock_picking",dict(searchstring="2026年11月23日浦发银行主力资金净流入金额",searchtype="stock")),
 ("etf_share_basic","basic_data_service",dict(codes="510300.SH",indipara=[{"indicator":"ths_share_fund","indiparams":["20261123"]}])),
 ("etf_quotes","cmd_history_quotation",dict(codes="510300.SH,159919.SZ",indicators="close,amount,changeRatio",startdate="2026-11-18",enddate="2026-11-23",functionpara={"Fill":"Omit"})),
 ("etf_shares","cmd_history_quotation",dict(codes="510300.SH,159919.SZ",indicators="totalShares",startdate="2026-11-18",enddate="2026-11-23",functionpara={"Fill":"Omit"})),
 ("sw_flow_history","cmd_history_quotation",dict(codes="801010.SL",indicators="mainNetInflow",startdate="2026-11-23",enddate="2026-11-23",functionpara={"Fill":"Omit"})),
 ("stock_flow_history","cmd_history_quotation",dict(codes="600000.SH",indicators="mainNetInflow",startdate="2026-11-23",enddate="2026-11-23",functionpara={"Fill":"Omit"})),
]
for name,path,body in cases:
    try:
        result=client.post(path,body)
        print("FALLBACK="+json.dumps(dict(case=name,ok=True,tables=result.get("tables"),datatype=result.get("datatype")),ensure_ascii=False),flush=True)
    except Exception as exc:
        print("FALLBACK="+json.dumps(dict(case=name,ok=False,error=str(exc)),ensure_ascii=False),flush=True)
