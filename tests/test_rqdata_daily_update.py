import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rqdata_daily_update as updater


class CoreBatchTests(unittest.TestCase):
    def seed(self, directory):
        for _, filename, _ in updater.CORE_UPDATES:
            (directory / filename).write_text(json.dumps({
                "asOf": "2026-10-08", "points": [1], "industries": [1],
            }), encoding="utf-8")

    def fake_run(self, args, **kwargs):
        self.assertEqual(kwargs["env"]["RQDATA_AS_OF"], "2026-10-09")
        output = Path(args[args.index("--output") + 1])
        self.assertNotEqual(output.parent, self.directory)
        value = json.loads(output.read_text(encoding="utf-8"))
        value["asOf"] = "2026-10-09"
        output.write_text(json.dumps(value), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    def test_partial_mode_keeps_successful_sources_and_reports_failure(self):
        with tempfile.TemporaryDirectory(dir=updater.BASE_DIR) as temporary:
            self.directory=Path(temporary)
            self.seed(self.directory)
            def run(args, **kwargs):
                if 'rqdata_industry_refresh.py' in args[1]:
                    return subprocess.CompletedProcess(args,1,'','Quota exceeded')
                return self.fake_run(args,**kwargs)
            with patch.object(updater.subprocess,'run',side_effect=run):
                errors=updater.refresh_core_snapshots('2026-10-09',directory=self.directory,allow_partial=True)
            self.assertEqual(len(errors),1)
            self.assertEqual(updater.read_snapshot(self.directory/'rqdata-broad-sentiment.json')['asOf'],'2026-10-09')
            self.assertEqual(updater.read_snapshot(self.directory/'rqdata-industry-sentiment.json')['asOf'],'2026-10-08')

    def test_success_commits_one_date(self):
        with tempfile.TemporaryDirectory(dir=updater.BASE_DIR) as temporary:
            self.directory = Path(temporary)
            self.seed(self.directory)
            with patch.object(updater.subprocess, "run", side_effect=self.fake_run):
                updater.refresh_core_snapshots("2026-10-09", directory=self.directory)
            updater.verify_snapshots(self.directory, "2026-10-09")

    def test_failure_keeps_entire_previous_batch(self):
        with tempfile.TemporaryDirectory(dir=updater.BASE_DIR) as temporary:
            self.directory = Path(temporary)
            self.seed(self.directory)
            before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
            def run(args, **kwargs):
                if "rqdata_industry_refresh.py" in args[1]:
                    return subprocess.CompletedProcess(args, 1, "", "provider unavailable")
                return self.fake_run(args, **kwargs)
            with patch.object(updater.subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(RuntimeError, "previous snapshots retained"):
                    updater.refresh_core_snapshots("2026-10-09", directory=self.directory)
            self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})

    def test_success_exit_with_stale_date_rejected(self):
        with tempfile.TemporaryDirectory(dir=updater.BASE_DIR) as temporary:
            self.directory = Path(temporary)
            self.seed(self.directory)
            with patch.object(updater.subprocess, "run", return_value=
                              subprocess.CompletedProcess([], 0, "", "")):
                with self.assertRaisesRegex(ValueError, "trading date mismatch"):
                    updater.refresh_core_snapshots("2026-10-09", directory=self.directory)
            updater.verify_snapshots(self.directory, "2026-10-08")

    def test_replacement_error_restores_all_original_files(self):
        with tempfile.TemporaryDirectory(dir=updater.BASE_DIR) as temporary:
            self.directory = Path(temporary)
            self.seed(self.directory)
            before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
            original_replace = Path.replace
            replacements = []
            def replace(path, target):
                replacements.append(target)
                if len(replacements) == 3:
                    raise OSError("file locked")
                return original_replace(path, target)
            with patch.object(updater.subprocess, "run", side_effect=self.fake_run), \
                    patch.object(Path, "replace", new=replace):
                with self.assertRaisesRegex(OSError, "file locked"):
                    updater.refresh_core_snapshots("2026-10-09", directory=self.directory)
            self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})


if __name__ == "__main__":
    unittest.main()
