"""Accept only documented zero-maker-fee schedules for new pilot entries."""
from datetime import datetime
from .risk import RiskBlocked

def zero_maker_fees(exchange,series,event,close):
    current=exchange.public_get('/series/'+series).get('series',{})
    if current.get('fee_type')!='quadratic':raise RiskBlocked('Maker fees are nonzero or could not be verified')
    page=exchange.public_get('/series/fee_changes',dict(series_ticker=series))
    changes=page.get('series_fee_change_arr')
    if not isinstance(changes,list) or len(changes)>1000:raise RiskBlocked('Could not verify series fee changes')
    event_changes=[];cursor=None
    for _ in range(5):
        page=exchange.public_get('/events/fee_changes',dict(event_ticker=event,limit=200,**({'cursor':cursor} if cursor else {})))
        rows=page.get('event_fee_changes')
        if not isinstance(rows,list) or len(rows)>200:raise RiskBlocked('Could not verify event fee overrides')
        event_changes.extend(rows)
        following=page.get('cursor')
        if not following:break
        if following==cursor:raise RiskBlocked('Could not finish fee verification')
        cursor=following
    else:raise RiskBlocked('Could not finish fee verification')
    for change in changes+event_changes:
        try:scheduled=datetime.fromisoformat(change['scheduled_ts'].replace('Z','+00:00')).timestamp()
        except (KeyError,ValueError,TypeError):raise RiskBlocked('Fee schedule has an unknown effective time') from None
        # Conservative: even a previous nonzero override requires review rather
        # than guessing which clear/override wins across an incomplete history.
        if scheduled<=close and change.get('fee_type',change.get('fee_type_override')) not in (None,'quadratic'):
            raise RiskBlocked('Maker fees change before this market closes')
    return True
