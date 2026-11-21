"""Three-by-three Favorites research, without inventing legacy entry timestamps."""
from decimal import Decimal as D
from .observation_returns import merge,summarize

PRICES=((D('.70'),D('.78'),'70–<78¢'),(D('.78'),D('.86'),'78–<86¢'),(D('.86'),D('.95'),'86–95¢'))
TIME_INTERVALS={'<3m':(0,180),'3–5m':(180,300),'5–10m':(300,600),'10–15m':(600,900),
                '15–30m':(900,1800),'30–60m':(1800,3600),'1–2h':(3600,7200)}

def price_band(price):
    value=D(str(price))
    return next((i for i,(lo,hi,_) in enumerate(PRICES) if lo<=value and (value<hi or i==2 and value==hi)),None)

def duration(profile):
    if profile.get('asset') in ('sports','weather_daily'):return None
    return 900 if profile.get('series','').endswith('15M') else 3600

def _label(seconds):
    minutes=int(float(seconds)//60);remaining=float(seconds)-minutes*60
    if abs(remaining)<1e-6:return f'{minutes}m'
    part=f'{remaining:.3f}'.rstrip('0').rstrip('.')+'s'
    return (f'{minutes}m ' if minutes else '')+part

def summarize_wide(folder_bots,profiles,category_for):
    sources={};bounds={};by_bot={};specs={}
    for bot_id,bot in folder_bots.items():
        profile=profiles.get(str(bot_id),{})
        if not profile:continue
        category=category_for(profile);sources.setdefault(category,[]);specs[category]=profile
        for row in bot.get('entry_timing',[]):
            sources.setdefault(category,[]).append((str(bot_id),profile,row))
            if duration(profile) is None:
                times=[float(v) for v in (row.get('time_min'),row.get('time_max')) if v is not None]
                times.extend(float(record[0]) for records in row.get('wide_events',{}).values() for record in records)
                if times:
                    old=bounds.get(category,(min(times),max(times)))
                    bounds[category]=(min(old[0],min(times)),max(old[1],max(times)))
    output={};coverage={}
    for category,items in sources.items():
        nominal=duration(specs[category]);lo,hi=(0,nominal) if nominal else bounds.get(category,(0,0))
        report=dict(window_start_seconds=lo,window_end_seconds=hi,time_basis='market_duration' if nominal else 'observed_entry_window',
                    excluded_legacy_observations=0,excluded_price_observations=0)
        coverage[category]=report
        if hi<=lo:
            report['reason']='Waiting for an observed betting window with distinct entry times';output[category]=[];continue
        cuts=[lo+(hi-lo)*i/3 for i in range(4)]
        labels=[_label(cuts[i])+'–'+_label(cuts[i+1]) for i in range(3)]
        report.update(time_buckets=labels,reason='ready')
        groups={};bot_groups={}
        def add(target,band,slot,event,payout,q,cost,realized=None):
            cell=target.setdefault((band,slot),{})
            item=cell.setdefault(str(event),dict(outcome=int(payout),quantity=D(0),cost=D(0),returns={},incomplete=False))
            item['outcome']=min(item['outcome'],int(payout));item['quantity']+=q;item['cost']+=cost
            if realized:merge(item['returns'],{str(event):realized})
            else:
                # A separate entry in this same event/price/time cell lacks a
                # verified hold return. Do not publish a partial-event ROI.
                item['incomplete']=True
        for bot_id,profile,row in items:
            events=row.get('outcome_events',{})
            band=price_band(row.get('price','0'))
            if band is None:report['excluded_price_observations']+=len(events);continue
            exact=row.get('wide_events',{})
            targets=(groups,bot_groups.setdefault(bot_id,{}))
            for event,records in exact.items():
                if event not in events:continue
                payout=int(events[event])
                for seconds,quantity,cost,*actual_net in records:
                    seconds=float(seconds)
                    if not lo<=seconds<=hi:continue
                    slot=min(2,int(3*(seconds-lo)/(hi-lo)))
                    q=D(quantity);c=D(cost)
                    for target in targets:add(target,band,slot,event,payout,q,c,dict(cost=str(c),net=str(actual_net[0])) if actual_net else None)
            # Legacy time ranges are included only when the ENTIRE old interval
            # belongs to one new bin. Never spread one event across guessed bins.
            remaining={event:value for event,value in events.items() if event not in exact}
            interval=TIME_INTERVALS.get(row.get('horizon'))
            slot=next((i for i in range(3) if interval and cuts[i]<=interval[0] and interval[1]<=cuts[i+1]),None)
            if slot is None:report['excluded_legacy_observations']+=len(remaining);continue
            qty=D(row.get('contracts','0'));unit_cost=D(row.get('cost','0'))/qty if qty else D(str(row['price']))
            for event,payout in remaining.items():
                realized=row.get('return_events',{}).get(event)
                for target in targets:add(target,band,slot,event,payout,D(1),unit_cost,realized)
        def rows(target):
            result=[]
            for (band,slot),events in sorted(target.items()):
                returns={event:value['returns'][event] for event,value in events.items()
                         if not value['incomplete'] and event in value['returns']}
                n=len(events);wins=sum(value['outcome'] for value in events.values())
                # One event receives one vote for both outcome accuracy and
                # average entry. Multi-contract positions do not inflate n.
                entry=sum((v['cost']/v['quantity'] for v in events.values() if v['quantity']>0),D(0))
                result.append(dict(series='combined',market_type=category,clock='estimated_game_end' if specs[category].get('asset')=='sports' else 'market_close',
                    price=str(PRICES[band][0]),band=PRICES[band][2],horizon=labels[slot],time_slot=slot,wide=True,
                    events=n,event_wins=wins,event_win_rate=100*wins/n if n else None,
                    contracts=str(n),cost=str(entry),closed=str(len(returns)),net=str(sum((D(v['net']) for v in returns.values()),D(0))),
                    **summarize(returns)))
            return result
        output[category]=rows(groups)
        for bot_id,group in bot_groups.items():by_bot[bot_id]=dict(rows=rows(group),coverage=report)
    return dict(rows=output,coverage=coverage,by_bot=by_bot,price_buckets=[label for _,_,label in PRICES])
