"""Pure cash/quantity replay of one explicitly selected paper-wallet session.

No I/O or financial mutation. Recorded fill fees are replayed as charged;
this is not independent validation of a historical venue fee schedule.
"""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

D=Decimal
ZERO=D(0)
TOLERANCE=D('1e-18')
KINDS=frozenset(('FILL','SETTLED','REFILL'))
MAX_EVENTS=250000
MAX_BATCH=512
MAX_SEARCH_STATES=10000


class CashReconciliationError(ValueError):pass


def number(value):
    if isinstance(value,bool) or not isinstance(value,(str,int,float,D)):
        raise CashReconciliationError('invalid_numeric_evidence')
    try:result=D(str(value))
    except InvalidOperation:raise CashReconciliationError('invalid_numeric_evidence') from None
    if not result.is_finite():raise CashReconciliationError('nonfinite_numeric_evidence')
    return result


def close(a,b):return abs(a-b)<=TOLERANCE


def event(row):
    if not isinstance(row,dict):raise CashReconciliationError('invalid_source_row')
    try:
        ident=str(UUID(row['id']))
        stamp=datetime.fromisoformat(row['created_at'])
    except (KeyError,ValueError,TypeError,AttributeError):
        raise CashReconciliationError('invalid_source_identity') from None
    if (ident!=row['id'] or stamp.tzinfo is None or row.get('asset')!='crypto'
            or row.get('status')!='succeeded'
            or not isinstance(row.get('idempotency_key'),str)
            or not row['idempotency_key'].startswith('demo/shadow/event/')
            or not len('demo/shadow/event/')<len(row['idempotency_key'])<=180):
        raise CashReconciliationError('invalid_source_provenance')
    p=row.get('progress')
    if not isinstance(p,dict) or p.get('event') not in KINDS or 'archive' in p:
        raise CashReconciliationError('unresolved_financial_evidence')
    result=dict(id=ident,key=row['idempotency_key'],stamp=stamp,kind=p['event'],cash=number(p.get('cash')))
    if p['event']=='REFILL':
        result['quantity']=number(p.get('quantity'))
        if result['quantity']<=0:raise CashReconciliationError('invalid_refill')
        return result
    ticker=p.get('ticker')
    if not isinstance(ticker,str) or not ticker or len(ticker)>180:
        raise CashReconciliationError('invalid_market_identity')
    price=number(p.get('price'))
    if not ZERO<=price<=1:raise CashReconciliationError('invalid_execution_price')
    result.update(ticker=ticker,price=price)
    if p['event']=='FILL':
        quantity=number(p.get('quantity'));fee=number(p.get('fee'))
        if (quantity<=0 or fee<0 or p.get('side') not in ('yes','no')
                or p.get('action') not in ('buy','sell')):
            raise CashReconciliationError('invalid_fill')
        result.update(quantity=quantity,fee=fee,side=p['side'],action=p['action'])
    return result


def transition(state, item):
    """Reconstruct net collateral releases independently of the live Wallet."""
    cash,inventory,settled=state
    inventory=inventory.copy();settled=settled.copy()
    if item['kind']=='REFILL':cash+=item['quantity']
    else:
        ticker=item['ticker'];yes=(ticker,'yes');no=(ticker,'no')
        if ticker in settled:return None
        if item['kind']=='SETTLED':
            cash+=inventory.pop(yes,ZERO)*item['price']+inventory.pop(no,ZERO)*(1-item['price'])
            settled.add(ticker)
        else:
            key=(ticker,item['side']);other=(ticker,'no' if item['side']=='yes' else 'yes')
            q=item['quantity'];p=item['price'];fee=item['fee']
            if item['action']=='buy':
                # The original wallet must afford the buy before netting.
                if q*p+fee>cash+TOLERANCE:return None
                netted=min(q,inventory.get(other,ZERO))
                cash+=netted-q*p-fee
                inventory[other]=inventory.get(other,ZERO)-netted
                inventory[key]=inventory.get(key,ZERO)+q-netted
            else:
                if q>inventory.get(key,ZERO)+TOLERANCE:return None
                inventory[key]=inventory.get(key,ZERO)-q
                cash+=q*p-fee
    inventory={k:v for k,v in inventory.items() if not close(v,ZERO)}
    if cash < -TOLERANCE or not close(cash,item['cash']):return None
    return cash,inventory,settled


def order_batch(initial, items):
    """Find a cash-consistent ordering for rows sharing one commit timestamp.

    now() timestamps and random UUIDs do not encode insert order. Never sort
    same-commit fills by UUID and pretend that was execution chronology.
    Cash links plus covered inventory constrain the path. Only one valid path
    is needed for aggregate cash/quantities: netted collateral and final signed
    inventory are invariant under valid orderings; fills after settlement are
    forbidden. Lot cost/target allocation is expressly outside this verifier.
    """
    if len(items)>MAX_BATCH:raise CashReconciliationError('commit_batch_capacity')
    def choices(state,remaining):
        for index in remaining:
            after=transition(state,items[index])
            if after is not None:
                yield after,tuple(i for i in remaining if i!=index)
    remaining=tuple(range(len(items)))
    stack=[(initial,remaining,None)];visited=set();attempts=0
    while stack:
        state,remaining,iterator=stack[-1]
        if not remaining:return state,attempts
        if iterator is None:
            signature=(remaining,state[0],tuple(sorted(state[1].items())),tuple(sorted(state[2])))
            if signature in visited:
                stack.pop();continue
            visited.add(signature);attempts+=1
            if attempts>MAX_SEARCH_STATES:raise CashReconciliationError('cash_order_search_capacity')
            iterator=choices(state,remaining);stack[-1]=(state,remaining,iterator)
        try:
            after,next_remaining=next(iterator)
            stack.append((after,next_remaining,None))
        except StopIteration:stack.pop()
    raise CashReconciliationError('cash_chain_unresolved')


def reconcile_wallet(wallet, rows, *, initial_cash):
    """Rows must belong to ONE independently selected session and portfolio."""
    if not isinstance(rows,list) or len(rows)>MAX_EVENTS:
        raise CashReconciliationError('financial_source_capacity')
    initial=number(initial_cash)
    if initial<0:raise CashReconciliationError('invalid_initial_funding')
    groups=defaultdict(list);seen=set();keys=set();fees=ZERO;refills=ZERO;kinds=Counter()
    for row in rows:
        item=event(row)
        if item['id'] in seen or item['key'] in keys:
            raise CashReconciliationError('duplicate_financial_identity')
        seen.add(item['id']);keys.add(item['key']);groups[item['stamp']].append(item);kinds[item['kind']]+=1
        if item['kind']=='FILL':fees+=item['fee']
        if item['kind']=='REFILL':refills+=item['quantity']
    state=(initial,{},set());search_states=0
    for stamp in sorted(groups):
        state,steps=order_batch(state,groups[stamp]);search_states+=steps
    expected_inventory=defaultdict(lambda:ZERO)
    for lot in wallet['lots']:
        quantity=number(lot['quantity'])
        if quantity<=0 or lot['side'] not in ('yes','no'):
            raise CashReconciliationError('invalid_checkpoint_inventory')
        expected_inventory[(lot['ticker'],lot['side'])]+=quantity
    actual=state[1]
    inventory_matches=all(close(actual.get(k,ZERO),expected_inventory.get(k,ZERO))
                          for k in actual.keys()|expected_inventory.keys())
    cash_matches=close(state[0],number(wallet['cash']))
    deposits_match=close(initial+refills,number(wallet['deposits']))
    return dict(cash_matches=cash_matches,inventory_matches=inventory_matches,
                deposits_match=deposits_match,recorded_cash_chain_verified=True,
                replay_matches_checkpoint=cash_matches and inventory_matches and deposits_match,
                replayed_events=len(rows),event_kinds=dict(kinds),commit_groups=len(groups),
                search_states=search_states,recorded_fill_fees=str(fees),
                replayed_cash=str(state[0]),cash_difference=str(state[0]-number(wallet['cash'])),
                lot_cost_allocation_reconciled=False,session_scope_verified=False,
                full_financial_history_verified=False,safe_to_restart=False)
