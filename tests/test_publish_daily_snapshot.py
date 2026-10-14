import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publish_daily_snapshot import FILES, GitHub, git_blob_sha, validate_snapshot


class PublishDailySnapshotTests(unittest.TestCase):
    def test_rejects_stale_wind_data_even_when_refresh_report_succeeded(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            (root / "daily-update-status.json").write_text(
                json.dumps({"ok": True, "targetDate": "2026-10-14"}), encoding="utf-8")
            (root / "broad-sentiment-page-cache.json").write_text(json.dumps({"payload": {
                "series": [
                    {"id": "windall-close-excel", "points": [{"date": "2026-10-14", "value": 1}]},
                    {"id": "windall-turnover", "points": [{"date": "2026-10-13", "value": 1}]},
                ]}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "windall-turnover"):
                validate_snapshot(root)

    def test_publishes_allowlisted_files_on_latest_main(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            for name in FILES:
                (root / name).write_bytes(name.encode())
            github = GitHub("test-token")
            calls = []

            def request(method, path, payload=None):
                calls.append((method, path, payload))
                if path == "/git/ref/heads/main":
                    return {"object": {"sha": "parent"}}
                if path == "/git/commits/parent":
                    return {"tree": {"sha": "base"}}
                if path == "/git/trees/base" and method == "GET":
                    return {"tree": [{"path": FILES[0], "type": "blob", "sha": git_blob_sha(FILES[0].encode())}]}
                if path == "/git/blobs":
                    return {"sha": "newblob"}
                if path == "/git/trees":
                    return {"sha": "newtree"}
                if path == "/git/commits":
                    return {"sha": "newcommit"}
                if path == "/git/refs/heads/main":
                    return {}
                raise AssertionError((method, path))

            with patch.object(github, "request", side_effect=request):
                result = github.publish(root, "2026-10-14")
            self.assertEqual(result["commit"], "newcommit")
            self.assertNotIn(FILES[0], result["changed"])
            self.assertEqual(len(result["changed"]), len(FILES) - 1)
            self.assertEqual(calls[-1][0:2], ("PATCH", "/git/refs/heads/main"))
            self.assertFalse(calls[-1][2]["force"])


if __name__ == "__main__":
    unittest.main()
