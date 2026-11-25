"""One post-close batch, persistent stage checkpoints, at most one retry."""
import hashlib
import json
import os
import subprocess
import sys
import time
import random
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
    code = hashlib.sha256("".join(str(digest(p)) for p in ([ROOT/command[0],ROOT/"requirements-daily.txt"] if name not in {"build","page-rebuild"} else sorted(ROOT.glob("*.py")))).encode()).hexdigest()
    if command[0] in {"akshare_public_refresh.py","akshare_medium_inputs.py","akshare_margin_risk.py","akshare_options_refresh.py","etf_market_refresh.py","etf_weekly_relative_flow.py","sw_flow_refresh.py","sw_rotation_refresh.py"}:
        code=hashlib.sha256((code+str(digest(ROOT/"akshare_request_policy.py"))).encode()).hexdigest()
    hashes = {p: digest(ROOT / p) for p in outputs}
    if name in {"build", "page-rebuild"}:
        hashes["inputs"] = hashlib.sha256("".join(str(digest(p)) for p in sorted(ROOT.glob("*.json")) if p.name != "daily-update-status.json").encode()).hexdigest()
    if previous.get("code")==code and previous.get("ok") and previous.get("outputs") == hashes and all(hashes.values()):
        print("Already complete: " + name, flush=True)
        return True
    attempts = 0  # Retry failed stages on each scheduled invocation; max two attempts per run.
    while attempts < 2:
        attempts += 1
        print(f"{name}: attempt {attempts}/2", flush=True)
        try:
            result = subprocess.run([sys.executable, *command], cwd=ROOT, timeout=1800)
            ok = result.returncode == 0 and all((ROOT / p).is_file() for p in outputs)
        except subprocess.TimeoutExpired:
            ok = False
        write(marker, dict(ok=ok, attempts=attempts, code=code,
                          outputs={**{p: digest(ROOT / p) for p in outputs}, **({"inputs": hashes["inputs"]} if name in {"build", "page-rebuild"} else {})}))
        if ok: return True
        if attempts<2:
            print("Cooling down before stage retry: "+name,flush=True)
            time.sleep(30+random.uniform(0,5))
    return False
def trading_day(now):
    import akshare as ak
    path = STATE / "calendar.json"
    calendar = read(path)
    year = str(now.year)
    if calendar.get("year") != year:
        dates = sorted(str(d)[:10] for d in (getattr(ak, 'calendar_trade_date_hist_sina', None) or ak.tool_trade_date_hist_sina)()["trade_date"])
        if not any(d.startswith(year) for d in dates):
            raise ValueError("Trading calendar does not cover current year")
        calendar = dict(year=year, dates=dates)
        write(path, calendar)
    return now.date().isoformat() in calendar["dates"]
def main():
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    from completed_session import completed_target
    target=os.environ.get("DAILY_TARGET_DATE")
    if not target:
        trading_day(now)  # Populate the verified exchange calendar cache.
        target=completed_target(now,read(STATE/"calendar.json").get("dates",[]))
    os.environ["DAILY_TARGET_DATE"] = target
    os.environ["RQDATA_AS_OF"] = target
    os.environ["DEFER_DASHBOARD_BUILD"] = "1"
    tasks = [
        ("options", ["akshare_options_refresh.py"], ["akshare-options-pcr.json"]),
        ("cffex-options", ["option_gap_recovery.py"], ["akshare-options-pcr.json", "option-gap-recovery-status.json"]),
        ("ifind-turnover", ["ifind_index_turnover_refresh.py"], ["ifind-index-turnover.json"]),

        ("public", ["akshare_public_refresh.py", "--sources-only"], ["akshare-public-inputs.json"]),
        ("index-financing", ["index_public_recovery.py", "--daily"], ["public-index-inputs.json", "index-recovery-status.json"]),
        ("public-flows", ["public_recovery.py", "--flows-only"], ["flows-recovery-status.json", "akshare-public-inputs.json"]),
        ("medium", ["akshare_medium_inputs.py", "--as-of", target], ["akshare-medium-inputs.json"]),
        ("medium-matching-inputs", ["public_recovery.py", "--medium-only"], ["medium-input-audit.json", "cloud-market-inputs.json"]),
        ("margin", ["akshare_margin_risk.py"], ["akshare-margin-risk.json"]),
        ("etf", ["etf_market_refresh.py"], ["etf-market.json"]),
        ("etf-shares", ["etf_share_public_recovery.py"], ["etf-net-subscription.json", "etf-shares-history.json"]),
        ("etf-weekly", ["etf_weekly_relative_flow.py"], ["etf-weekly-relative-flow.json"]),
        ("industry-flow", ["sw_flow_refresh.py"], ["sw-industry-flow.json"]),
        ("industry-rotation", ["sw_rotation_refresh.py"], ["akshare-sw-industry-rotation.json"]),
        ("ifind-medium-bond", ["ifind_medium_bond_refresh.py"], ["ifind-medium-bond.json"]),
    ]
    if os.environ.get("AIDO_API_KEY"):
        tasks += [
            ("fund", ["rqdata_fund_exposure_refresh.py", "--output", "rqdata-fund-exposure.json", "--timeout", "20"], ["rqdata-fund-exposure.json"]),
            ("crowding", ["aido_style_crowding_refresh.py"], ["style-crowding.json"]),
        ]
    failures = [name for name, command, outputs in tasks if not run_stage(name, command, target, outputs)]
    write(ROOT / "daily-update-status.json", dict(targetDate=target, ok=not failures, failedStages=failures))
    if not run_stage("page-rebuild", ["rebuild_saved_page.py", "--target", target], target, ["broad-sentiment-page-cache.json", "data-freshness.json"]):
        failures.append("page-rebuild")
    # Build once after all collectors, including partial results with actual source dates.
    if not run_stage("build", ["build_static_site.py"], target, ["dist/index.html"]):
        failures.append("build")
    write(ROOT / "daily-update-status.json", dict(targetDate=target, ok=not failures, failedStages=failures))
    if failures: raise SystemExit("Failed stages: " + ", ".join(failures))
if __name__ == "__main__": main()
