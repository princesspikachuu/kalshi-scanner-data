from datetime import datetime,timezone
import unittest
from services.research.campaigns import daily_due

class DailyScheduleTests(unittest.TestCase):
    def test_daily_fixed_pacific_time_and_dst(self):
        utc=timezone.utc
        # 3am Pacific is 10UTC in summer, 11UTC in winter.
        cases=[('2026-10-27T09:00:00+00:00','03:00','2026-10-27T10:00:00+00:00'),
               ('2026-10-27T10:00:00+00:00','03:00','2026-10-28T10:00:00+00:00'),
               ('2026-11-01T09:00:00+00:00','03:00','2026-11-01T11:00:00+00:00'),
               ('2026-03-08T09:00:00+00:00','02:30','2026-03-08T10:30:00+00:00'),
               ('2026-11-01T08:45:00+00:00','01:30','2026-11-02T09:30:00+00:00')]
        for now,clock,expected in cases:
            self.assertEqual(daily_due(datetime.fromisoformat(now),clock).isoformat(),expected)
        for value in ('3:00','24:00','12:60','03:00Z','ab:cd',True):
            with self.assertRaises(ValueError):daily_due(datetime.now(utc),value)
