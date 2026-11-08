"""Bounded admission for new candidates; existing exposure is never evicted."""
from collections import deque

def maker_entry_limit(stats):
    own=stats['categories'].get('market_maker',0)
    # Leave two additional discovery slots available to other strategies.
    other_entries=max(0,stats['entry_markets']-own)
    other_subscriptions=max(0,stats['subscribed_markets']-own)
    return max(0,min(8+4*stats['level'],stats['entry_candidates']-other_entries-2,
        stats['total']-other_subscriptions-2))

def category(m):
    return 'market_maker' if m.get('market_maker') else m.get('weather_category') or ('sports' if m.get('sports') else 'hourly' if m.get('hourly_price') else 'complete_set')

class MonitoringBudget:
    def __init__(self):
        self.samples=deque(maxlen=600);self.service_samples=deque(maxlen=600);self.healthy_since=None;self.level=0;self.last_at=None
    def observe(self,now,backlog,lag_seconds,per_input_ms,cooldown=0,input_count=None):
        if self.last_at is None or now-self.last_at>10:
            self.healthy_since=None;self.level=0
        self.samples.append((now,max(0,lag_seconds),max(0,per_input_ms)))
        while self.samples and now-self.samples[0][0]>60:self.samples.popleft()
        recent=sorted(s[1] for s in self.samples);costs=sorted(s[2] for s in self.samples)
        at=max(0,int(len(recent)*.95)-1)
        self.lag_p95=recent[at];self.processing_p95=costs[at];self.backlog=backlog;self.cooldown=cooldown
        # A recent overload resets the growth window. Stale telemetry cannot
        # authorize discovery, even if the previous sample looked healthy.
        # A tiny batch pays a whole checkpoint's fixed cost. Multiplying its
        # per-input cost by a large queue exaggerates drain time. Use measured
        # committed burst throughput only with enough fresh supporting inputs.
        if input_count is not None and input_count>=32:
            self.service_samples.append((now,input_count,max(0,per_input_ms)*input_count))
        while self.service_samples and now-self.service_samples[0][0]>60:self.service_samples.popleft()
        fresh_service=[s for s in self.service_samples if now-s[0]<=5]
        self.service_inputs=sum(s[1] for s in fresh_service)
        self.queue_cost_basis='p95 per-input fallback';self.service_ms=self.processing_p95
        if self.service_inputs>=128:
            recent_cost=sum(s[2] for s in fresh_service)/self.service_inputs
            long_cost=sum(s[2] for s in self.service_samples)/sum(s[1] for s in self.service_samples)
            self.service_ms=max(recent_cost,long_cost)
            self.queue_cost_basis='committed burst throughput; slower of 5s and 60s'
        self.queue_seconds=backlog*self.service_ms/1000
        overloaded=backlog>2000 or self.queue_seconds>.5 or self.lag_p95>2 or self.processing_p95>100 or cooldown>0
        healthy=backlog<=50 and self.lag_p95<.5 and self.processing_p95<20 and not cooldown
        if overloaded:self.level=0;self.healthy_since=None
        elif healthy:
            if self.healthy_since is None:self.healthy_since=now
            self.level=min(2,int((now-self.healthy_since)//120))
        else:self.healthy_since=None
        self.overloaded=overloaded;self.last_at=now
    def limits(self,now):
        fresh=self.last_at is not None and 0<=now-self.last_at<=10
        level=self.level if fresh else 0
        return dict(total=32+8*level,entry_candidates=12+4*level,per_category=4+4*level,
            admitting=fresh and not self.overloaded,telemetry_fresh=fresh,level=level,
            reason='Waiting for current load measurements' if not fresh else 'Discovery paused: processing lag or read cooldown' if self.overloaded else 'Measured capacity available',
            backlog=getattr(self,'backlog',0),estimated_queue_seconds=getattr(self,'queue_seconds',None),lag_p95_seconds=getattr(self,'lag_p95',None),
            queue_cost_basis=getattr(self,'queue_cost_basis',None),queue_service_ms=getattr(self,'service_ms',None),service_sample_inputs=getattr(self,'service_inputs',0),
            processing_p95_ms=getattr(self,'processing_p95',None),read_cooldown_seconds=getattr(self,'cooldown',0))

def protected(suite,ticker,now):
    for e,f,ps in suite.portfolios.values():
        if any(l.ticker==ticker for l in e.wallet.lots):return True
        if any(o.ticker==ticker and o.status in ('pending','resting') and o.action=='sell' for o in e.orders.values()):return True
        m=e.markets.get(ticker,{})
        # Preserve the whole-game shared view so late-only Favorites can join.
        if m.get('sports') and m.get('sports_live') and m.get('sports_expected_end',0)>now and any(
            b.enabled and b.profile.get('strategy')=='favorites' and b.series==ticker.split('-')[0] for b in f.bots.values()):return True
    return False
