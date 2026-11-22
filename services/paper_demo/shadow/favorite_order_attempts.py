"""Bounded, restart-durable paper BUY order-submission counts for regular Favorites.

Each distinct submitted maker BUY order is one attempt, including still-open
orders and those later cancelled/expired/filled. Rejects, fills and observed
opportunities are NOT submissions. All-time only covers telemetry since the
tracker was first installed; historic orders cannot be reconstructed safely.
No DB/R2/provider reads and no raw order IDs in dashboard reports.
"""
from collections import OrderedDict
from math import isfinite

from .favorite_filled_events import category_for
from .performance import WINDOWS

MAX_TRACKED_ATTEMPTS = 6000
PERIODS = dict(all=None, **WINDOWS)


def _valid_time(value, *, max_time=None):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and isfinite(value) and value > 0
            and (max_time is None or value <= max_time + 1))


class FavoriteOrderAttempts:
    """Track unique submitted maker BUY order IDs; cap recent exact timestamps."""

    def __init__(self, state=None, now=0):
        data = state if isinstance(state, dict) else {}
        now = float(now)
        began = data.get('started_at')
        self.started_at = float(began) if _valid_time(began, max_time=now) else now
        self.pruned_through = float(data.get('pruned_through')) if _valid_time(
            data.get('pruned_through'), max_time=now) else 0.
        self.unknown_after = float(data.get('unknown_after')) if _valid_time(
            data.get('unknown_after'), max_time=now) else 0.
        n = data.get('unknown_attempts')
        self.unknown_attempts = n if type(n) is int and 0 <= n <= 1000000000 else 0
        self.cumulative = {}
        for bot, count in (data.get('cumulative') or {}).items() if isinstance(
                data.get('cumulative'), dict) else ():
            if isinstance(bot, str) and 1 <= len(bot) <= 40 and type(count) is int and 0 <= count <= 1000000000:
                self.cumulative[bot] = count
        self.recent = OrderedDict()
        records = data.get('recent')
        for item in records if isinstance(records, list) else []:
            if not isinstance(item, list) or len(item) != 3:
                continue
            bot, ident, at = item
            if (not isinstance(bot, str) or not 1 <= len(bot) <= 40
                    or not isinstance(ident, str) or not 1 <= len(ident) <= 150
                    or not _valid_time(at, max_time=now)):
                continue
            key = (bot, ident)
            self.recent.pop(key, None)
            self.recent[key] = float(at)
            if len(self.recent) > MAX_TRACKED_ATTEMPTS:
                _, dropped = self.recent.popitem(last=False)
                self.pruned_through = max(self.pruned_through, dropped)

    def observe(self, order, at, market):
        if getattr(order, 'action', None) != 'buy' or getattr(order, 'maker', False) is not True:
            return
        if not _valid_time(at):
            return
        market = market if isinstance(market, dict) else {}
        bot, ident = market.get('bot_id'), getattr(order, 'id', None)
        if (not isinstance(bot, str) or not 1 <= len(bot) <= 40
                or not isinstance(ident, str) or not 1 <= len(ident) <= 150):
            self.unknown_attempts += 1
            self.unknown_after = max(self.unknown_after, float(at))
            return
        key = (bot, ident)
        if key in self.recent:
            return
        self.recent[key] = float(at)
        self.cumulative[bot] = self.cumulative.get(bot, 0) + 1
        if len(self.recent) > MAX_TRACKED_ATTEMPTS:
            _, dropped = self.recent.popitem(last=False)
            self.pruned_through = max(self.pruned_through, dropped)

    def export(self):
        return dict(started_at=self.started_at, pruned_through=self.pruned_through,
                    unknown_after=self.unknown_after,
                    unknown_attempts=self.unknown_attempts,
                    cumulative=dict(self.cumulative),
                    recent=[[bot, ident, at] for (bot, ident), at in self.recent.items()])

    def report(self, now, profiles):
        """All-time is a tracked lower bound; rolling windows exact if complete.

        Do not divide attempts by distinct filled events: submissions and venue
        events are different units, and their entry times may be in different
        reporting windows.
        """
        now = float(now)
        profiles_by_id = {
            str(p['id']): p for p in profiles
            if isinstance(p, dict) and p.get('id') is not None
        }
        per_bot = {bot: {period: 0 for period in PERIODS} for bot in profiles_by_id}
        by_category = {
            category_for(p): {period: 0 for period in PERIODS}
            for p in profiles_by_id.values()
        }
        combined = {period: 0 for period in PERIODS}
        for bot, count in self.cumulative.items():
            if bot not in profiles_by_id:
                continue
            category = category_for(profiles_by_id[bot])
            per_bot[bot]['all'] += count
            by_category[category]['all'] += count
            combined['all'] += count
        for (bot, _), at in self.recent.items():
            if bot not in profiles_by_id or not self.started_at <= at <= now:
                continue
            category = category_for(profiles_by_id[bot])
            for period, seconds in PERIODS.items():
                if seconds is None or at < now - seconds:
                    continue
                per_bot[bot][period] += 1
                by_category[category][period] += 1
                combined[period] += 1

        def format_windows(values):
            return {period: dict(
                count=count,
                complete=bool(seconds is not None and now - seconds >= max(
                    self.started_at, self.pruned_through, self.unknown_after)),
                started_at=self.started_at)
                for period, count in values.items()
                for seconds in (PERIODS[period],)}

        return dict(total=format_windows(combined),
                    by_bot={bot: format_windows(w) for bot, w in per_bot.items()},
                    by_category={category: format_windows(w) for category, w in by_category.items()},
                    unknown_submissions=self.unknown_attempts)
