"""One completed trading-day policy for local and cloud daily snapshots."""
from datetime import date, datetime, time, timedelta, timezone
import os


CHINA_TIME = timezone(timedelta(hours=8))
DAILY_READY_TIME = time(18, 0)


def as_date(value):
    return value.date() if isinstance(value, datetime) else date.fromisoformat(str(value)[:10])


def completed_trading_date(rq, *, now=None):
    now = now or datetime.now(CHINA_TIME)
    if now.tzinfo is not None:
        now = now.astimezone(CHINA_TIME)
    # Conservatively allow today's daily data only after the evening cutoff.
    limit = now.date()
    if now.time() < DAILY_READY_TIME:
        limit -= timedelta(days=1)
    latest = as_date(rq.get_latest_trading_date())
    limit = min(limit, latest)
    pinned = os.environ.get("RQDATA_AS_OF", "").strip()
    if pinned:
        target = date.fromisoformat(pinned)
        if target > limit:
            raise ValueError("RQDATA_AS_OF is later than the completed trading-day limit")
        calendar = rq.get_trading_dates(target, target)
        if target not in [as_date(item) for item in calendar]:
            raise ValueError("RQDATA_AS_OF is not a trading day")
        return target
    calendar = rq.get_trading_dates(limit - timedelta(days=60), limit)
    completed = [as_date(item) for item in calendar if as_date(item) <= limit]
    if not completed:
        raise ValueError("No completed trading day found in the recent calendar")
    return max(completed)
