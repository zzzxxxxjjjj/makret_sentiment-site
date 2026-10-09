import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

import cloud_daily_update
from rqdata_trading_day import CHINA_TIME, completed_trading_date


class Calendar:
    def __init__(self, latest="2026-10-09", holidays=()):
        self.latest = date.fromisoformat(latest)
        self.holidays = set(holidays)

    def get_latest_trading_date(self):
        return self.latest

    def get_trading_dates(self, start, end):
        return [date.fromordinal(day) for day in range(start.toordinal(), end.toordinal() + 1)
                if date.fromordinal(day).weekday() < 5
                and date.fromordinal(day) not in self.holidays]


class TradingDayTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"RQDATA_AS_OF": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def target(self, stamp, calendar=None):
        return completed_trading_date(calendar or Calendar(), now=datetime.fromisoformat(stamp))

    def test_before_evening_uses_previous_day(self):
        self.assertEqual(self.target("2026-10-09T17:59:59+08:00"), date(2026, 10, 8))

    def test_scheduled_evening_includes_today(self):
        self.assertEqual(self.target("2026-10-09T18:17:00+08:00"), date(2026, 10, 9))

    def test_utc_runner_uses_china_clock(self):
        self.assertEqual(self.target("2026-10-09T10:17:00+00:00"), date(2026, 10, 9))

    def test_weekend(self):
        self.assertEqual(self.target("2026-10-10T18:17:00+08:00"), date(2026, 10, 9))

    def test_holiday_uses_calendar(self):
        calendar = Calendar(holidays=[date(2026, 10, 9)])
        self.assertEqual(self.target("2026-10-09T18:17:00+08:00", calendar), date(2026, 10, 8))

    def test_provider_not_yet_on_today(self):
        self.assertEqual(self.target("2026-10-09T18:17:00+08:00", Calendar("2026-10-08")),
                         date(2026, 10, 8))

    def test_pinned_run_crosses_midnight(self):
        os.environ["RQDATA_AS_OF"] = "2026-10-09"
        self.assertEqual(self.target("2026-10-10T00:15:00+08:00"), date(2026, 10, 9))

    def test_future_pin_rejected(self):
        os.environ["RQDATA_AS_OF"] = "2026-10-09"
        with self.assertRaises(ValueError):
            self.target("2026-10-09T12:00:00+08:00")

    def test_nontrading_pin_rejected(self):
        os.environ["RQDATA_AS_OF"] = "2026-10-10"
        with self.assertRaises(ValueError):
            self.target("2026-10-11T18:17:00+08:00", Calendar("2026-10-11"))

    def test_stale_data_still_rejected_with_dates(self):
        with patch.object(cloud_daily_update, "read_cache", return_value={"asOf": "2026-10-08"}):
            with self.assertRaisesRegex(ValueError, "expected 2026-10-09, actual 2026-10-08"):
                cloud_daily_update.verify_core_dates("2026-10-09")


if __name__ == "__main__":
    unittest.main()
