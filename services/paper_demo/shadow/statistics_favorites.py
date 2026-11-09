"""Statistics-backed Favorites paper strategy; collector evidence remains read-only."""
import json
from .favorites import FavoritesStrategy
from .favorite_statistics import statistics_quote,StatisticsFavoritesMixin

class StatisticsFavoritesStrategy(StatisticsFavoritesMixin,FavoritesStrategy):
    def __init__(self,engine,profile):
        super().__init__(engine,profile)
        self.last_reason='Waiting for sufficient settled Favorites evidence'
        self._decision_signatures={};self._statistics_groups=None;self._statistics_groups_at=-1e9
    def entry_quote(self,ticker,side,max_price=None):
        q,decision=statistics_quote(self.e,self.profile,self.contracts,ticker,side,self._source_cells(),max_price,self.statistics_groups())
        decision=dict(decision,ticker=ticker,side=side,policy='favorites-statistics-v1',traded=bool(q))
        self.decisions[ticker]=decision
        signature=json.dumps({k:decision.get(k) for k in ('reason','level','samples','price','side','expected_roi')},sort_keys=True)
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
