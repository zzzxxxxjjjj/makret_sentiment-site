import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import daily_batch as batch

class DailyBatchTests(unittest.TestCase):
    def test_success_is_skipped_and_failure_retried_only_once(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            with patch.object(batch, "ROOT", root), patch.object(batch, "STATE", root / ".daily-cache"):
                def success(*args, **kwargs):
                    (root / "result.json").write_text("{}")
                    return type("Result", (), {"returncode": 0})()
                with patch.object(batch.subprocess, "run", side_effect=success) as run:
                    self.assertTrue(batch.run_stage("ok", ["source.py"], "2026-11-20", ["result.json"]))
                    self.assertTrue(batch.run_stage("ok", ["source.py"], "2026-11-20", ["result.json"]))
                    self.assertEqual(run.call_count, 1)
                with patch.object(batch.subprocess, "run", return_value=type("Result", (), {"returncode": 1})()) as run:
                    self.assertFalse(batch.run_stage("bad", ["source.py"], "2026-11-20", ["missing.json"]))
                    self.assertFalse(batch.run_stage("bad", ["source.py"], "2026-11-20", ["missing.json"]))
                    self.assertEqual(run.call_count, 2)
    def test_cached_holiday_skips_provider_call(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            with patch.object(batch, "STATE", Path(directory)):
                batch.write(Path(directory) / "calendar.json", {"year": "2026", "dates": ["2026-11-20"]})
                import sys
                with patch.dict(sys.modules, {"akshare": type("Ak", (), {})()}):
                    from datetime import datetime
                    self.assertFalse(batch.trading_day(datetime(2026, 11, 21)))

if __name__ == "__main__":
    unittest.main()
