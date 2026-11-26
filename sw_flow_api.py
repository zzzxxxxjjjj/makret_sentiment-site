"""Compatibility adapter for AKShare's renamed individual fund-flow function."""
import inspect
from public_recovery import resolve
def history(ak,code,market):
 try:fn=getattr(ak,"stock_fund_flow_individual_hist_em")
 except AttributeError:fn=resolve(ak,"stock_individual_fund_flow")
 parameter="stock" if "stock" in inspect.signature(fn).parameters else "symbol"
 return fn(**{parameter:code,"market":market})
