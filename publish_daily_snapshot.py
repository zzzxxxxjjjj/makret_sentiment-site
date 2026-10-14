"""Publish verified daily files to GitHub main without touching unrelated worktree changes."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPOSITORY = "zzzxxxxjjjj/makret_sentiment-site"
FILES = (
    "broad-market-excel-source.xlsx",
    "wind-market-supplement.json",
    "wind-synthesis-inputs.json",
    "broad-sentiment-page-cache.json",
)


def git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


def validate_snapshot(root: Path) -> str:
    report = json.loads((root / "daily-update-status.json").read_text(encoding="utf-8"))
    if not report.get("ok") or not report.get("targetDate"):
        raise ValueError("Daily refresh has not completed successfully")
    target = report["targetDate"]
    page = json.loads((root / "broad-sentiment-page-cache.json").read_text(encoding="utf-8"))["payload"]
    by_id = {item["id"]: item for item in page.get("series", [])}
    for series_id in ("windall-close-excel", "windall-turnover"):
        item = by_id.get(series_id)
        actual = max((p["date"] for p in item.get("points", []) if p.get("value") is not None), default=None) if item else None
        if actual != target:
            raise ValueError(f"{series_id} is dated {actual}, expected {target}")
    for name in FILES:
        if not (root / name).is_file():
            raise FileNotFoundError(root / name)
    return target


class GitHub:
    def __init__(self, token: str):
        if not token:
            raise ValueError("GITHUB_TOKEN is required; configure it on the scheduled Windows host")
        self.token = token

    def request(self, method: str, path: str, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            "https://api.github.com/repos/" + REPOSITORY + path,
            data=data,
            method=method,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json",
                     "User-Agent": "market-sentiment-daily-publisher"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    def publish(self, root: Path, target: str):
        contents = {name: (root / name).read_bytes() for name in FILES}
        blobs = {}
        for attempt in range(3):
            ref = self.request("GET", "/git/ref/heads/main")
            parent = ref["object"]["sha"]
            commit = self.request("GET", "/git/commits/" + parent)
            base_tree = commit["tree"]["sha"]
            tree = self.request("GET", "/git/trees/" + base_tree)
            old = {item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"}
            changed = [name for name, content in contents.items() if old.get(name) != git_blob_sha(content)]
            if not changed:
                return {"changed": [], "commit": parent}
            entries = []
            for name in changed:
                if name not in blobs:
                    blob = self.request("POST", "/git/blobs", {
                        "content": base64.b64encode(contents[name]).decode("ascii"), "encoding": "base64"})
                    blobs[name] = blob["sha"]
                entries.append({"path": name, "mode": "100644", "type": "blob", "sha": blobs[name]})
            new_tree = self.request("POST", "/git/trees", {"base_tree": base_tree, "tree": entries})
            new_commit = self.request("POST", "/git/commits", {
                "message": f"Publish verified Wind and RQData snapshot {target}",
                "tree": new_tree["sha"], "parents": [parent]})
            try:
                self.request("PATCH", "/git/refs/heads/main", {"sha": new_commit["sha"], "force": False})
                return {"changed": changed, "commit": new_commit["sha"]}
            except urllib.error.HTTPError as exc:
                if exc.code not in (409, 422) or attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        raise RuntimeError("GitHub main moved during publication")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-auth", action="store_true")
    args = parser.parse_args()
    github = GitHub(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")
    if args.check_auth:
        github.request("GET", "/git/ref/heads/main")
        print("GitHub authentication is ready")
        return
    target = validate_snapshot(ROOT)
    result = github.publish(ROOT, target)
    print(json.dumps({"targetDate": target, **result}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Publication failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
