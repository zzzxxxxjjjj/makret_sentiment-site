"""Collect the user-selected iFind bond-biased hybrid fund proxy separately."""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from ifind_client import Client

CODE = "701014.TI"
OUTPUT = Path(__file__).resolve().parent / "ifind-medium-bond.json"

def main():
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    end = now.date() - timedelta(days=int(now.hour < 18))
    result = Client().post("cmd_history_quotation", {
        "codes": CODE, "indicators": "close", "startdate": "2015-01-01",
        "enddate": str(end), "functionpara": {"Fill": "Omit"},
    })
    values = {}
    for table in result.get("tables") or []:
        if table.get("thscode") != CODE:
            continue
        for day, value in zip(table.get("time") or [], (table.get("table") or {}).get("close") or []):
            if isinstance(value, (float, int)) and math.isfinite(value) and value > 0:
                values[day[:10]] = float(value)
    if len(values) < 1000:
        raise ValueError("Insufficient verified iFind history; previous snapshot retained")
    if (end - datetime.fromisoformat(max(values)).date()).days > 10:
        raise ValueError("iFind history is stale; previous snapshot retained")
    payload = {"code": CODE, "name": "偏债混合型基金指数（用户指定代理）",
               "source": "iFind", "asOf": max(values),
               "points": [{"date": day, "value": values[day]} for day in sorted(values)]}
    if OUTPUT.exists():
        previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if previous.get("code") != CODE or previous.get("asOf", "") > payload["asOf"]:
            raise ValueError("Refusing source change or date rollback")
        merged = {p["date"]: p for p in previous["points"]}
        merged.update({p["date"]: p for p in payload["points"]})
        payload["points"] = [merged[d] for d in sorted(merged)]
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(OUTPUT)
    print(json.dumps({"code": CODE, "asOf": payload["asOf"], "count": len(payload["points"])}))
if __name__ == "__main__":
    main()
