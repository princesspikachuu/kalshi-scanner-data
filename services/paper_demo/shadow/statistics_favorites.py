"""Statistics-backed Favorites paper strategy; collector evidence remains read-only."""
import json
from .favorites import FavoritesStrategy
from .favorite_statistics import statistics_quote,StatisticsFavoritesMixin,price_bucket
from .favorite_timing import clock,horizon,market_type
from decimal import Decimal as D

class StatisticsFavoritesStrategy(StatisticsFavoritesMixin,FavoritesStrategy):
    def __init__(self,engine,profile):
        super().__init__(engine,profile)
        self.last_reason='Learning from settled outcomes and small targeted paper probes'
        self._decision_signatures={};self._statistics_groups=None;self._statistics_groups_at=-1e9
    def choose_entry_side(self,ticker,quotes):
        """Prioritize a maker-fillable, under-sampled side, not just the higher bid."""
        market=self.e.markets[ticker];remaining,_=clock(market,self.e.now)
        groups=self.statistics_groups()
        options=[]
        for _,side in quotes:
            book=self.e.books[ticker];bid,ask=book.bid(side),book.ask(side)
            if bid is None or ask is None or bid>=ask:continue
            price=min(bid+D('.01'),ask-D('.01'),D('.95'))
            if not D('.70')<=price<=D('.95'):continue
            key=('market_type_price_time_side',(market_type(self.profile,market),side,price_bucket(price),horizon(remaining)))
            exact=groups.get(key)
            n=len(exact['events']) if exact else 0
            # Data gaps are prioritized; remaining evidence and maker spread
            # provide deterministic tie-breakers. No speculative probability.
            target=int(self.profile.get('statistics_exploration_target_samples',20))
            under=max(0,target-n)
            options.append(((under>0,under,ask-bid,bid),side))
        return max(options)[1] if options else None

    def entry_quote(self,ticker,side,max_price=None):
        q,decision=statistics_quote(self.e,self.profile,self.contracts,ticker,side,self._source_cells(),max_price,self.statistics_groups())
        decision=dict(decision,ticker=ticker,side=side,policy='favorites-statistics-v1',traded=bool(q))
        self.decisions[ticker]=decision
        signature=json.dumps({k:decision.get(k) for k in ('reason','level','samples','exact_samples','price','side','decision_type')},sort_keys=True)
        if self._decision_signatures.get(ticker)!=signature:
            self._decision_signatures[ticker]=signature
            self.e.log('FAVORITE_STAT_DECISION',ticker=ticker,reason=decision.get('reason'),details=json.dumps(decision))
        if not q:
            self.last_reason=f"Statistics skip · {decision.get('reason')} · n={decision.get('samples',0)}" 
        return q
    def submit_entry(self,ticker,a,q):
        super().submit_entry(ticker,a,q)
        d=dict(self.decisions.get(ticker,{}),traded=True)
        self.decisions[ticker]=d
