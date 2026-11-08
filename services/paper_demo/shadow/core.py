"""Deterministic, data-only shadow execution. No exchange account mutation exists here."""
from __future__ import annotations
from collections import deque
from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_CEILING, InvalidOperation
import csv
import heapq
import json
import math
import os
from pathlib import Path
import random
import sqlite3
import statistics
from typing import Callable

D = Decimal
ZERO = D(0)


def phase_at(close: float, now: float) -> int:
    elapsed = now - close + 900
    return 0 if elapsed < 0 else 4 if now >= close else 1 if elapsed < 601 else 2 if elapsed < 781 else 3


@dataclass(frozen=True)
class FeePolicy:
    taker_multiplier: D = D(1)
    maker_multiplier: D = D(0)

    @classmethod
    def from_series(cls, series: dict):
        kind = series['fee_type']
        multiplier = D(str(series['fee_multiplier']))
        if kind not in ('quadratic', 'quadratic_with_maker_fees') or multiplier < 0:
            raise ValueError('Unsupported fee schedule; supply a verified policy, not an assumed fee')
        return cls(multiplier, multiplier if kind == 'quadratic_with_maker_fees' else ZERO)

    def charge(self, quantity: D, price: D, maker: bool = False) -> D:
        rate = D('.0175') * self.maker_multiplier if maker else D('.07') * self.taker_multiplier
        raw = rate * quantity * price * (1-price)
        # Current published rule: round fee + position cost up to a centicent.
        cost = quantity * price
        return (cost + raw).quantize(D('.0001'), rounding=ROUND_CEILING) - cost if rate else ZERO


class PriceLevels(dict):
    """Depth map with an incrementally maintained best bid."""
    def __init__(self,values=()):
        super().__init__(values);self.best=max(self,default=None);self._ordered=None
    def __setitem__(self,key,value):
        if key not in self:self._ordered=None
        super().__setitem__(key,value)
        if self.best is None or key>self.best:self.best=key
    def __delitem__(self,key):
        super().__delitem__(key);self._ordered=None
        if key==self.best:self.best=max(self,default=None)
    def pop(self,key,*default):
        exists=key in self;value=super().pop(key,*default)
        if exists:self._ordered=None
        if key==self.best:self.best=max(self,default=None)
        return value
    def popitem(self):
        key,value=super().popitem();self._ordered=None
        if key==self.best:self.best=max(self,default=None)
        return key,value
    def clear(self):super().clear();self.best=None;self._ordered=None
    def ordered_prices(self):
        if self._ordered is None:self._ordered=tuple(sorted(self,reverse=True))
        return self._ordered
    def update(self,values=(),**kwargs):
        for key,value in dict(values,**kwargs).items():self[key]=value
    def setdefault(self,key,default=None):
        if key not in self:self[key]=default
        return self[key]
    def __ior__(self,values):self.update(values);return self


class Book:
    def __init__(self):
        self.levels = {'yes': {}, 'no': {}}
        self.seq = None
        self.sid = None
        self.valid = False
        self.at = 0.0
        self.snapshot_at = 0.0
        self.used = {'yes': {}, 'no': {}}

    @property
    def levels(self):return self._levels

    @levels.setter
    def levels(self,value):
        self._levels={side:values if isinstance(values,PriceLevels) else PriceLevels(values) for side,values in value.items()}

    def apply(self, event: dict, now: float):
        msg = event['msg']
        if event['type'] == 'orderbook_snapshot':
            levels={'yes':{},'no':{}}
            try:
                for side in ('yes','no'):
                    for raw_price,raw_quantity in msg.get(side+'_dollars_fp',[]):
                        price,quantity=D(raw_price),D(raw_quantity)
                        if not price.is_finite() or not ZERO<price<1 or not quantity.is_finite() or quantity<0:
                            raise ValueError('invalid binary book level')
                        if quantity:levels[side][price]=quantity
            except (InvalidOperation,ValueError,TypeError,KeyError):
                self.valid=False
                raise ValueError('invalid binary book level') from None
            self.levels=levels
            self.used={side:{p:q for p,q in self.used[side].items() if p in levels[side]} for side in ('yes','no')}
            self.valid=True
            self.snapshot_at=now
        else:
            if not self.valid or self.seq is None or event.get('sid')!=self.sid or event.get('seq')!=self.seq+1:
                self.valid=False
                raise ValueError('book sequence gap')
            try:
                side,price,delta=msg['side'],D(msg['price_dollars']),D(msg['delta_fp'])
                if side not in ('yes','no') or not price.is_finite() or not ZERO<price<1 or not delta.is_finite():
                    raise ValueError('invalid binary book level')
                quantity=self.levels[side].get(price,ZERO)+delta
                if not quantity.is_finite():raise ValueError('invalid binary book level')
            except (InvalidOperation,ValueError,TypeError,KeyError):
                self.valid=False
                raise ValueError('invalid binary book level') from None
            if quantity<0:
                self.valid=False
                raise ValueError('negative depth')
            if quantity:self.levels[side][price]=quantity
            else:
                self.levels[side].pop(price,None)
                self.used[side].pop(price,None)
            # All unchanged levels were already validated by their snapshot or
            # previous delta. Rechecking the entire depth on each tick is quadratic.
        self.seq,self.sid,self.at=event['seq'],event['sid'],now
        yes,no=self.bid('yes'),self.bid('no')
        if yes is not None and no is not None and yes+no>1:
            self.valid=False
            raise ValueError('crossed complementary book')

    def bid(self, side: str) -> D | None:
        levels=self.levels[side]
        if not isinstance(levels,PriceLevels):
            levels=self.levels[side]=PriceLevels(levels)
        return levels.best

    def ask(self, side: str) -> D | None:
        bid = self.bid('no' if side == 'yes' else 'yes')
        return 1-bid if bid is not None else None

    def iter_depth(self,side:str,action:str):
        book_side=side if action=='sell' else 'no' if side=='yes' else 'yes'
        levels=self.levels[book_side]
        if not isinstance(levels,PriceLevels):
            levels=self.levels[book_side]=PriceLevels(levels)
        # Quantity changes do not change price ordering. Calculate the shadow
        # overlay only for levels the caller actually needs.
        best=levels.best
        if best is None:return
        yield (best if action=='sell' else 1-best),max(ZERO,levels[best]-self.used[book_side].get(best,ZERO))
        for price in levels.ordered_prices():
            if price==best:continue
            yield (price if action=='sell' else 1-price),max(ZERO,levels[price]-self.used[book_side].get(price,ZERO))

    def depth(self,side:str,action:str):return list(self.iter_depth(side,action))

    def consume(self, side: str, action: str, price: D, quantity: D):
        book_side, level = (side, price) if action == 'sell' else (
            'no' if side == 'yes' else 'yes', 1-price)
        self.used[book_side][level] = self.used[book_side].get(level, ZERO) + quantity


@dataclass
class Lot:
    id: str
    ticker: str
    side: str
    quantity: D
    price: D
    entry_fee: D
    phase_origin: int
    is_armed: bool = False
    exit_requested: bool = False
    acquired_at: float = 0.0
    recovery_cost: D = ZERO
    recovery_proceeds: D = ZERO


@dataclass
class Stats:
    gross: D = ZERO
    fees_paid: D = ZERO
    realized_fees: D = ZERO
    closed: D = ZERO
    won: D = ZERO
    taker_slippage: D = ZERO
    taker_quantity: D = ZERO
    taker_orders: int = 0
    taker_order_slippage: D = ZERO
    taker_slippage_square: D = ZERO
    stress_fills: D = ZERO
    valid: bool = True
    maker_requested: D = ZERO
    maker_filled: D = ZERO
    taker_requested: D = ZERO
    ioc_unfilled: D = ZERO
    profit_contracts: D = ZERO
    profit_proceeds: D = ZERO
    execution_orders: int = 0
    rejected_orders: int = 0
    ioc_attempts: int = 0
    partial_iocs: int = 0
    execution_measured: bool = False


class Wallet:
    def __init__(self, cash: D):
        self.cash = cash
        self.lots: list[Lot] = []
        self.stats: dict[str, Stats] = {}
        self.deposits = cash

    def stat(self, ticker: str) -> Stats:
        return self.stats.setdefault(ticker, Stats())

    def inventory(self, ticker: str, side: str) -> D:
        return sum((l.quantity for l in self.lots if l.ticker == ticker and l.side == side), ZERO)

    def fill(self, ticker: str, side: str, action: str, quantity: D, price: D,
             fee: D, origin: int, ident: str, targets: list[str] | None = None,
             acquired_at: float = 0.0):
        if (quantity <= 0 or not quantity.is_finite() or not price.is_finite() or
                not ZERO <= price <= 1 or not fee.is_finite() or fee < 0):
            raise ValueError('invalid virtual execution')
        if action == 'buy' and quantity*price + fee > self.cash:
            raise ValueError('insufficient virtual cash')
        if action == 'sell' and sum((l.quantity for l in self.lots if l.ticker == ticker and
                l.side == side and (targets is None or l.id in targets)), ZERO) < quantity:
            raise ValueError('virtual exit exceeds targeted inventory')
        stat = self.stat(ticker)
        stat.fees_paid += fee
        if action == 'buy':
            self.cash -= quantity*price + fee
            opposite = 'no' if side == 'yes' else 'yes'
            # Opposite buys release complete-set collateral and realize the old leg.
            remaining, fee_left = quantity, fee
            for lot in list(self.lots):
                if lot.ticker == ticker and lot.side == opposite and remaining:
                    take = min(remaining, lot.quantity)
                    allocated = fee*take/quantity
                    # Collateral released by netting closes that fraction's risk.
                    fraction=(lot.quantity-take)/lot.quantity
                    lot.recovery_cost*=fraction
                    lot.recovery_proceeds*=fraction
                    self._close(lot, take, 1-price, allocated)
                    self.cash += take
                    remaining -= take
                    fee_left -= allocated
            if remaining:
                self.lots.append(Lot(ident, ticker, side, remaining, price, fee_left, origin,
                                     acquired_at=acquired_at,recovery_cost=remaining*price+fee_left))
        else:
            eligible = [l for l in self.lots if l.ticker == ticker and l.side == side and
                        (targets is None or l.id in targets)]
            if sum((l.quantity for l in eligible), ZERO) < quantity:
                raise ValueError('virtual exit exceeds targeted inventory')
            self.cash += quantity*price-fee
            remaining = quantity
            for lot in eligible:
                take = min(remaining, lot.quantity)
                if take:
                    self._close(lot, take, price, fee*take/quantity)
                    remaining -= take
        self.lots = [l for l in self.lots if l.quantity]

    def _close(self, lot: Lot, quantity: D, exit_price: D, exit_fee: D):
        stat = self.stat(lot.ticker)
        entry_fee = lot.entry_fee*quantity/lot.quantity
        gross = quantity*(exit_price-lot.price)
        stat.gross += gross
        stat.realized_fees += entry_fee + exit_fee
        stat.closed += quantity
        stat.won += quantity if gross-entry_fee-exit_fee > 0 else ZERO
        lot.quantity -= quantity
        lot.entry_fee -= entry_fee

    def settle(self, ticker: str, yes_payout: D):
        if not yes_payout.is_finite() or not ZERO <= yes_payout <= 1:
            raise ValueError('invalid settlement payout')
        for lot in list(self.lots):
            if lot.ticker == ticker:
                payout = yes_payout if lot.side == 'yes' else 1-yes_payout
                self.cash += lot.quantity*payout
                self._close(lot, lot.quantity, payout, ZERO)
        self.lots = [l for l in self.lots if l.quantity]


@dataclass
class Order:
    id: str
    ticker: str
    side: str
    action: str
    quantity: D
    price: D
    maker: bool
    phase: int
    created: float
    arrives: float
    expiry: float
    reference: D | None
    targets: list[str] | None = None
    status: str = 'pending'
    remaining: D = ZERO
    ahead: D = ZERO
    reserved: D = ZERO
    stress_episode: int = -1
    opposing_fill_race: bool = False
    purpose: str = 'strategy'
    decision_at: float = 0.0
    worker_delay_seconds: float = 0.0
    transport_latency_seconds: float = 0.0
    execution_model: str = 'fixed-latency-v1'


class Audit:
    columns = ['sequence', 'time', 'event', 'ticker', 'order_id', 'side', 'action',
               'quantity', 'price', 'fee', 'reference', 'slippage', 'reason',
               'queue_ahead', 'cash', 'details']
    def __init__(self, directory: str):
        self.path = Path(directory)
        self.path.mkdir(parents=True, exist_ok=True)
        if any(self.path.iterdir()):
            raise ValueError('Output directory must be new or empty; existing runs are preserved')
        claim = os.open(self.path/'.run-claimed', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        os.close(claim)
        self.db = sqlite3.connect(self.path/'ledger.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, payload TEXT)')
        if self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]:
            raise ValueError('Output contains an existing run; replay it into a fresh directory')
        self.db.execute('CREATE TABLE IF NOT EXISTS wallet (id INTEGER PRIMARY KEY, payload TEXT)')
        self.csv_file = open(self.path/'events.csv', 'w', newline='')
        self.csv = csv.DictWriter(self.csv_file, self.columns)
        self.csv.writeheader()
        self.seq = 0

    def log(self, now: float, kind: str, wallet: Wallet, **fields):
        self.seq += 1
        row = dict.fromkeys(self.columns, '')
        row.update(sequence=self.seq, time=f'{now:.6f}', event=kind, cash=str(wallet.cash), **fields)
        row = {k: str(v) for k,v in row.items()}
        payload = json.dumps({'cash': str(wallet.cash), 'deposits': str(wallet.deposits),
                              'lots': [asdict(l) for l in wallet.lots],
                              'stats': {k: asdict(v) for k,v in wallet.stats.items()}}, default=str)
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?)', (self.seq, json.dumps(row)))
            self.db.execute('INSERT OR REPLACE INTO wallet VALUES (1,?)', (payload,))
        self.csv.writerow(row)
        self.csv_file.flush()

    def close(self):
        self.csv_file.close()
        self.db.close()


class Spot:
    def __init__(self):
        self.samples, self.low, self.high = deque(), deque(), deque()
        self.second = -1
        self.at = 0.0
        self.episode = 0
        self.toxic_until = {'yes': 0.0, 'no': 0.0}
        self.last_event = 0.0
        self.spike = False

    def add(self, price: float, event_time: float, now: float):
        self.spike = False
        if price <= 0 or not math.isfinite(price) or abs(now-event_time) > 3:
            raise ValueError('invalid/stale spot')
        if event_time < self.last_event:
            return
        self.last_event, self.at = event_time, now
        while self.samples and self.samples[0][0] < event_time-60:
            self.samples.popleft()
        for window in (self.low, self.high):
            while window and window[0][0] < event_time-10:
                window.popleft()
        if self.ready(now) and self.low:
            sigma = statistics.pstdev(p for _,p in self.samples)
            self.spike = max(abs(price-self.high[0][1]), abs(price-self.low[0][1])) > 2.5*sigma
            against_yes = self.high[0][1]-price > 2*sigma
            against_no = price-self.low[0][1] > 2*sigma
            for side, adverse in (('yes', against_yes), ('no', against_no)):
                if adverse and now >= self.toxic_until[side]:
                    self.episode += 1
                    self.toxic_until[side] = now+2
        if int(event_time) != self.second:
            self.samples.append((event_time, price))
            self.second = int(event_time)
        while self.low and self.low[-1][1] >= price:
            self.low.pop()
        while self.high and self.high[-1][1] <= price:
            self.high.pop()
        self.low.append((event_time, price))
        self.high.append((event_time, price))

    def ready(self, now: float):
        return (len(self.samples) >= 50 and self.samples[-1][0]-self.samples[0][0] >= 55
                and now-self.at <= 3)


class Engine:
    def __init__(self, audit: Audit, cash='50', latency_ms=150, seed=7,
                 toxic_fill_probability=.35, stale_seconds=3):
        if latency_ms < 0 or not 0 <= toxic_fill_probability <= 1 or D(cash) < 0:
            raise ValueError('invalid simulation configuration')
        self.audit, self.wallet = audit, Wallet(D(cash))
        self.latency = latency_ms/1000
        self.rng = random.Random(seed)
        self.toxic_probability, self.stale_seconds = toxic_fill_probability, stale_seconds
        self.books: dict[str,Book] = {}
        self.markets: dict[str,dict] = {}
        self.fees: dict[str,FeePolicy] = {}
        self.orders: dict[str,Order] = {}
        self.pending = []
        self.serial, self.now = 0, 0.0
        self.trade_ids = set()
        self.sequences = {}
        self.spot = Spot()
        self.fill_callback: Callable[[Order,D],None] | None = None
        self.closed_reports, self.settled = set(), set()
        self.strategy = None
        self.gap_reasons = {}
        self.safety_until = 0.0
        self.book_feed_at = {}
        self.wall_clock = None

    def book_fresh(self,ticker):
        book=self.books[ticker]
        return book.valid and self.now-max(book.at,self.book_feed_at.get(book.sid,0))<=self.stale_seconds

    def log(self, kind: str, order: Order | None = None, **fields):
        if order:
            fields = dict(ticker=order.ticker, order_id=order.id, side=order.side,
                          action=order.action, queue_ahead=order.ahead, **fields)
        self.audit.log(self.now, kind, self.wallet, **fields)

    def refill(self, amount: D):
        if not amount.is_finite() or amount <= 0:
            raise ValueError('refill must be positive')
        self.wallet.cash += amount
        self.wallet.deposits += amount
        self.log('REFILL', quantity=amount)

    def add_market(self, market: dict, fees: FeePolicy):
        ticker = market['ticker']
        if ticker not in self.markets:
            self.markets[ticker] = market
            self.books[ticker] = Book()
        self.fees[ticker] = fees
        self.log('MARKET', ticker=ticker, details=json.dumps(market))

    def available(self):
        return self.wallet.cash-sum((o.reserved for o in self.orders.values()
                                    if o.status in ('pending','resting')), ZERO)

    def request_timing(self):
        decision=max(self.now,self.wall_clock()) if self.wall_clock else self.now
        return dict(decision_at=decision,worker_delay_seconds=decision-self.now,
            transport_latency_seconds=self.latency,
            execution_model='worker-delay-v1' if self.wall_clock else 'fixed-latency-v1')

    def place(self, ticker: str, side: str, action: str, quantity: D, price: D,
              maker=True, phase=1, expiry=None, targets=None, purpose='strategy') -> str:
        quantity, price = D(quantity), D(price)
        if (side not in ('yes','no') or action not in ('buy','sell') or quantity <= 0 or
                not quantity.is_finite() or not ZERO < price < 1):
            raise ValueError('invalid virtual order')
        if maker and action != 'buy' and not getattr(self,'covered_maker_sells',False):
            raise ValueError('maker engine currently supports strategy entry buys only')
        market = self.markets[ticker]
        self.serial += 1
        ident = f'S{self.serial:09d}'
        book = self.books[ticker]
        reference = book.bid(side) if action == 'sell' else book.ask(side)
        timing=self.request_timing()
        order = Order(ident, ticker, side, action, quantity, price, maker, phase,
                      self.now, timing['decision_at']+self.latency, expiry or market['close'], reference,
                      targets=targets, remaining=quantity,purpose=purpose,**timing)
        stat=self.wallet.stat(ticker)
        stat.execution_measured=True
        stat.execution_orders+=1
        if maker:stat.maker_requested+=quantity
        else:stat.taker_requested+=quantity
        if action == 'buy':
            order.reserved = quantity*price+self.fees[ticker].charge(quantity, price, maker)
            if order.reserved > self.available():
                order.status, order.reserved = 'rejected', ZERO
                stat.rejected_orders+=1
        self.orders[ident] = order
        if order.status == 'pending':
            heapq.heappush(self.pending, (order.arrives, self.serial, 'arrive', ident))
        self.log('ORDER_SUBMITTED' if order.status == 'pending' else 'ORDER_REJECTED', order,
                 quantity=quantity, price=price, reference=reference, reason='latency scheduled',details=json.dumps(timing))
        return ident

    def cancel(self, ident: str):
        order = self.orders[ident]
        if order.status in ('pending','resting') and not any(
                action=='cancel' and target==ident for _,_,action,target in self.pending):
            self.serial += 1
            timing=self.request_timing()
            heapq.heappush(self.pending, (timing['decision_at']+self.latency, self.serial, 'cancel', ident))
            self.log('CANCEL_SUBMITTED', order,details=json.dumps(timing))

    def cancel_buys(self, ticker: str):
        for order in self.orders.values():
            if order.ticker == ticker and order.maker:
                self.cancel(order.id)

    def prune_terminal_orders(self):
        # The durable journal owns history. Completed/cancelled orders are not
        # execution state, unless a delayed action still refers to their ID.
        referenced={item[3] for item in self.pending}
        self.orders={ident:o for ident,o in self.orders.items()
                     if o.status in ('pending','resting') or ident in referenced}
        if hasattr(self,'_recent_fills'):
            self._recent_fills={ident:rows for ident,rows in self._recent_fills.items()
                                if ident in self.orders}

    def advance(self, now: float):
        if now < self.now:
            raise ValueError('non-monotonic replay clock')
        while self.pending and self.pending[0][0] <= now:
            at, _, action, ident = heapq.heappop(self.pending)
            self.now = at
            self.expire()
            order = self.orders[ident]
            if order.status not in ('pending','resting'):
                continue
            if action == 'cancel':
                order.status, order.reserved = 'cancelled', ZERO
                self.log('CANCELLED', order)
            elif order.status == 'pending':
                self.arrive(order)
        self.now = now
        self.expire()

    def expire(self):
        for order in self.orders.values():
            if order.status in ('pending','resting') and self.now >= order.expiry:
                order.status, order.reserved = 'expired', ZERO
                self.log('EXPIRED', order)

    def arrive(self, order: Order):
        book = self.books[order.ticker]
        market = self.markets[order.ticker]
        if (not self.book_fresh(order.ticker) or
                self.now >= market['close'] or order.ticker in self.settled):
            order.status, order.reserved = 'rejected', ZERO
            self.wallet.stat(order.ticker).rejected_orders+=1
            self.log('ORDER_REJECTED', order, reason='stale/missing/closed book')
            return
        if not order.maker and self.strategy and not self.strategy.exit_allowed(order):
            order.status = 'cancelled'
            self.log('CANCELLED', order, reason='freeze at delayed arrival')
            return
        if order.maker:
            ask = book.ask(order.side)
            if ask is not None and order.price >= ask:
                order.status, order.reserved = 'rejected', ZERO
                self.wallet.stat(order.ticker).rejected_orders+=1
                self.log('ORDER_REJECTED', order, reason='post-only would cross at arrival')
                return
            order.ahead = book.levels[order.side].get(order.price, ZERO) + sum((
                o.remaining for o in self.orders.values() if o.id != order.id and
                o.ticker == order.ticker and o.side == order.side and o.price == order.price and
                o.status == 'resting'), ZERO)
            order.status = 'resting'
            self.log('MAKER_RESTING', order, quantity=order.remaining, price=order.price)
        else:
            self.sweep(order)

    def sweep(self, order: Order):
        book = self.books[order.ticker]
        target_qty = sum((l.quantity for l in self.wallet.lots if l.ticker == order.ticker and
            l.side == order.side and (order.targets is None or l.id in order.targets)), ZERO)
        budget = min(order.remaining, target_qty) if order.action == 'sell' else order.remaining
        total, slippage = ZERO, ZERO
        for price, depth in book.iter_depth(order.side, order.action):
            if budget <= 0:
                break
            if (order.action == 'sell' and price < order.price or
                    order.action == 'buy' and price > order.price):
                break
            take = min(budget, depth)
            if take:
                # Hypothetical depth use is an overlay, never a mutation to the public book.
                book.consume(order.side, order.action, price, take)
                reference = order.reference if order.reference is not None else price
                slip = take*(reference-price if order.action == 'sell' else price-reference)
                self.fill(order, take, price, 'DEPTH_SWEEP', slip)
                total, budget, slippage = total+take, budget-take, slippage+slip
        order.status, order.reserved = 'filled' if order.remaining == 0 else 'ioc_cancelled', ZERO
        stat=self.wallet.stat(order.ticker)
        stat.ioc_attempts+=1
        stat.ioc_unfilled+=order.remaining
        stat.partial_iocs+=int(total>0 and order.remaining>0)
        if total:
            stat = self.wallet.stat(order.ticker)
            stat.taker_orders += 1
            stat.taker_order_slippage += slippage/total
            stat.taker_slippage_square += (slippage/total)**2
        self.log('IOC_COMPLETE', order, quantity=total, slippage=slippage,
                 details=json.dumps({'unfilled': str(order.remaining),
                                     'vwap': str(sum((D(x['quantity'])*D(x['price']) for x in
                                           getattr(self, '_recent_fills', {}).get(order.id, [])), ZERO)/total)
                                              if total else None}))

    def fill(self, order: Order, quantity: D, price: D, reason: str, slippage=ZERO):
        fee = self.fees[order.ticker].charge(quantity, price, order.maker)
        # Record net cash actually recovered, including each executed layer's fee.
        # Targets use the same FIFO allocation as Wallet.fill; quotes are never proceeds.
        if order.purpose=='partial_profit' and order.action=='sell':
            left=quantity
            for lot in self.wallet.lots:
                if lot.ticker==order.ticker and lot.side==order.side and (order.targets is None or lot.id in order.targets):
                    take=min(left,lot.quantity)
                    lot.recovery_proceeds+=take*price-fee*take/quantity
                    left-=take
                    if not left:break
            stat=self.wallet.stat(order.ticker)
            stat.profit_contracts+=quantity
            stat.profit_proceeds+=quantity*price-fee
        order.opposing_fill_race = (order.maker and self.wallet.inventory(order.ticker,
                                   'no' if order.side == 'yes' else 'yes') > 0)
        self.wallet.fill(order.ticker, order.side, order.action, quantity, price, fee,
                         order.phase, f'{order.id}:{order.remaining}', order.targets,acquired_at=self.now)
        order.remaining -= quantity
        if order.maker and order.action=='buy':
            order.reserved = (order.remaining*order.price+
                              self.fees[order.ticker].charge(order.remaining, order.price, True))
        stat = self.wallet.stat(order.ticker)
        if order.maker:stat.maker_filled+=quantity
        if not order.maker:
            stat.taker_slippage += slippage
            stat.taker_quantity += quantity
        if reason == 'ADVERSE_SELECTION_STRESS':
            stat.stress_fills += quantity
        if not hasattr(self, '_recent_fills'):
            self._recent_fills = {}
        self._recent_fills.setdefault(order.id, []).append({'quantity':str(quantity), 'price':str(price)})
        if not order.remaining:
            order.status, order.reserved = 'filled', ZERO
        self.log('FILL', order, quantity=quantity, price=price, fee=fee,
                 reference=order.reference, slippage=slippage, reason=reason,
                 details=json.dumps(dict(purpose=order.purpose,latency_ms=order.transport_latency_seconds*1000,
                     worker_delay_ms=order.worker_delay_seconds*1000,decision_at=order.decision_at,
                     arrival_at=order.arrives,execution_model=order.execution_model)))
        if self.fill_callback:
            self.fill_callback(order, quantity)

    def trade(self, ticker: str, trade: dict):
        if ticker in self.settled:
            return
        ident = (ticker, trade['trade_id'])
        if ident in self.trade_ids or trade.get('is_block_trade'):
            return
        self.trade_ids.add(ident)
        book = self.books[ticker]
        if not self.book_fresh(ticker):
            return
        aggressor = trade.get('taker_outcome_side', trade.get('taker_side'))
        if aggressor not in ('yes','no'):
            self.data_gap(ticker, 'unknown aggressor direction')
            return
        resting_side = 'no' if aggressor == 'yes' else 'yes'
        trade_price = D(trade['yes_price_dollars']) if resting_side == 'yes' else 1-D(trade['yes_price_dollars'])
        volume = D(trade['count_fp'])
        if not volume.is_finite() or volume <= 0 or not trade_price.is_finite() or not ZERO <= trade_price <= 1:
            raise ValueError('invalid trade price/quantity')
        print_time = trade.get('ts_ms', trade.get('ts', 0)*1000)/1000
        if abs(self.now-print_time) > self.stale_seconds:
            self.data_gap(ticker, 'stale/future trade print')
            return
        candidates = sorted((o for o in self.orders.values() if o.ticker == ticker and
            o.side == resting_side and o.status == 'resting' and o.arrives <= print_time and
            (o.price == trade_price or trade_price <= o.price-D('.01'))),
            key=lambda o: (-o.price, o.arrives, o.id))
        remaining_print = volume
        shadow_by_price = {}
        for order in candidates:
            effective_volume = volume-sum((q for p,q in shadow_by_price.items() if p > order.price), ZERO)
            old_ahead = order.ahead
            through = trade_price <= order.price-D('.01')
            eligible = effective_volume if through else max(ZERO, effective_volume-old_ahead)
            if not through:
                order.ahead = max(ZERO, old_ahead-effective_volume)
            reason = 'TRADE_THROUGH' if through else 'QUEUE_EXHAUSTED'
            if (not through and not eligible and self.now < self.spot.toxic_until[order.side]
                    and order.stress_episode != self.spot.episode):
                order.stress_episode = self.spot.episode
                if self.rng.random() < self.toxic_probability:
                    eligible, reason = effective_volume, 'ADVERSE_SELECTION_STRESS'
            take = min(order.remaining, remaining_print, eligible)
            if take:
                self.fill(order, take, order.price, reason)
                remaining_print -= take
                shadow_by_price[order.price] = shadow_by_price.get(order.price, ZERO)+take

    def data_gap(self, ticker: str, reason: str):
        if ticker in self.books:
            seen=self.gap_reasons.setdefault(ticker,set())
            duplicate=reason in seen
            seen.add(reason)
            self.books[ticker].valid = False
            self.books[ticker].snapshot_at = 0.0
            self.wallet.stat(ticker).valid = False
            callback=getattr(self.strategy,'on_data_gap',None)
            if callback:callback(ticker,reason)
            self.cancel_buys(ticker)
            if not duplicate:self.log('DATA_GAP', ticker=ticker, reason=reason)

    def report(self, ticker: str, final=False) -> dict:
        stat = self.wallet.stat(ticker)
        report = dict(ticker=ticker, bot_name=self.markets[ticker].get('bot_name',ticker),
            bot_id=self.markets[ticker].get('bot_id'), strategy_version=self.markets[ticker].get('strategy_version','convexity-1'),
            final=final, data_valid=stat.valid,
            win_rate=str(stat.won/stat.closed*100) if stat.closed else None,
            closed_contracts=str(stat.closed),winning_contracts=str(stat.won),
            gross_profit=str(stat.gross), total_fees_paid=str(stat.fees_paid),
            average_slippage_per_taker_order=str(stat.taker_slippage/stat.taker_orders)
                if stat.taker_orders else None,
            average_price_slippage_per_taker_order=str(stat.taker_order_slippage/stat.taker_orders)
                if stat.taker_orders else None,
            taker_price_slippage_variance=str(max(ZERO, stat.taker_slippage_square/stat.taker_orders-
                (stat.taker_order_slippage/stat.taker_orders)**2)) if stat.taker_orders else None,
            quantity_weighted_slippage_per_contract=str(stat.taker_slippage/stat.taker_quantity)
                if stat.taker_quantity else None,
            net_realized_pnl=str(stat.gross-stat.realized_fees),
            open_contracts=str(sum((l.quantity for l in self.wallet.lots if l.ticker==ticker), ZERO)),
            stress_fill_contracts=str(stat.stress_fills), cash=str(self.wallet.cash),
            available_cash=str(self.available()), outstanding_orders=sum(1 for o in self.orders.values()
                if o.ticker==ticker and o.status in ('pending','resting')))
        from .profit_recovery import execution_report
        report['execution']=execution_report(self,ticker)
        print(json.dumps(report, indent=2))
        self.log('CYCLE_REPORT', ticker=ticker, details=json.dumps(report))
        with open(self.audit.path/'reports.jsonl', 'a') as f:
            f.write(json.dumps(report)+'\n')
        from .dashboard import write_dashboard
        write_dashboard(self.audit.path)
        return report

    def handle(self, source: str, payload: dict, now: float):
        # Execute due actions against the last causally observed book BEFORE a newer event.
        changed={self.orders[item[3]].ticker for item in self.pending if item[0]<=now}
        self.advance(now)
        if source == 'market':
            changed.add(payload['market']['ticker'])
            self.add_market(payload['market'], FeePolicy(D(payload['taker_multiplier']),
                                                       D(payload['maker_multiplier'])))
        elif source == 'refill':
            self.refill(D(payload['amount']))
        elif source == 'spot':
            self.spot.add(float(payload['price']), payload['event_time'], now)
            if self.strategy and self.spot.spike:
                already_paused=now<self.safety_until
                self.safety_until=max(self.safety_until,now+10)
                # A sustained break may generate hundreds of spot prints. Once
                # entries are paused and bids canceled, extend the timer without
                # rewriting every market's checkpoint/audit on every tick.
                if not already_paused:
                    for ticker in self.markets:
                        if ticker not in self.closed_reports:
                            self.strategy.safety_cancel(ticker)
                            self.cancel_buys(ticker)
                            self.log('SPOT_SAFETY_CANCEL', ticker=ticker, reason='2.5 sigma strategy valve; stable 10-second cooldown')
        elif source == 'book_heartbeat':
            sid=payload.get('sid')
            if sid in self.sequences:self.book_feed_at[sid]=now
        elif source == 'metadata_retry':
            self.log('METADATA_RETRY',ticker=payload.get('ticker'),reason=payload['reason'],
                     details=json.dumps({k:payload.get(k) for k in ('scope','series','status','code')}))
        elif source == 'gap':
            self.sequences.clear();self.book_feed_at.clear()
            self.spot = Spot()
            for ticker in list(self.books):
                if ticker not in self.settled:
                    self.data_gap(ticker, payload['reason'])
        elif source == 'settlement':
            ticker = payload['ticker']
            if ticker not in self.settled:
                raise ValueError('settlement requires prior explicit WS settled event')
            if not self.markets[ticker].get('paid'):
                self.wallet.settle(ticker, D(payload['yes_payout']))
                self.trade_ids = {ident for ident in self.trade_ids if ident[0] != ticker}
                self.markets[ticker]['paid'] = True
                self.log('SETTLED', ticker=ticker, price=payload['yes_payout'])
                self.report(ticker, final=True)
        elif source == 'kalshi':
            kind, msg = payload.get('type'), payload.get('msg', {})
            ticker = msg.get('market_ticker')
            if ticker in self.markets:changed.add(ticker)
            sid, seq = payload.get('sid'), payload.get('seq')
            previous_seq = self.sequences.get(sid)
            if sid is not None and seq is not None:
                if kind != 'orderbook_snapshot' and previous_seq is not None and seq <= previous_seq:
                    return  # Duplicate delivery; never apply depth or print twice.
                if (kind in ('orderbook_delta','trade') and previous_seq is not None and
                        seq != previous_seq+1):
                    for affected in self.books:
                        if affected not in self.settled:
                            self.data_gap(affected, 'subscription sequence gap')
                    self.sequences[sid] = seq
                    return
                self.sequences[sid] = seq
            if kind == 'event_fee_update':
                for affected in self.markets:
                    if str(msg.get('event_ticker','')).startswith('KXBTC15M') and affected not in self.settled:
                        self.data_gap(affected, 'fee metadata changed; cycle excluded')
            if ticker in self.markets:
                if kind in ('orderbook_snapshot','orderbook_delta'):
                    try:
                        if abs(now-payload.get('sending_ts_ms', now*1000)/1000) > self.stale_seconds:
                            raise ValueError('stale book event')
                        if kind == 'orderbook_delta':
                            if not self.books[ticker].valid:
                                return  # Wait for replacement snapshot; never patch an invalid book.
                            # Subscription sequence is shared across subscribed markets.
                            self.books[ticker].seq = previous_seq
                        self.books[ticker].apply(payload, now)
                        self.book_feed_at[sid]=now
                    except ValueError as exc:
                        self.data_gap(ticker, str(exc))
                        raise
                elif kind == 'trade':
                    self.trade(ticker, msg)
                elif kind == 'market_lifecycle_v2':
                    if msg['event_type'] == 'settled':
                        self.settled.add(ticker)
                        self.cancel_buys(ticker)
                    elif msg['event_type'] in ('deactivated','close_date_updated'):
                        self.data_gap(ticker, msg['event_type'])
        if source == 'clock':
            for ticker, book in self.books.items():
                if self.now < self.markets[ticker]['close'] and book.valid and (
                        not self.book_fresh(ticker) or
                        (self.spot.at and self.now-self.spot.at > self.stale_seconds)):
                    self.data_gap(ticker, 'market/spot data stale')
        if self.strategy:
            if source in ('clock','refill'):self.strategy.step()
            else:
                for affected in changed:self.strategy.step(affected)
        for ticker, market in self.markets.items():
            if now >= market['close'] and ticker not in self.closed_reports:
                self.cancel_buys(ticker)
                self.report(ticker)
                self.closed_reports.add(ticker)


class ConvexityStrategy:
    """The previously requested 10c/3c, conditional-arm, rollover/freeze design."""
    def __init__(self, engine: Engine, contracts=100, require_spot_warmup=True, series=None, name=None):
        self.e, self.contracts, self.require_spot = engine, D(contracts), require_spot_warmup
        self.series, self.name = series, name or series
        self.enabled = True
        self.phases, self.entered, self.locked = {}, set(), set()
        self.safety_retries=set()
        self.halted, self.emergency, self.last_exit = set(), {}, {}
        self.e.fill_callback = self.on_fill
        self.e.strategy = self

    def safety_cancel(self,ticker):
        for order in self.e.orders.values():
            if order.ticker==ticker and order.maker and order.status in ('pending','resting'):
                self.safety_retries.add((ticker,order.phase,order.side))

    def on_fill(self, order: Order, quantity: D):
        self.locked.add((order.ticker, phase_at(self.e.markets[order.ticker]['close'], self.e.now)))
        self.e.cancel_buys(order.ticker)
        if order.maker:
            # If a buy leaves inventory of the opposite side of earlier acquisitions,
            # only the residual new-side net position needs an emergency exit.
            if order.opposing_fill_race:
                self.halted.add(order.ticker)
                self.emergency[order.ticker] = order.side
                self.e.log('BOTH_SIDES_FILL_WARNING', order, reason='net inventory first')

    def exit_allowed(self, order: Order):
        phase = phase_at(self.e.markets[order.ticker]['close'], self.e.now)
        if order.purpose=='partial_profit':return phase in (1,2)
        return phase in (1,2) or (phase == 3 and self.emergency.get(order.ticker) == order.side)

    def step(self,changed_ticker=None):
        for ticker, market in self.e.markets.items():
            if changed_ticker is not None and ticker!=changed_ticker:continue
            if self.series and not ticker.startswith(self.series+'-'):
                continue
            phase = phase_at(market['close'], self.e.now)
            if self.phases.get(ticker) != phase:
                self.e.cancel_buys(ticker)
                self.phases[ticker] = phase
                self.e.log('PHASE', ticker=ticker, details=str(phase))
            book = self.e.books[ticker]
            if not self.e.book_fresh(ticker):
                continue
            for lot in self.e.wallet.lots:
                if lot.ticker != ticker or phase not in (1,2):
                    continue
                arm, stop = (D('.50'), D('.45')) if phase == 2 or lot.phase_origin==2 else (D('.40'),D('.30'))
                bid = book.bid(lot.side) or ZERO
                before=(lot.is_armed,lot.exit_requested)
                # A trade print may arrive before the depth updates it caused.
                # A pre-entry quote must not arm a brand-new cheap fill.
                depth=sum((q for p,q in book.depth(lot.side,'sell') if p>arm),ZERO)
                if book.at>lot.acquired_at:lot.is_armed |= bid > arm and depth>=lot.quantity
                lot.exit_requested |= lot.is_armed and bid <= stop
                if before != (lot.is_armed,lot.exit_requested):
                    self.e.log('RISK_STATE',ticker=ticker,side=lot.side,details=json.dumps(dict(
                        lot_id=lot.id,bid=str(bid),quote_at=book.at,entry_at=lot.acquired_at,
                        is_armed=lot.is_armed,exit_requested=lot.exit_requested,
                        arm=str(arm),stop=str(stop),phase=phase)))
            pending_exit = any(o.ticker == ticker and not o.maker and o.status=='pending'
                               for o in self.e.orders.values())
            if not pending_exit and self.e.now-self.last_exit.get(ticker, -1e9) >= .5 and phase<4:
                for side in ('yes','no'):
                    targets = [l for l in self.e.wallet.lots if l.ticker==ticker and l.side==side and
                        ((phase in (1,2) and l.exit_requested) or self.emergency.get(ticker)==side)]
                    if targets:
                        self.e.cancel_buys(ticker)
                        self.last_exit[ticker] = self.e.now
                        self.e.place(ticker, side, 'sell', sum((l.quantity for l in targets), ZERO),
                                     D('.01'), maker=False, phase=phase, targets=[l.id for l in targets])
                        pending_exit=True
                        break
                if not pending_exit and phase in (1,2):
                    from .profit_recovery import recovery_order
                    for lot in self.e.wallet.lots:
                        if lot.ticker!=ticker or lot.exit_requested or book.at<=lot.acquired_at:continue
                        price=D(market.get('partial_profit_price','.40'))
                        quantity=recovery_order(lot,book,self.e.fees[ticker],price)
                        if quantity:
                            self.e.cancel_buys(ticker)
                            self.last_exit[ticker]=self.e.now
                            self.e.log('PARTIAL_PROFIT_REQUESTED',ticker=ticker,side=lot.side,
                                quantity=quantity,price=price,details=json.dumps(dict(lot_id=lot.id,
                                cost=str(lot.recovery_cost),recovered=str(lot.recovery_proceeds))))
                            self.e.place(ticker,lot.side,'sell',quantity,price,maker=False,
                                phase=phase,targets=[lot.id],purpose='partial_profit')
                            break
            for key in tuple(self.safety_retries):
                if key[0]!=ticker:continue
                if key[1]!=phase or (ticker,phase) in self.locked:
                    self.safety_retries.discard(key);continue
                if self.e.now>=self.e.safety_until and not any(o.ticker==ticker and o.maker and
                        o.phase==phase and o.side==key[2] and o.status in ('pending','resting') for o in self.e.orders.values()):
                    self.entered.discard(key);self.safety_retries.discard(key)
                    self.e.log('SAFETY_REENTRY_READY',ticker=ticker,side=key[2],reason='cooldown ended; prior bid unfilled')
            if (self.enabled and self.e.now>=self.e.safety_until and book.bid('yes') is not None and book.bid('no') is not None and phase in (1,2) and ticker not in self.halted and ticker not in self.e.settled and
                    self.e.wallet.stat(ticker).valid and (ticker,phase) not in self.locked and
                    (not self.require_spot or self.e.spot.ready(self.e.now))):
                price = D('.10') if phase==1 else D('.03')
                for side in ('yes','no'):
                    key = (ticker,phase,side)
                    if key not in self.entered:
                        ask = book.ask(side)
                        if ask is not None and price >= ask:
                            continue
                        self.entered.add(key)
                        self.e.place(ticker, side, 'buy', self.contracts, price, phase=phase,
                                     expiry=market['close']-900+(601 if phase==1 else 781))


class StrategyFleet:
    """28 independent strategy instances sharing transport, liquidity and virtual cash."""
    def __init__(self, engine, profiles):
        self.e = engine
        self.halted = set()
        self.bots = {}
        for profile in profiles:
            if profile['series'] in self.bots:
                raise ValueError('Duplicate series profile')
            bot = ConvexityStrategy(engine, profile['contracts'], series=profile['series'],
                                    name=profile['name'])
            bot.halted = self.halted
            self.bots[profile['series']] = bot
        engine.fill_callback = self.on_fill
        engine.strategy = self

    def owner(self, ticker):
        return self.bots.get(ticker.split('-')[0])

    def safety_cancel(self,ticker):
        bot=self.owner(ticker)
        if bot:bot.safety_cancel(ticker)

    def on_fill(self, order, quantity):
        bot = self.owner(order.ticker)
        if bot:
            bot.on_fill(order, quantity)

    def exit_allowed(self, order):
        bot = self.owner(order.ticker)
        return bool(bot and bot.exit_allowed(order))

    def step(self,changed_ticker=None):
        if changed_ticker is not None:
            bot=self.owner(changed_ticker)
            if bot:bot.step(changed_ticker)
        else:
            for bot in self.bots.values():bot.step()
