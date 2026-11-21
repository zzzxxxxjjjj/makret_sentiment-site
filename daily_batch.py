"""One post-close batch, persistent stage checkpoints, at most one retry."""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".daily-cache"
def read(path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
    temporary.replace(path)
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
def run_stage(name, command, target, outputs=()):
    marker = STATE / target / (name + ".json")
    previous = read(marker)
    hashes = {p: digest(ROOT / p) for p in outputs}
    if name == "build":
        hashes["inputs"] = hashlib.sha256("".join(str(digest(p)) for p in sorted(ROOT.glob("*.json")) if p.name != "daily-update-status.json").encode()).hexdigest()
    if previous.get("ok") and previous.get("outputs") == hashes and all(hashes.values()):
        print("Already complete: " + name, flush=True)
        return True
    attempts = previous.get("attempts", 0)
    while attempts < 2:
        attempts += 1
        print(f"{name}: attempt {attempts}/2", flush=True)
        try:
            result = subprocess.run([sys.executable, *command], cwd=ROOT, timeout=1800)
            ok = result.returncode == 0 and all((ROOT / p).is_file() for p in outputs)
        except subprocess.TimeoutExpired:
            ok = False
        write(marker, dict(ok=ok, attempts=attempts,
                          outputs={**{p: digest(ROOT / p) for p in outputs}, **({"inputs": hashes["inputs"]} if name == "build" else {})}))
        if ok: return True
    return False
def trading_day(now):
    import akshare as ak
    path = STATE / "calendar.json"
    calendar = read(path)
    year = str(now.year)
    if calendar.get("year") != year:
        dates = sorted(str(d)[:10] for d in ak.tool_trade_date_hist_sina()["trade_date"])
        if not any(d.startswith(year) for d in dates):
            raise ValueError("Trading calendar does not cover current year")
        calendar = dict(year=year, dates=dates)
        write(path, calendar)
    return now.date().isoformat() in calendar["dates"]
def main():
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    target = now.date().isoformat()
    if now.hour < 18 or not trading_day(now):
        print("Skip: outside post-close trading session")
        return
    os.environ["DAILY_TARGET_DATE"] = target
    os.environ["RQDATA_AS_OF"] = target
    os.environ["DEFER_DASHBOARD_BUILD"] = "1"
    tasks = [
        ("public", ["akshare_public_refresh.py"], ["akshare-public-inputs.json"]),
        ("medium", ["akshare_medium_inputs.py", "--as-of", target], ["akshare-medium-inputs.json"]),
        ("margin", ["akshare_margin_risk.py"], ["akshare-margin-risk.json"]),
        ("etf", ["etf_market_refresh.py"], ["etf-market.json"]),
        ("etf-shares", ["etf_net_subscription_refresh.py"], ["etf-net-subscription.json"]),
        ("etf-weekly", ["etf_weekly_relative_flow.py"], ["etf-weekly-relative-flow.json"]),
        ("industry-flow", ["sw_flow_refresh.py"], ["sw-industry-flow.json"]),
        ("industry-rotation", ["sw_rotation_refresh.py"], ["akshare-sw-industry-rotation.json"]),
        ("ifind-turnover", ["ifind_index_turnover_refresh.py"], ["ifind-index-turnover.json"]),
    ]
    if os.environ.get("RQDATAC_CONF"):
        tasks += [
            ("core", ["cloud_daily_update.py"], ["rqdata-breadth-sentiment.json"]),
            ("valuation", ["sw_valuation_rotation.py"], ["sw-industry-valuation.json", "sw-industry-rotation.json"]),
            ("position", ["position_refresh.py"], ["position-advice.json"]),
        ]
    if os.environ.get("AIDO_API_KEY"):
        tasks += [
            ("fund", ["rqdata_fund_exposure_refresh.py", "--output", "rqdata-fund-exposure.json", "--timeout", "20"], ["rqdata-fund-exposure.json"]),
            ("crowding", ["aido_style_crowding_refresh.py"], ["style-crowding.json"]),
        ]
    failures = [name for name, command, outputs in tasks if not run_stage(name, command, target, outputs)]
    from data_freshness import write_report
    write_report(target, errors=[{"source": name, "error": "daily stage failed"} for name in failures])
    # Build once after all collectors, including partial results with actual source dates.
    if not run_stage("build", ["build_static_site.py"], target, ["dist/index.html"]):
        failures.append("build")
    write(ROOT / "daily-update-status.json", dict(targetDate=target, ok=not failures, failedStages=failures))
    if failures: raise SystemExit("Failed stages: " + ", ".join(failures))
if __name__ == "__main__": main()
