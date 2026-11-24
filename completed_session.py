"""Completed-session selection independent of scheduler arrival time."""
from datetime import timedelta

def completed_target(now, calendar):
    limit=now.date() if now.hour>=18 else now.date()-timedelta(days=1)
    days=sorted({str(d)[:10] for d in calendar if str(d)[:10]<=str(limit)})
    if not days:raise ValueError("No verified completed trading session")
    return days[-1]
