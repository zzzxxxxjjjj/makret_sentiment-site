#!/usr/bin/env python3
"""公募偏股基金行业超配快照（AIDO Research / 东北证券金融工程）。

拉取旗舰指数 885001（偏股混合型基金指数）最新一期的申万一级行业配置，
落地为本地快照 rqdata-fund-exposure.json，供行业情绪页面直接读取。

只依赖标准库，可用任意 Python 3 解释器运行。

用法：
    python rqdata_fund_exposure_refresh.py --output rqdata-fund-exposure.json
    python rqdata_fund_exposure_refresh.py --index 885002 --output xxx.json

API Key 解析顺序：
    1) --api-key 参数
    2) 环境变量 AIDO_API_KEY
    3) 环境变量 CROWDING_API_KEY / PEFIDX_API_KEY
    4) 已安装的 aido-research 技能凭据文件
失败时保留既有快照并以非零码退出，站点继续使用上一次缓存。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_BASE_URL = "http://81.70.32.217"
DEFAULT_INDEX = "885001"
DEFAULT_OUTPUT = "rqdata-fund-exposure.json"

SKILL_KEY_FILES = (
    Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")) / "skills" / "aido-research" / "references" / "customer-api-key.md",
    Path.home() / ".workbuddy" / "skills" / "aido-research" / "references" / "customer-api-key.md",
    Path.home() / ".workbuddy" / "skills" / "aido-research" / "references" / "crowding-api.md",
)

INDUSTRY_COUNT = 31


def resolve_api_key(explicit: str | None) -> str:
    if explicit:
        return explicit.strip()
    for env_name in ("AIDO_API_KEY", "CROWDING_API_KEY", "PEFIDX_API_KEY"):
        value = os.environ.get(env_name)
        if value and value.strip():
            return value.strip()
    for path in SKILL_KEY_FILES:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        match = re.search(r"\bsk_[A-Za-z0-9_\-]{8,}", text)
        if match:
            return match.group(0)
    raise SystemExit(
        "找不到 API Key。请设置环境变量 AIDO_API_KEY，或用 --api-key 传入。"
    )


def fetch_json(base_url: str, path: str, api_key: str, params: dict, timeout: float) -> dict:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "ifind-market-sentiment-site/fund-exposure",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        if exc.code == 403:
            raise SystemExit(f"HTTP 403：该 Key 未开通 pefidx 模块授权。{body}") from exc
        if exc.code == 401:
            raise SystemExit(f"HTTP 401：API Key 缺失/无效/过期。{body}") from exc
        raise SystemExit(f"HTTP {exc.code} 调用 {path} 失败：{body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"网络错误，无法访问 {path}：{exc.reason}") from exc


def number_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 4)


def validate_snapshot(payload):
    """Reject incomplete or mixed-week responses before replacing the last good file."""
    try:
        as_of = date.fromisoformat(payload['asOf'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('Fund exposure response has no valid weekly date') from None
    rows = payload.get('industries', [])
    if len(rows) != INDUSTRY_COUNT or len({r.get('code') for r in rows}) != INDUSTRY_COUNT:
        raise ValueError('Fund exposure response must contain 31 unique industries')
    for row in rows:
        if not row.get('code') or not row.get('name') or row.get('tradeDate') != as_of.isoformat():
            raise ValueError('Fund exposure contains missing industry names or mixed weekly dates')
        if any(number_or_none(row.get(k)) is None for k in ('wgtEq', 'mkt', 'overPp')):
            raise ValueError('Fund exposure contains invalid weights')
        if abs(row['wgtEq'] - row['mkt'] - row['overPp']) > 0.02:
            raise ValueError('Fund overweight does not equal equity weight minus benchmark weight')
    for key in ('wgtEq', 'mkt'):
        if abs(sum(r[key] for r in rows) - 100) > 0.1:
            raise ValueError('Fund exposure weights do not sum to 100 percent')


def build_weekly_comparison(current, previous_raw):
    """Compare actual adjacent provider weeks, allowing holiday gaps."""
    validate_snapshot(current)
    previous = {
        'asOf': previous_raw.get('as_of'),
        'industries': [{
            'code': row.get('code'), 'name': row.get('name'),
            'tradeDate': row.get('trade_date'),
            'wgtEq': number_or_none(row.get('wgt_eq')),
            'mkt': number_or_none(row.get('mkt')),
            'overPp': number_or_none(row.get('over_pp')),
        } for row in previous_raw.get('data', [])],
    }
    validate_snapshot(previous)
    if previous['asOf'] >= current['asOf']:
        raise ValueError('Previous fund week must precede the latest week')
    if previous_raw.get('index', current.get('index')) != current.get('index'):
        raise ValueError('Fund comparison must use the same fund index')
    by_code = {r['code']: r for r in previous['industries']}
    if set(by_code) != {r['code'] for r in current['industries']}:
        raise ValueError('Fund comparison industry coverage changed; refusing partial rankings')
    rows = []
    for row in current['industries']:
        old = by_code[row['code']]
        rows.append({
            'code': row['code'], 'name': row['name'],
            'previousOverPp': old['overPp'], 'currentOverPp': row['overPp'],
            'changeOverPp': round(row['overPp'] - old['overPp'], 4),
            'weightChangePp': round(row['wgtEq'] - old['wgtEq'], 4),
            'benchmarkChangePp': round(row['mkt'] - old['mkt'], 4),
        })
    rows.sort(key=lambda r: (-r['changeOverPp'], r['code']))
    return {'previousAsOf': previous['asOf'], 'asOf': current['asOf'],
            'unit': 'pp', 'industries': rows}


def save_snapshot(payload, output_path):
    validate_snapshot(payload)
    if output_path.exists():
        try:
            previous = json.loads(output_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous = {}
        if previous.get('asOf', '') > payload['asOf']:
            raise ValueError('Fund exposure source returned an older week; existing snapshot retained')
        meaningful = lambda d: {k: v for k, v in d.items() if k != 'updatedAt'}
        if meaningful(previous) == meaningful(payload):
            return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + '.tmp')
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    temp_path.replace(output_path)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公募偏股基金行业超配快照")
    parser.add_argument("--base-url", default=os.environ.get("AIDO_API_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key")
    parser.add_argument("--index", default=DEFAULT_INDEX, help="基金指数代码，默认 885001 偏股混合型")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path(__file__).resolve().parent / output_path

    api_key = resolve_api_key(args.api_key)

    latest = fetch_json(
        args.base_url,
        "v1/pefidx/latest",
        api_key,
        {"category": "industry", "index": args.index},
        args.timeout,
    )

    rows = latest.get("data") or []
    if not isinstance(rows, list) or not rows:
        raise SystemExit("接口未返回行业配置数据，保留既有快照。")

    industries = []
    for row in rows:
        over = number_or_none(row.get("over_pp"))
        wgt_eq = number_or_none(row.get("wgt_eq"))
        mkt = number_or_none(row.get("mkt"))
        if over is None or wgt_eq is None or mkt is None:
            continue
        industries.append({
            "code": row.get("code"),
            "name": row.get("name"),
            "tradeDate": row.get("trade_date"),
            "wgtEq": wgt_eq,
            "mkt": mkt,
            "overPp": over,
            "wgtNav": number_or_none(row.get("wgt_nav")),
            "anchor": number_or_none(row.get("anchor")),
            "lb": number_or_none(row.get("lb")),
            "ub": number_or_none(row.get("ub")),
        })

    if not industries:
        raise SystemExit("接口返回的行业记录缺少 wgt_eq / mkt / over_pp 字段，保留既有快照。")

    industries.sort(key=lambda item: item["overPp"], reverse=True)

    sum_wgt_eq = sum(item["wgtEq"] for item in industries)
    sum_mkt = sum(item["mkt"] for item in industries)
    top3 = round(sum(item["wgtEq"] for item in industries[:3]), 4)

    payload = {
        "asOf": latest.get("as_of"),
        "index": latest.get("index") or args.index,
        "indexName": latest.get("index_name") or "偏股混合型基金指数",
        "category": "industry",
        "taxonomy": "申万一级",
        "unit": "pp",
        "source": "AIDO Research · 东北证券金融工程",
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(industries),
        "expectedCount": INDUSTRY_COUNT,
        "checks": {
            "wgtEqSum": round(sum_wgt_eq, 4),
            "mktSum": round(sum_mkt, 4),
            "top3WgtEq": top3,
            "overCount": sum(1 for item in industries if item["overPp"] > 0),
            "underCount": sum(1 for item in industries if item["overPp"] < 0),
        },
        "industries": industries,
    }

    # The last available observation before the current week, not an assumed
    # seven-day offset: holidays can leave a longer interval between snapshots.
    before = (date.fromisoformat(payload['asOf']) - timedelta(days=1)).isoformat()
    previous_raw = fetch_json(args.base_url, 'v1/pefidx/snapshot', api_key,
                              {'category': 'industry', 'index': args.index, 'date': before}, args.timeout)
    payload['comparison'] = build_weekly_comparison(payload, previous_raw)
    save_snapshot(payload, output_path)

    print(
        f"已写入 {output_path.name}：{payload['indexName']}（{payload['index']}）"
        f" {payload['asOf']}，{len(industries)} 个行业；"
        f"最超配 {industries[0]['name']} {industries[0]['overPp']:+.2f}pp，"
        f"最低配 {industries[-1]['name']} {industries[-1]['overPp']:+.2f}pp"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
