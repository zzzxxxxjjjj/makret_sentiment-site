"""Build a Cloudflare Pages snapshot using only saved local JSON and web assets.

No server, Excel, RQData SDK, account credentials, or network access is needed.
Run with Python 3.10+: python build_static_site.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from market_data_sync import apply_market_data_sync
from publication_filters import without_northbound


BASE_DIR = Path(__file__).resolve().parent
WEB_FILES = (
    "style-crowding.js", "style-crowding.css",
    "index.html", "app.js", "styles.css", "cycle.css", "theme.js",
    "industry-sentiment.html", "industry-sentiment.js",
    "industry-flow-trend.js", "industry-sentiment.css", "industry-rotation-history.js", "data-health.js",
    "etf-flows.html", "etf-flows.js", "etf-flows.css",
    "financing-activity.html", "financing-activity.js", "financing-activity.css",
    "macro-tracking.html", "macro-tracking.js", "macro-tracking.css",
    "position-advice.html", "position-advice.js", "position-advice.css",
)
REQUIRED_DATA = ("rqdata-broad-sentiment.json", "rqdata-industry-sentiment.json")
OPTIONAL_DATA = {
    "style-crowding.json": {"available": False, "asOf": None, "factors": []},
    "position-advice.json": {
        "available": False, "asOf": None,
        "note": "当前发布版本尚未包含已核验的择时观点数据。",
    },
    "akshare-margin-risk.json": {"asOf": None, "series": [], "source": "AKShare / 东方财富"},
    "rqdata-industry-rotation.json": {"points": []},
    "data-freshness.json": {"entries": [], "targetDate": None},
    "rqdata-fund-exposure.json": {
        "available": False, "asOf": None, "industries": [],
        "note": "当前发布版本尚未包含公募基金行业超配数据。",
    },
    "macro-tracking.json": {
        "available": False, "asOf": None, "series": [],
        "note": "当前发布版本尚未包含宏观跟踪数据。",
    },
}
GENERATED_FILES = ("broad-sentiment.json", "deployment-info.json", "_headers", "404.html")


def public_data(value):
    """Keep indicator values while removing local paths and private metadata."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = key.lower().replace("_", "")
            if normalized in {"sourcesignature", "password", "token", "accesstoken",
                              "refreshtoken", "apikey", "username", "credential", "credentials"}:
                continue
            if normalized in {"path", "filepath", "localpath"}:
                continue
            result[key] = public_data(item)
        return result
    if isinstance(value, list):
        return [public_data(item) for item in value]
    if isinstance(value, str) and (re.search(r"[A-Za-z]:[\\/]", value)
                                   or "/home/" in value or "/Users/" in value):
        return "本地数据文件（路径已省略）"
    return value


def read_json(name):
    value = json.loads((BASE_DIR / name).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{name}: expected a JSON object")
    return value


def validate_dashboard(payload):
    if not isinstance(payload, dict):
        raise ValueError("Page cache has no dashboard payload")
    for key in ("cards", "series"):
        if not isinstance(payload.get(key), list) or not payload[key]:
            raise ValueError(f"Dashboard {key} is missing or empty")
    if not payload.get("asOf") or not isinstance(payload.get("summary"), dict):
        raise ValueError("Dashboard date or summary is missing")
    if not isinstance(payload.get("availableCount"), int):
        raise ValueError("Dashboard coverage is missing")


def build():
    # Use the complete saved page payload, not the raw RQData cache's different schema.
    payload = read_json("broad-sentiment-page-cache.json").get("payload")
    validate_dashboard(payload)
    # Permit a focused publication without replacing unrelated source snapshots.
    institutional_path = BASE_DIR / "institutional-buy-snapshot.json"
    if institutional_path.is_file():
        institutional = read_json(institutional_path.name)
        for incoming in institutional.get("series", []):
            if incoming.get("id") not in {"institutional-buy", "institutional-buy-ma5"}:
                raise ValueError("Unexpected series in institutional buying snapshot")
            points = incoming.get("points", [])
            if not points:
                raise ValueError("Institutional buying snapshot has no points")
            current = next((s for s in payload["series"] if s.get("id") == incoming["id"]), {})
            current_date = max((p["date"] for p in current.get("points", [])), default="")
            if max(p["date"] for p in points) >= current_date:
                payload["series"] = [s for s in payload["series"] if s.get("id") != incoming["id"]]
                payload["series"].append(incoming)
    exported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = apply_market_data_sync(public_data(payload), BASE_DIR)
    payload["publication"] = {"mode": "snapshot", "exportedAt": exported_at}
    output = {"broad-sentiment.json": json.dumps(payload, ensure_ascii=False, allow_nan=False)}
    missing = []
    dates = {"broad-sentiment.json": payload["asOf"]}
    institutional_series = next((s for s in payload["series"] if s.get("id") == "institutional-buy"), {})
    if institutional_series.get("points"):
        dates["institutional-buy"] = max(p["date"] for p in institutional_series["points"])

    for name in REQUIRED_DATA:
        data = read_json(name)
        if name == "rqdata-industry-sentiment.json" and not data.get("industries"):
            raise ValueError("Industry snapshot has no industries")
        output[name] = json.dumps(public_data(data), ensure_ascii=False, allow_nan=False)
        dates[name] = data.get("asOf")
    for name, fallback in OPTIONAL_DATA.items():
        if (BASE_DIR / name).is_file():
            data = read_json(name)
            output[name] = json.dumps(public_data(data), ensure_ascii=False, allow_nan=False)
            dates[name] = data.get("asOf")
        else:
            missing.append(name)
            if fallback is not None:
                output[name] = json.dumps(fallback, ensure_ascii=False, allow_nan=False)

    for name in WEB_FILES:
        content = (BASE_DIR / name).read_text(encoding="utf-8-sig")
        if name in {"app.js", "etf-flows.js", "financing-activity.js"}:
            content = content.replace("/api/broad-sentiment", "/broad-sentiment.json")
        if name == "macro-tracking.js":
            content = content.replace(
                "const payload=await response.json();",
                "const payload=await response.json();if(payload.available===false)throw new Error(payload.note||'暂无宏观快照');",
            )
        if name == "industry-sentiment.html":
            content = content.replace(
                "暂无公募偏股基金超配数据，请运行 rqdata_fund_exposure_refresh.py 生成 rqdata-fund-exposure.json。",
                "当前发布版本尚未包含公募偏股基金行业超配数据。",
            )
        if name.endswith(".html"):
            if "data-health.js" not in content:
                content=content.replace("</body>", '<script src="/data-health.js?v=20261016-1" defer></script></body>')
            content = content.replace('type="button">刷新数据</button>', 'type="button">重新读取</button>')
        if name == "app.js":
            content = content.replace(
                "data.missingCount?`已更新 · ${data.missingCount}项待接入`:'数据已更新'",
                "data.missingCount?`已发布快照 · ${data.missingCount}项待接入`:'已发布快照'",
            )
        output[name] = content

    output["_headers"] = "/*\n  Cache-Control: no-cache\n/*.json\n  Cache-Control: no-store\n  X-Content-Type-Options: nosniff\n"
    output["404.html"] = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>页面未找到</title><h1>页面未找到</h1><p><a href="/">返回首页</a></p></html>'
    manifest = {
        "mode": "static-snapshot", "exportedAt": exported_at,
        "snapshotGeneratedAt": payload.get("generatedAt"),
        "dataDates": dates, "missingOptionalData": missing,
        "files": sorted([*output, "deployment-info.json"]),
    }
    output["deployment-info.json"] = json.dumps(manifest, ensure_ascii=False, indent=2)
    for name, content in list(output.items()):
        if name.endswith(".json"):
            output[name] = json.dumps(without_northbound(json.loads(content)), ensure_ascii=False, allow_nan=False)
    validate_output(output)

    destination = BASE_DIR / "dist"
    if destination.is_symlink():
        raise ValueError("dist must not be a symbolic link")
    if destination.exists():
        allowed = set(WEB_FILES) | set(REQUIRED_DATA) | set(OPTIONAL_DATA) | set(GENERATED_FILES)
        unexpected = {item.name for item in destination.iterdir() if item.name not in allowed or not item.is_file() or item.is_symlink()}
        if unexpected:
            raise ValueError("dist contains unrelated files; build stopped: " + ", ".join(sorted(unexpected)))
        # Prevent accidentally retaining data removed since a previous build.
        stale = {item.name for item in destination.iterdir()} - set(output)
        if stale:
            raise ValueError("dist contains old optional files; move them aside before rebuilding: " + ", ".join(sorted(stale)))
    destination.mkdir(exist_ok=True)
    for name, content in output.items():
        (destination / name).write_text(content, encoding="utf-8")
    return manifest


def validate_output(output):
    for name, content in output.items():
        if "\ufffd" in content:
            raise ValueError(f"{name} contains damaged Unicode text; publication stopped")
        if len(content.encode("utf-8")) > 25 * 1024 * 1024:
            raise ValueError(f"{name} exceeds the Cloudflare Pages 25 MiB file limit")
        if name.endswith(".js") and "/api/" in content:
            raise ValueError(f"{name} still depends on a backend API")
        if name.endswith(".html"):
            if "data-health.js" not in content:
                content=content.replace("</body>", '<script src="/data-health.js?v=20261016-1" defer></script></body>')
            for link in re.findall(r'(?:src|href)=[\"\']([^\"\']+)', content):
                target = link.split("?", 1)[0].split("#", 1)[0].lstrip("/")
                if not target or ":" in target:
                    continue
                if target not in output:
                    raise ValueError(f"{name} references missing asset {target}")


if __name__ == "__main__":
    try:
        manifest = build()
    except (OSError, ValueError) as exc:
        print(f"Static build failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Static site ready: dist ({len(manifest['files'])} files)")
    print(f"Dashboard data date: {manifest['dataDates']['broad-sentiment.json']}")
    if manifest["missingOptionalData"]:
        print("Missing optional snapshots: " + ", ".join(manifest["missingOptionalData"]))

