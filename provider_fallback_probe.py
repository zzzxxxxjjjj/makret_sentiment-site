"""Read-only checks for provider fallback fields; no production writes."""
import json
from ifind_client import Client
client=Client()
cases=[
 ("dated_sw_membership","smart_stock_picking",dict(searchstring="2026年11月23日A股申万一级行业",searchtype="stock")),
 ("all_a_snapshot","smart_stock_picking",dict(searchstring="2026年11月23日A股成交额、换手率、主力资金流向",searchtype="stock")),
 ("missing_etf","smart_stock_picking",dict(searchstring="2026年11月23日159528的收盘价、成交额、基金份额",searchtype="fund")),
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
        print("FALLBACK="+json.dumps(dict(case=name,ok=True,tables=[dict(columns={k:{"count":len(v) if isinstance(v,list) else None,"sample":v[:2] if isinstance(v,list) else v} for k,v in (t.get("table") or {}).items()}) for t in result.get("tables") or []],datatype=result.get("datatype")),ensure_ascii=False),flush=True)
    except Exception as exc:
        print("FALLBACK="+json.dumps(dict(case=name,ok=False,error=str(exc)),ensure_ascii=False),flush=True)
