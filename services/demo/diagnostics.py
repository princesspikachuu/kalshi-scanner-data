"""Fixed owner-facing recovery explanations; no raw exception or provider text."""
def exchange_issue(error,stage,*,market=None,order_id=None,bot=None):
    code=error.provider_code or error.code
    if error.code=='authentication':
        summary='Kalshi Demo rejected the API key or its permissions.'
        action='Open Manage connection and verify the Demo key and trading permissions.';control='connection'
    elif code=='insufficient_shard_balance':
        summary='This market’s exchange shard has insufficient available Demo cash.'
        action='The app transfers existing Demo cash automatically. Review funds if this persists.';control='funds'
    elif error.code=='rate_limited':
        summary='Kalshi has temporarily limited API requests.'
        action='Automatic retries are slowing down. Wait for verification to recover.';control='retry'
    elif error.ambiguous:
        summary='Kalshi has not confirmed whether the last write completed.'
        action='The app is checking exchange history before any replacement. Review the order in Activity; the write will not be repeated.';control='activity'
    elif code=='not_found' and stage=='reconciliation':
        summary='Kalshi has not returned a saved order during reconciliation.'
        action='New entries wait while the app verifies that order. Review its history in Activity or request another verification.';control='retry'
    elif error.code.startswith('stream'):
        summary='The market-price stream needs a fresh verified subscription.'
        action='The app reconnects automatically and checks orders before resuming entries.';control='retry'
    elif error.code=='connection':
        summary='The app could not complete a connection to Kalshi Demo.'
        action='Existing orders are retained. The app reconnects and verifies them automatically.';control='retry'
    elif code in ('post_only_cross','post_only_would_cross') or error.reason=='post_only':
        summary='Kalshi rejected a maker order because the market price moved.'
        action='The order was not accepted. Review the quote and entry settings in Activity.';control='activity'
    else:
        summary='Kalshi could not verify '+{'controls':'bot controls','discovery':'market discovery','stream':'the price stream','reconciliation':'account and order state','trade':'an order'}.get(stage,'trading state')+'.'
        action='New entries wait for a complete check. Review Activity and request verification if this persists.';control='retry'
    return dict(summary=summary,action=action,control=control,code=code,http_status=error.status,
        phase=stage,market=market,order_id=order_id,bot=bot)

def runtime_issue(stage,*,market=None,order_id=None,bot=None):
    return dict(summary='The trading worker could not finish '+{'controls':'loading bot controls','discovery':'market discovery','stream':'reconnecting the price stream','reconciliation':'order reconciliation','trade':'processing an order'}.get(stage,'recovery')+'.',
        action='Saved orders are retained. Recovery retries automatically; use Activity to inspect the affected market.',control='retry',code='runtime_recovery',http_status=None,phase=stage,market=market,order_id=order_id,bot=bot)
