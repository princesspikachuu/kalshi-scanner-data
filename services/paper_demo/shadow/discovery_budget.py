"""Fair candidate selection within the shared adaptive monitoring budget."""
from .monitoring import protected,category

CATEGORY_LIMITS={'weather':8,'weather_daily':7,'hourly':12,'sports':4}


def candidate_markets(suite,markets,asset,now):
    return [t for t,m in markets.items() if category(m)==asset and not m.get('paid')
            and m['close']>now and not protected(suite,t,now)]


def next_profile(suite,choices,candidates,cursor):
    # One new candidate per series before adding a second in the same series.
    for offset in range(len(choices)):
        index=(cursor+offset)%len(choices)
        p=choices[index]
        if not any(t.startswith(p['series']+'-') for t in candidates):
            return p,index+1
    return None,cursor
