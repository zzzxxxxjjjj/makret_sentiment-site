"""Weekly cumulative estimated subscriptions / 2024-09-20 assets."""
import json, math
from pathlib import Path
from datetime import date, timedelta
ROOT = Path(__file__).resolve().parent
BASE = "2024-09-20"
TARGET = "510300 510310 510330 159919 510050 510100 510180 510230 515800 159901 159915 159952 159977 588000 588080 588050 510500 512500 159922 512100 159845 560010 159629".split()
def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
def compute(history, sessions, names=None):
    rows = {e["date"]: e for e in history.get("entries", [])}
    sessions = sorted(set(d for d in sessions if d >= BASE))
    result = []
    for code in TARGET:
        base = rows.get(BASE, {})
        shares = base.get("shares", {}).get(code)
        close = base.get("close", {}).get(code)
        item = dict(code=code, name=(names or {}).get(code, code), points=[], available=False)
        if not number(shares) or not number(close) or shares <= 0 or close <= 0:
            item["reason"] = "缺少2024-09-20基准份额或收盘价"
            result.append(item); continue
        if not sessions or sessions[0] != BASE:
            item["reason"] = "交易日历未覆盖基准日"
            result.append(item); continue
        scale = shares * close
        cumulative = 0.
        daily = {BASE: (0., 0.)}
        previous = shares
        for day in sessions[1:]:
            row = rows.get(day, {})
            units, price = row.get("shares", {}).get(code), row.get("close", {}).get(code)
            if not number(units) or not number(price) or units <= 0 or price <= 0:
                item["reason"] = "日频数据缺口：" + day
                break
            cumulative += (units - previous) * price
            daily[day] = (cumulative / scale * 100, cumulative / 1e8)
            previous = units
        # A Friday holiday uses the last actual session in that completed week.
        weeks = {}
        for day in sessions:
            stamp = date.fromisoformat(day)
            week = stamp - timedelta(days=stamp.weekday())
            weeks[week.isoformat()] = day
        last = sessions[-1] if sessions else BASE
        for day in weeks.values():
            friday = date.fromisoformat(day) + timedelta(days=4-date.fromisoformat(day).weekday())
            if day in daily and friday.isoformat() <= last:
                value, amount = daily[day]
                item["points"].append(dict(date=day, value=round(value, 6), amount=round(amount, 6)))
        item.update(available=bool(item["points"]), baseScale=scale/1e8, baseShares=shares,
                    baseClose=close, asOf=max(daily))
        result.append(item)
    return dict(baseDate=BASE, unit="%", series=result,
                formula="累计Σ[(当日份额－前一交易日份额)×当日收盘价] ÷ (基准日份额×基准日收盘价) ×100%",
                note="基准日为0%；只显示完整周。缺失日后停止累计；份额拆分或合并需先校正。ETF整体净申赎估算，不代表汇金自身买卖。")
def main():
    history_path = ROOT/"etf-shares-history.json"
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {}
    calendar_path = ROOT/".daily-cache/calendar.json"
    calendar = json.loads(calendar_path.read_text(encoding="utf-8")).get("dates", []) if calendar_path.exists() else []
    if not calendar or min(calendar) > BASE:
        import akshare as ak
        calendar = [str(d)[:10] for d in (getattr(ak,'calendar_trade_date_hist_sina',None) or ak.tool_trade_date_hist_sina)()["trade_date"]]
    end = max((e["date"] for e in history.get("entries", [])), default=BASE)
    market_path = ROOT/"etf-market.json"
    market = json.loads(market_path.read_text(encoding="utf-8")) if market_path.exists() else {}
    names = {row["code"]: row.get("name", row["code"]) for row in market.get("rows", [])}
    result = compute(history, [d for d in calendar if d <= end], names)
    path=ROOT/"etf-weekly-relative-flow.json"
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    temp.replace(path)
if __name__=="__main__": main()
