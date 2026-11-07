"""Shared bounded subscriptions, with candidate slots separate from owned lots."""
MAX_EXTRA=48
MAX_TOTAL=64
CATEGORY_LIMITS={'weather':8,'weather_daily':7,'hourly':12,'sports':4}


def capacity(suite,now):
    legacy=sum(m['close']>now for m in suite.host.engine.markets.values())
    return max(0,min(MAX_EXTRA,MAX_TOTAL-legacy))


def candidate_markets(suite,markets,category,now):
    found=[]
    for ticker,m in markets.items():
        asset=m.get('weather_category') or ('hourly' if m.get('hourly_price') else 'sports' if m.get('sports') else None)
        if asset!=category or m.get('paid') or m['close']<=now:continue
        # Inventory keeps its data subscription, but must not consume the slots
        # reserved for discovering new opportunities in that category.
        held=False
        for engine,fleet,_ in suite.portfolios.values():
            if ticker not in engine.markets:continue
            owner=fleet.owner(ticker)
            if any(l.ticker==ticker for l in engine.wallet.lots) or (owner and owner.attempts.get(ticker,{}).get('first')):
                held=True;break
        if not held:found.append(ticker)
    return found


def next_profile(suite,choices,candidates,cursor):
    # One new candidate per series before adding a second in the same series.
    for offset in range(len(choices)):
        index=(cursor+offset)%len(choices)
        p=choices[index]
        if not any(t.startswith(p['series']+'-') for t in candidates):
            return p,index+1
    return None,cursor
