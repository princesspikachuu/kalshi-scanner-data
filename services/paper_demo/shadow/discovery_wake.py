"""Known entry-window wake hints; never substitute for fresh provider/fee evidence.

UTC epoch hints are carried in the existing experiment checkpoint. Known
out-of-window markets do not consume discovery reads. Unknown or changed
schedules retain ordinary provider discovery, never guessed eligibility.
"""
from datetime import datetime, timedelta, time as day_time
from zoneinfo import ZoneInfo
import math

from .runner import ts
from .weather_window import CITY_ZONES, entry_end


def wake_state(suite):
    state=getattr(suite, 'discovery_wakes', None)
    if not isinstance(state, dict):
        state=suite.discovery_wakes={}
    return state


def asleep(suite,key,now):
    state=wake_state(suite)
    wake=state.get(key,0)
    if isinstance(wake,(int,float)) and math.isfinite(wake) and wake>now:
        return True
    state.pop(key,None)
    return False


def remember(suite,key,when,now):
    state=wake_state(suite)
    if isinstance(when,(int,float)) and math.isfinite(when) and when>now:
        state[key]=float(when)
    else:
        state.pop(key,None)


def daily_scan_wake(series,now):
    """Return next city-local 22:00; None inside today's 22:00-midnight entry.

    The venue may close earlier, which is checked against the actual market
    before any trading. DST and local day changes use the IANA time zone.
    """
    zone=CITY_ZONES.get(series)
    if not zone:return None
    tz=ZoneInfo(zone)
    local=datetime.fromtimestamp(now,tz)
    for offset in range(3):
        end=datetime.combine(local.date()+timedelta(days=offset+1),day_time(),tz).timestamp()
        start=end-7200
        if now<start:return start
        if start<=now<end-60:return None
    return None


def known_entry_wake(raw,kind,now):
    """Earliest *future* eligible scan based on provider market timestamps.

    A wake is a scheduling hint, not a trading authorization. Every resumed
    scan still checks market status, fresh book, fees and position safeguards.
    """
    try:
        opens=ts(raw['open_time'])
        closes=ts(raw['close_time'])
        if not (math.isfinite(opens) and math.isfinite(closes)):return None
        if kind=='weather_daily':
            end=entry_end(dict(ticker=raw['ticker'],event_ticker=raw.get('event_ticker'),
                weather_category='weather_daily',close=closes))
            if end is None:return None
            start=max(opens,end-7200)
            cutoff=min(end,closes)-60
        elif kind=='hourly':
            start=max(opens,closes-3600)
            cutoff=closes-60
        elif kind=='sports':
            end=ts(raw['expected_expiration_time'])
            if not math.isfinite(end) or end>closes:return None
            # Only prewarm the status lookup five minutes before the late
            # window. A fresh live status remains mandatory at actual entry.
            start=max(opens,end-7200-300)
            cutoff=min(end,closes)-60
        else:
            start=opens
            cutoff=closes-60
        if start<cutoff and start>now:return start
    except (KeyError,ValueError,TypeError,OverflowError):
        return None
    return None
