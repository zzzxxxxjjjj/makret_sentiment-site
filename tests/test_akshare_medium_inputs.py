import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from akshare_medium_inputs import fetch


class FakeAKShare:
    def __init__(self):
        self.bond_requests = []

    def stock_zh_index_hist_csindex(self, **kwargs):
        self.index_symbol = kwargs["symbol"]
        return pd.DataFrame({
            "日期": [date(2026, 10, 13), date(2026, 10, 14)],
            "收盘": [100, 101], "滚动市盈率": [18, 19],
        })

    def stock_zh_index_value_csindex(self, **kwargs):
        return pd.DataFrame({"日期": [date(2026, 10, 14)], "股息率2": [1.8]})

    def bond_china_close_return(self, **kwargs):
        self.bond_requests.append(kwargs)
        return pd.DataFrame({
            "日期": [date.fromisoformat(kwargs["start_date"][:4] + "-" + kwargs["start_date"][4:6] + "-" + kwargs["start_date"][6:])],
            "期限": [10.0], "到期收益率": [1.7],
        })


class AKShareMediumInputsTest(unittest.TestCase):
    def test_collects_named_sources_without_substituting_fund_index(self):
        fake = FakeAKShare()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inputs.json"
            payload = fetch("2026-10-14", path, ak=fake)
            self.assertEqual(fake.index_symbol, "000985")
            self.assertFalse(payload["readyForPublishedMediumScore"])
            self.assertEqual(len(fake.bond_requests), 22)
            self.assertTrue(all(request["start_date"] == request["end_date"] for request in fake.bond_requests))
            self.assertEqual(
                {item["id"] for item in payload["series"]},
                {"csi-all-share-close", "csi-all-share-pe-rolling", "csi-all-share-dividend-yield", "cdb-10y-close-yield"},
            )
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["indexCode"], "000985")


if __name__ == "__main__":
    unittest.main()
