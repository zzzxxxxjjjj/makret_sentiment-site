from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from broad_sentiment import build_payload as build_broad_sentiment_payload


BASE_DIR = Path(__file__).resolve().parent
# Legacy environment names remain aliases for existing launchers.
HOST = os.environ.get("SITE_HOST", os.environ.get("IFIND_SITE_HOST", "0.0.0.0"))
PORT = int(os.environ.get("SITE_PORT", os.environ.get("IFIND_SITE_PORT", "8876")))
AUTO_DAILY_UPDATE = os.environ.get(
    "RQDATA_AUTO_DAILY_UPDATE", os.environ.get("IFIND_AUTO_DAILY_UPDATE", "1")
) == "1"
DAILY_UPDATE_HOUR = int(os.environ.get(
    "RQDATA_DAILY_UPDATE_HOUR", os.environ.get("IFIND_DAILY_UPDATE_HOUR", "16")
))
DAILY_UPDATE_MINUTE = int(os.environ.get(
    "RQDATA_DAILY_UPDATE_MINUTE", os.environ.get("IFIND_DAILY_UPDATE_MINUTE", "10")
))
RQDATA_PYTHON = Path(os.environ.get(
    "RQDATA_PYTHON", r"C:\Users\DELL\anaconda3\envs\rqsdk\python.exe"
))
DAILY_UPDATE_SCRIPTS = (
    ("宽基情绪", "rqdata_refresh.py", ("--output", "rqdata-broad-sentiment.json")),
    ("市场广度", "rqdata_breadth_refresh.py", ("--output", "rqdata-breadth-sentiment.json", "--start", "2018-01-01")),
    ("行业情绪", "rqdata_industry_refresh.py", ("--output", "rqdata-industry-sentiment.json")),
    ("基金仓位", "rqdata_fund_position_refresh.py", ("--output", "rqdata-fund-stock-position-history.json", "--start", "2021-07-01")),
    ("公募基金超配", "rqdata_fund_exposure_refresh.py", ("--output", "rqdata-fund-exposure.json")),
    ("宏观跟踪", "macro_tracking_refresh.py", ("--output", "macro-tracking.json", "--refresh-excel")),
)


def build_market_payload():
    """Legacy route alias for the current dashboard, with no iFind fallback.

    /api/market now returns the same card/series schema as /api/broad-sentiment.
    The current frontend uses /api/broad-sentiment directly.
    """
    return build_broad_sentiment_payload()


def build_debug_payload():
    """Inspect local data availability without contacting data providers."""
    sources = []
    for filename in (
        "rqdata-broad-sentiment.json",
        "rqdata-breadth-sentiment.json",
        "rqdata-industry-sentiment.json",
        "rqdata-fund-stock-position-history.json",
        "rqdata-fund-exposure.json",
        "macro-tracking.json",
    ):
        item = {"file": filename, "available": False, "asOf": None}
        try:
            data = json.loads((BASE_DIR / filename).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("数据文件应为 JSON 对象")
            item.update(available=True, asOf=data.get("asOf"))
        except (OSError, ValueError) as exc:
            item["error"] = f"{type(exc).__name__}: 无法读取本地数据缓存"
        sources.append(item)
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "dataProvider": "RQData",
        "supplementarySource": "Excel（部分指标保留原始来源）",
        "sources": sources,
        "rqdataPythonAvailable": RQDATA_PYTHON.is_file(),
        "automaticDailyUpdate": AUTO_DAILY_UPDATE,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json({"ok": True, "time": datetime.now().isoformat(timespec="seconds")})
            return
        if parsed.path in ("/api/market", "/api/broad-sentiment"):
            try:
                payload = build_market_payload()
            except Exception as exc:
                print(f"宽基情绪数据生成失败：{type(exc).__name__}")
                self.send_json({"error": "RQData/Excel 数据尚未准备好，请检查本地缓存。"}, status=503)
                return
            self.send_json(payload)
            return
        if parsed.path == "/api/debug":
            self.send_json(build_debug_payload())
            return
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path in ("", "/"):
            self.serve_file(BASE_DIR / "index.html")
            return
        target = (BASE_DIR / parsed.path.lstrip("/")).resolve()
        if BASE_DIR not in target.parents and target != BASE_DIR:
            self.send_error(403)
            return
        if target.exists() and target.is_file():
            self.serve_file(target)
            return
        self.send_error(404)

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_file(self, path):
        body = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        elif path.suffix in (".html", ".css"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_daily_data_update():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始每日收盘数据更新")
    for label, script_name, arguments in DAILY_UPDATE_SCRIPTS:
        try:
            completed = subprocess.run(
                [str(RQDATA_PYTHON), str(BASE_DIR / script_name), *arguments],
                cwd=str(BASE_DIR), capture_output=True, text=True,
                timeout=1800, check=False,
            )
            status = "完成" if completed.returncode == 0 else f"失败（代码 {completed.returncode}）"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {label}更新{status}")
            if completed.returncode and completed.stderr:
                print(completed.stderr[-800:])
        except Exception as exc:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {label}更新失败：{exc}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 每日收盘数据更新结束")


def daily_update_scheduler():
    last_run_date = None
    while True:
        now = datetime.now()
        scheduled = now.replace(
            hour=DAILY_UPDATE_HOUR, minute=DAILY_UPDATE_MINUTE,
            second=0, microsecond=0,
        )
        if now.weekday() < 5 and now >= scheduled and last_run_date != now.date():
            last_run_date = now.date()
            run_daily_data_update()
        time.sleep(30)


if __name__ == "__main__":
    print(f"RQData 市场情绪网站已启动：http://{HOST}:{PORT}")
    if AUTO_DAILY_UPDATE:
        print(f"工作日自动更新已启用：{DAILY_UPDATE_HOUR:02d}:{DAILY_UPDATE_MINUTE:02d}")
        threading.Thread(target=daily_update_scheduler, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
