import unittest
from datetime import datetime
from completed_session import completed_target
class CompletedTests(unittest.TestCase):
    days=['2026-11-19','2026-11-20','2026-11-23','2026-11-24']
    def test_delayed_next_morning(self):
        self.assertEqual(completed_target(datetime(2026,11,24,6),self.days),'2026-11-23')
    def test_evening(self):
        self.assertEqual(completed_target(datetime(2026,11,24,19),self.days),'2026-11-24')
    def test_weekend(self):
        self.assertEqual(completed_target(datetime(2026,11,22,19),self.days),'2026-11-20')
    def test_missing_calendar_fails(self):
        with self.assertRaises(ValueError):completed_target(datetime(2026,11,24,6),[])
if __name__=='__main__':unittest.main()
