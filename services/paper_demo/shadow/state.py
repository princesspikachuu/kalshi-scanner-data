"""Versioned durable shadow state, independent of transport and local files."""
from dataclasses import asdict
from .core import D, ZERO, Wallet, Lot, Stats, Order, Book, FeePolicy


def encode(engine, fleet):
    return dict(schema=1, now=engine.now,safety_until=engine.safety_until, serial=engine.serial,rng_state=engine.rng.getstate(),
        wallet=dict(cash=str(engine.wallet.cash),deposits=str(engine.wallet.deposits),
            lots=[asdict(l) for l in engine.wallet.lots],
            stats={k:asdict(v) for k,v in engine.wallet.stats.items()}),
        markets=engine.markets,fees={k:asdict(v) for k,v in engine.fees.items()},
        orders={k:asdict(v) for k,v in engine.orders.items()},pending=engine.pending,
        closed_reports=sorted(engine.closed_reports),settled=sorted(engine.settled),
        fleet={series:dict(phases=b.phases,entered=sorted(b.entered),locked=sorted(b.locked),
            halted=sorted(b.halted),safety_retries=sorted(b.safety_retries),emergency=b.emergency,last_exit=b.last_exit)
            for series,b in fleet.bots.items()})


def restore(engine,fleet,data):
    if data.get('schema') != 1:
        raise ValueError('Unsupported shadow checkpoint')
    def tuples(value):return tuple(tuples(v) for v in value) if isinstance(value,list) else value
    if 'rng_state' in data:engine.rng.setstate(tuples(data['rng_state']))
    w=data['wallet'];engine.wallet=Wallet(D(w['cash']));engine.wallet.deposits=D(w['deposits'])
    engine.wallet.lots=[Lot(**dict(l,**{k:D(l[k]) for k in
        ('quantity','price','entry_fee','recovery_cost','recovery_proceeds') if k in l})) for l in w['lots']]
    decimal_stats=[k for k,v in asdict(Stats()).items() if isinstance(v,D)]
    engine.wallet.stats={k:Stats(**dict(v,**{field:D(v[field]) for field in decimal_stats if field in v}))
                         for k,v in w['stats'].items()}
    engine.safety_until=data.get('safety_until',0)
    engine.markets=data['markets'];engine.serial=data['serial'];engine.now=data['now']
    engine.fees={k:FeePolicy(**{field:D(value) for field,value in v.items()}) for k,v in data['fees'].items()}
    engine.books={ticker:Book() for ticker in engine.markets}
    fields=('quantity','price','remaining','ahead','reserved')
    engine.orders={k:Order(**dict(v,**{f:D(v[f]) for f in fields},reference=D(v['reference'])
        if v.get('reference') is not None else None)) for k,v in data['orders'].items()}
    engine.pending=[tuple(v) for v in data['pending']]
    engine.closed_reports=set(data['closed_reports']);engine.settled=set(data['settled'])
    for series,info in data['fleet'].items():
        if series not in fleet.bots:continue
        b=fleet.bots[series]
        b.phases=info['phases'];b.entered={tuple(v) for v in info['entered']}
        b.locked={tuple(v) for v in info['locked']};b.halted.update(info['halted'])
        b.safety_retries={tuple(v) for v in info.get('safety_retries',[])}
        b.emergency=info['emergency'];b.last_exit=info['last_exit']
    # Never replay hypothetical submissions across unobserved downtime. Wallet/fills
    # remain durable; interrupted cycles are excluded and entries wait for new cycles.
    for order in engine.orders.values():
        if order.status in ('pending','resting'):
            order.status='cancelled';order.reserved=ZERO
    engine.pending=[]
    for ticker in engine.markets:
        if ticker not in engine.settled:
            engine.wallet.stat(ticker).valid=False
            owner=fleet.owner(ticker)
            if getattr(owner,'recover_fresh_entries',False) and ticker not in fleet.halted:
                engine.markets[ticker]['entry_recovery_halt']=True
            fleet.halted.add(ticker)
