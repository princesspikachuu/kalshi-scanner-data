"""Daily entry windows follow the dated city's day, not delayed venue settlement.

The supported daily series identify a city and date. Entry ends by local midnight
(or an earlier venue close); payout still needs the venue's authoritative result.
Unknown dates/cities fail closed for entries. No outcome is inferred from time.
"""
from datetime import datetime,timedelta,time as day_time
from functools import lru_cache
import re
from zoneinfo import ZoneInfo

CITY_ZONES={'KXHIGHNY':'America/New_York','KXHIGHTEWR':'America/New_York',
    'KXHIGHMIA':'America/New_York','KXHIGHCHI':'America/Chicago',
    'KXHIGHAUS':'America/Chicago','KXHIGHDEN':'America/Denver','KXHIGHLAX':'America/Los_Angeles'}
MONTHS={name:index+1 for index,name in enumerate(('JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'))}

def is_daily(m):
    return m.get('weather_category')=='weather_daily' or str(m.get('ticker','')).split('-')[0] in CITY_ZONES

@lru_cache(maxsize=4096)
def _day_end(ticker,event):
    series=ticker.split('-')[0];zone=CITY_ZONES.get(series)
    if not zone:return None
    match=re.fullmatch(re.escape(series)+r'-(\d{2})([A-Z]{3})(\d{2})(?:-.*)?',event or ticker)
    if not match:return None
    try:
        year,month,day=match.groups();date=datetime(2000+int(year),MONTHS[month],int(day)).date()
        return datetime.combine(date+timedelta(days=1),day_time(),ZoneInfo(zone)).timestamp()
    except (ValueError,KeyError):return None

def daily_day_end(m):
    return _day_end(str(m.get('ticker','')),str(m.get('event_ticker','')))

def entry_allowed(m,now):
    end=daily_day_end(m)
    return end is not None and end-7200<=now<min(end,float(m['close']))-60

def entry_end(m):
    end=daily_day_end(m)
    return min(float(m['close']),end) if end is not None else None

def observation_end(m):
    end=entry_end(m) if is_daily(m) else None
    return end if end is not None else m['close']
