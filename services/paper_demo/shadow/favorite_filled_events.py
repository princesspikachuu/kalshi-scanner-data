"""Bounded observed BUY-FILL event counts for regular High-Probability Favorites.

Never count contracts, maker bids, rejected orders, or settlement alone as
new windowed fills. Store one last actual buy-fill timestamp per bot/event.
All-time is a conservative lower bound: historic *settled* event IDs in the
existing research plus fills observed by this tracker. Older unsettled fills
cannot be dated retroactively. No additional database or R2 reads.
"""
from collections import OrderedDict
from math import isfinite
from .performance import WINDOWS

MAX_TRACKED_EVENTS = 12000
PERIODS = dict(all=None, **WINDOWS)


def category_for(profile):
    """Match the regular Favorites market category names in the dashboard."""
    import re
    asset = profile.get('asset')
    series = str(profile.get('series') or '').upper()
    if asset == 'weather': return 'weather-hourly'
    if asset == 'weather_daily': return 'weather-daily'
    if asset == 'sports': return 'sports'
    duration = '15m' if series.endswith('15M') else 'hourly' if asset == 'hourly' else ''
    if re.fullmatch(r'KX(BTC|ETH|SOL|XRP|DOGE|BNB|HYPE|ZEC|NEAR)(15M|D|H)?', series):
        kind = 'crypto'
    elif re.fullmatch(r'KX(GOLD|SILVER|PLATINUM|PALLADIUM|COPPER|WTI|NATGAS|BRENT)(15M|H|D)?', series):
        kind = 'commodities'
    elif re.fullmatch(r'KX(USDCAD|AUDUSD|USDJPY|GBPUSD|EURUSD|2YRRATE|5YRRATE|10YRRATE|30YRRATE|INX|NDQ|NASDAQ100)(15M|AH|H|U|D)?', series):
        kind = 'finance'
    else:
        kind = 'other'
    return kind + ('-' + duration if duration else '')


class FavoriteFilledEvents:
    def __init__(self, state=None, now=0):
        data = state if isinstance(state, dict) else {}
        now = float(now)
        started = data.get('started_at')
        self.started_at = float(started) if isinstance(started, (int, float)) and isfinite(started) and 0 < started <= now else now
        self.events = OrderedDict()
        self.pruned_through = float(data.get('pruned_through', 0) or 0)
        self.unknown_after = float(data.get('unknown_after', 0) or 0)
        self.unknown_fills = int(data.get('unknown_fills', 0) or 0)
        for item in data.get('events', []):
            if not isinstance(item, list) or len(item) != 3: continue
            bot, event, at = item
            if (not isinstance(bot, str) or not 1 <= len(bot) <= 40
                    or not isinstance(event, str) or not 1 <= len(event) <= 150
                    or isinstance(at, bool) or not isinstance(at, (int, float))
                    or not isfinite(at) or at <= 0 or at > now + 1): continue
            key = (bot, event)
            self.events.pop(key, None)
            self.events[key] = float(at)
            if len(self.events) > MAX_TRACKED_EVENTS:
                (_, _), evicted = self.events.popitem(last=False)
                self.pruned_through = max(self.pruned_through, evicted)

    def observe(self, order, at, market):
        if getattr(order, 'action', None) != 'buy': return
        if not isinstance(at, (int, float)) or not isfinite(at) or at <= 0: return
        market = market if isinstance(market, dict) else {}
        bot, event = market.get('bot_id'), market.get('event_ticker')
        if (not isinstance(bot, str) or not 1 <= len(bot) <= 40
                or not isinstance(event, str) or not 1 <= len(event) <= 150):
            self.unknown_fills += 1
            self.unknown_after = max(self.unknown_after, float(at))
            return
        key = (bot, event)
        self.events.pop(key, None)
        self.events[key] = float(at)
        if len(self.events) > MAX_TRACKED_EVENTS:
            _, evicted = self.events.popitem(last=False)
            self.pruned_through = max(self.pruned_through, evicted)

    def export(self):
        return dict(started_at=self.started_at,
            events=[[bot, event, at] for (bot, event), at in self.events.items()],
            pruned_through=self.pruned_through, unknown_after=self.unknown_after,
            unknown_fills=self.unknown_fills)

    def report(self, now, profiles, historical_settled=None):
        """Counts are distinct event IDs *per selected window*, across filled orders.

        Historical settled IDs have no supported original fill timestamps and
        are used ONLY for the all-time lower bound. For rolling windows, a new
        tracker cannot claim complete coverage until its entire period elapsed.
        """
        now = float(now)
        historical_settled = historical_settled if isinstance(historical_settled, dict) else {}
        profiles_by_id = {str(p['id']): p for p in profiles if isinstance(p, dict)
                          and p.get('id') is not None}
        per_bot = {bot: {period: set() for period in PERIODS} for bot in profiles_by_id}
        categories = {category_for(p) for p in profiles_by_id.values()}
        by_category = {category: {period: set() for period in PERIODS} for category in categories}
        combined = {period: set() for period in PERIODS}
        for (bot, event), at in self.events.items():
            if bot not in profiles_by_id or not self.started_at <= at <= now: continue
            category = category_for(profiles_by_id[bot])
            for period, seconds in PERIODS.items():
                if seconds is not None and at < now - seconds: continue
                per_bot[bot][period].add(event)
                by_category[category][period].add(event)
                combined[period].add(event)
        for bot, events in historical_settled.items():
            if bot not in profiles_by_id or not isinstance(events, (set, frozenset)):
                continue
            category = category_for(profiles_by_id[bot])
            for event in events:
                if not isinstance(event, str) or not event: continue
                per_bot[bot]['all'].add(event)
                by_category[category]['all'].add(event)
                combined['all'].add(event)
        def summarize(groups):
            return {key: {period: dict(
                count=len(events),
                complete=bool(seconds is not None
                    and now - seconds >= max(self.started_at, self.pruned_through, self.unknown_after)),
                started_at=self.started_at,
            ) for (period, seconds), events in
                ((period, PERIODS[period], values) for period, values in windows.items())}
                for key, windows in groups.items()}
        # Fully bounded, ID-free dashboard summaries.
        def one(windows):
            result = {}
            for period, events in windows.items():
                seconds = PERIODS[period]
                result[period] = dict(count=len(events),
                    complete=bool(seconds is not None
                        and now - seconds >= max(self.started_at, self.pruned_through, self.unknown_after)),
                    started_at=self.started_at)
            return result
        return dict(total=one(combined),
                    by_bot={key: one(windows) for key, windows in per_bot.items()},
                    by_category={key: one(windows) for key, windows in by_category.items()},
                    unknown_fill_events=self.unknown_fills)
