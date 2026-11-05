import json
import unittest
from pathlib import Path
from unittest.mock import patch

from akshare_public_refresh import apply_public_inputs, points
import pandas as pd


class PublicInputsTests(unittest.TestCase):
    def test_rejects_future_and_nonfinite_observations(self):
        frame = pd.DataFrame({"日期": ["2026-11-03", "2026-11-04", "2026-11-05"],
                              "收盘": [10.0, float("inf"), 12.0]})
        self.assertEqual(points(frame, "收盘", "2026-11-04"),
                         [{"date": "2026-11-03", "value": 10.0}])

    def test_old_provider_cannot_roll_back_series(self):
        # A stale fallback must preserve the newer observation and its source.
        old = {"id": "hs300-close", "source": "prior", "points": [
            {"date": "2026-11-04", "value": 100.0}]}
        incoming = {"id": "hs300-close", "source": "AKShare", "points": [
            {"date": "2026-11-03", "value": 90.0}]}
        with patch.object(Path, "exists", return_value=True), patch.object(
                Path, "read_text", return_value=json.dumps({"series": [incoming]})):
            result = apply_public_inputs({"series": [old]}, Path("."))
        self.assertEqual(result["series"], [old])


if __name__ == "__main__":
    unittest.main()
