import unittest
from datetime import date, timedelta

from akshare_margin_risk import transform


class Frame:
    def __init__(self, rows):
        self.rows = rows
        self.columns = rows[0].keys()

    def to_dict(self, orientation):
        assert orientation == "records"
        return self.rows


class MarginRiskTests(unittest.TestCase):
    def test_personal_investor_units_and_as_of_filter(self):
        start = date(2025, 1, 1)
        rows = [{
            "日期": start + timedelta(days=index),
            "平均维持担保比例": 250 + index / 100,
            "参与交易的投资者数量": 300_000,
            "个人投资者数量": 800,
            "机构投资者数量": 50_000,
        } for index in range(102)]
        result = transform(Frame(rows), (start + timedelta(days=100)).isoformat())
        guarantee, participation = result["series"]
        self.assertEqual(result["asOf"], (start + timedelta(days=100)).isoformat())
        self.assertEqual(guarantee["points"][-1]["value"], 251)
        self.assertEqual(participation["points"][-1]["value"],
                         round(300_000 / (800 * 10_000 + 50_000) * 100, 4))
        self.assertEqual(len(guarantee["points"]), 101)

    def test_missing_account_fields_fail_loudly(self):
        with self.assertRaisesRegex(ValueError, "fields missing"):
            transform(Frame([{"日期": date(2025, 1, 1)}]), "2025-04-01")


if __name__ == "__main__":
    unittest.main()
