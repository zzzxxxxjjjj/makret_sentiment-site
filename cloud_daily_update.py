"""Compatibility entry point; historical validation does not query any provider."""
import json
from pathlib import Path
from daily_batch import main

BASE_DIR = Path(__file__).resolve().parent
CORE_FILES = ("rqdata-broad-sentiment.json", "rqdata-breadth-sentiment.json", "rqdata-industry-sentiment.json")

def read_cache(filename):
    try:
        value = json.loads((BASE_DIR / filename).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def verify_core_dates(trade_date):
    for filename in CORE_FILES:
        actual = read_cache(filename).get("asOf", "missing")
        if actual != trade_date:
            raise ValueError(f"{filename} trading date mismatch: expected {trade_date}, actual {actual}")

if __name__ == "__main__":
    main()
