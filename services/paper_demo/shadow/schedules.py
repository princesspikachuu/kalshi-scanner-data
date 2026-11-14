"""Wake hints for verified cash-index sessions; never an entry authorization.

NYSE cash-equity calendar: https://www.nyse.com/trade/hours-calendars
Only cash S&P/Nasdaq series use this calendar. Crypto, FX, metals and unknown
series retain provider-driven discovery; unknown calendar years fail open.
"""
from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo

CASH_INDEX_SERIES={'KXINXU','KXNASDAQ100U'}
HOLIDAYS={
    2026:'01-01 01-19 02-16 04-03 05-25 06-19 07-03 09-07 11-26 12-25',
    2027:'01-01 01-18 02-15 03-26 05-31 06-18 07-05 09-06 11-25 12-24',
    2028:'01-17 02-21 04-14 05-29 06-19 07-04 09-04 11-23 12-25',
}
EARLY_CLOSE={2026:{'11-27','12-24'},2027:{'11-26'},2028:{'07-03','11-24'}}
EASTERN=ZoneInfo('America/New_York')

def session_wake(series,now):
    """None while active/unknown, otherwise next prewarm at 09:29 ET."""
    if series not in CASH_INDEX_SERIES:return None
    local=datetime.fromtimestamp(now,EASTERN)
    if local.year not in HOLIDAYS:return None
    for offset in range(10):
        day=local.date()+timedelta(days=offset)
        if day.year not in HOLIDAYS:return None
        key=day.strftime('%m-%d')
        if day.weekday()>=5 or key in HOLIDAYS[day.year].split():continue
        opening=datetime.combine(day,time(9,30),EASTERN).timestamp()-60
        closing=datetime.combine(day,time(13 if key in EARLY_CLOSE.get(day.year,set()) else 16),EASTERN).timestamp()
        if opening<=now<closing:return None
        if now<opening:return opening
    return None
