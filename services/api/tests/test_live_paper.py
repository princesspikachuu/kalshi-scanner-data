import copy,json,unittest
from unittest.mock import Mock
from services.paper.live import Ledger,initial,price,public_state
from services.paper.live_feed import LiveFeed,metadata

NOW=1793318400

def strategy(**changes):
    return dict(name='BTC square',asset='btc',series=['KXBTC15M'],entry_minute_min=3,entry_minute_max=5,
        min_price=90,max_price=99,below_ask_cents=1,maximum_bid_cents=None,balance_percent=10,
        contracts=5,loss_trigger_cents=None,statistical_yield_percent=5,**changes)

def quote(t=NOW,ticker='a',bid='.80',ask='.90',size='10'):
    return dict(type='ticker',msg=dict(market_ticker=ticker,ts=t,yes_bid_dollars=bid,yes_ask_dollars=ask,yes_bid_size_fp=size,yes_ask_size_fp=size))

def trade(t=NOW+3,ticker='a',volume='2',identifier='one',price='.88'):
    return dict(type='trade',msg=dict(trade_id=identifier,market_ticker=ticker,ts=t,count_fp=volume,
        yes_price_dollars=price,no_price_dollars=str(1-float(price)),taker_outcome_side='no'))

def ledger(strategies=None,model='conservative',cash=10000):
    s=initial(cash);s['feed']='connected';s['markets']['a']=dict(ticker='a',event='game',series='KXBTC15M',close=NOW+300,status='active',result='')
    return Ledger(s,strategies or [strategy()],model)


class LiveLedgerTests(unittest.TestCase):
    def test_partial_volume_cash_refund_and_confirmed_settlement_without_fees(self):
        l=ledger();l.apply([quote()],NOW)
        self.assertEqual(l.s['cash'],9555)
        l.apply([trade()],NOW+3);self.assertEqual(l.s['filled_contracts'],2)
        l.apply([],NOW+300);self.assertEqual(l.s['cash'],9822)
        self.assertEqual(len(l.s['positions']),1) # no invented close payout
        l.s['markets']['a'].update(status='settled',result='yes');l.apply([],NOW+305)
        self.assertEqual(l.s['cash'],10022);self.assertEqual(l.s['realized_pnl'],22)

    def test_restart_and_duplicate_trade_do_not_double_fill_and_share_volume(self):
        l=ledger([strategy(),strategy()]);l.apply([quote()],NOW);l.apply([trade(volume='3')],NOW+3)
        restarted=Ledger(json.loads(json.dumps(l.s)),l.strategies)
        restarted.apply([trade(volume='3')],NOW+4)
        self.assertEqual(restarted.s['filled_contracts'],3)
        self.assertLessEqual(restarted.exposure('game'),1000)

    def test_feed_gap_cancels_pending_preserves_positions_and_requires_new_quote(self):
        l=ledger();l.apply([quote()],NOW);l.apply([trade()],NOW+3)
        l.suspend(NOW+4,'connection lost');self.assertEqual(l.s['cash'],9822)
        self.assertEqual(len(l.s['positions']),1);self.assertFalse(l.s['orders']);self.assertFalse(l.s['quotes'])
        l.apply([quote(t=NOW+5,ticker='a')],NOW+5)
        self.assertEqual(l.s['orders_placed'],1)

    def test_old_or_crossed_quotes_and_expired_trades_cannot_create_fills(self):
        l=ledger();l.apply([quote(t=NOW-11),quote(bid='.95',ask='.90')],NOW)
        self.assertEqual(l.s['orders_placed'],0)
        l.apply([quote()],NOW);l.apply([trade(t=NOW+300)],NOW+300)
        self.assertEqual(l.s['filled_contracts'],0);self.assertEqual(l.s['cash'],10000)

    def test_optional_maximum_best_bid_and_strict_post_only_guard(self):
        s=strategy();s.update(bid_reference='best_bid',bid_adjustment_cents=1,maximum_bid_cents=70)
        l=ledger([s]);l.apply([quote()],NOW);self.assertEqual(l.s['orders'][0]['bid'],70)
        s.update(maximum_bid_cents=None,bid_adjustment_cents=15)
        l=ledger([s]);l.apply([quote()],NOW);self.assertFalse(l.s['orders'])

    def test_loss_prevention_consumes_depth_once_without_price_floor(self):
        s=strategy();s['loss_trigger_cents']=70
        l=ledger([s]);l.apply([quote()],NOW);l.apply([trade(volume='5')],NOW+3)
        q=quote(t=NOW+4,bid='.50',ask='.60',size='2');l.apply([q,q],NOW+4)
        self.assertEqual(l.s['positions'][0]['quantity'],3)
        self.assertEqual(l.s['realized_pnl'],-78)
        self.assertEqual(l.s['cash'],9655)

    def test_optimistic_mode_is_explicit_and_stop_keeps_filled_positions(self):
        l=ledger(model='all_filled');l.apply([quote()],NOW);l.stop(NOW+1)
        self.assertEqual(l.s['filled_contracts'],5);self.assertTrue(l.s['positions']);self.assertTrue(l.s['stopping'])
        self.assertIn('NOT a realistic',next(e['evidence'] for e in l.events if e['kind']=='fill'))

    def test_global_yield_priority_uses_fresh_quotes_across_categories(self):
        a=strategy();a.update(contracts=100)
        b=strategy();b.update(name='Sports',series=['KXNFLGAME'],statistical_yield_percent=20,contracts=100)
        l=ledger([a,b],cash=1000)
        for i in range(10):l.s['markets'][f'btc{i}']={**l.s['markets']['a'],'ticker':f'btc{i}','event':f'btc{i}'}
        l.s['markets']['sport']={**l.s['markets']['a'],'ticker':'sport','series':'KXNFLGAME','event':'sports-event'}
        l.apply([quote(ticker=t) for t in l.s['markets']],NOW)
        self.assertEqual(next(e['ticker'] for e in l.events if e['kind']=='bid'),'sport')
        self.assertLessEqual(l.exposure('sports-event'),100)

    def test_public_snapshot_is_bounded_and_excludes_feed_internal_state(self):
        l=ledger();l.apply([quote()],NOW)
        self.assertNotIn('quotes',public_state(l.s));self.assertNotIn('seen_trades',public_state(l.s))
        self.assertLess(len(json.dumps(public_state(l.s))),10000)

    def test_lifecycle_early_close_cancels_and_does_not_credit_unconfirmed_result(self):
        l=ledger();l.apply([quote()],NOW)
        l.apply([dict(type='market_lifecycle_v2',msg=dict(market_ticker='a',event_type='deactivated'))],NOW+1)
        self.assertFalse(l.s['orders']);self.assertEqual(l.s['cash'],10000)


class LiveFeedTests(unittest.TestCase):
    def test_bounded_stream_wires_fresh_messages_to_ledger_without_order_api(self):
        from threading import Event
        from services.paper.live import lifecycle
        stop=Event();clock=[NOW];s=initial(10000);m=dict(ticker='a',event='game',series='KXBTC15M',close=NOW+300,status='active',result='')
        connector=Mock();socket=connector.return_value
        feed=LiveFeed(Mock(),Mock(),Mock(),stop,clock=lambda:clock[0],connector=connector)
        feed.health=Mock();feed.discover=Mock(return_value=(100,None,{'a':m}));feed.store=Mock()
        def checkpoint(job,now,**kw):
            s['markets'].update({x['ticker']:x for x in kw.get('metadata',[])})
            l=Ledger(s,[strategy()])
            if kw.get('gap'):l.suspend(now,kw['gap'])
            if kw.get('feed'):s['feed']=kw['feed']
            l.apply(kw.get('messages',[]),now)
            if s['filled_contracts']:stop.set()
            return s
        feed.store.checkpoint.side_effect=checkpoint
        frames=[dict(type='subscribed',msg=dict(channel=ch,sid=i+1)) for i,ch in enumerate(('ticker','trade','market_lifecycle_v2'))]+[quote(),None,trade(),None]
        def recv(**kw):
            item=frames.pop(0)
            if item is None:raise TimeoutError()
            if item.get('type')=='trade':clock[0]=NOW+3
            return json.dumps(item)
        socket.recv.side_effect=recv
        feed.run_session(dict(id='session',parameters=dict(strategies=[strategy()],fill_model='conservative')),Mock())
        self.assertEqual(s['filled_contracts'],2);self.assertEqual(connector.call_args.args[0],'wss://external-api-ws.kalshi.com/trade-api/ws/v2')
        self.assertEqual(connector.call_args.kwargs['max_queue'],16)
        commands=[json.loads(c.args[0]) for c in socket.send.call_args_list]
        self.assertTrue(all(c['cmd']=='subscribe' for c in commands));socket.close.assert_called_once()
    def test_discovery_reserves_shared_budget_before_any_read(self):
        feed=LiveFeed(Mock(),Mock(),Mock(),Mock(),clock=lambda:NOW)
        feed.budget.take.return_value=8;provider=Mock()
        result=feed.discover(provider,[strategy()],initial(10000),{}, {},0)
        self.assertEqual(result[0],8);provider._read.assert_not_called()
        feed.budget.take.assert_called_once_with(1)

    def test_discovery_rate_limit_reduces_shared_pace_and_does_not_crash(self):
        from services.research.inventory import ProviderFailure
        feed=LiveFeed(Mock(),Mock(),Mock(),Mock(),clock=lambda:NOW);feed.budget.take.return_value=0
        provider=Mock();provider._read.side_effect=ProviderFailure('provider_rate_limit',delay=1,cooldown=1)
        feed.discover(provider,[strategy()],initial(10000),{},{},0)
        feed.budget.rate_limited.assert_called_once_with(1)

    def test_market_discovery_rejects_bad_id_and_keeps_pinned_positions(self):
        self.assertIsNone(metadata(dict(ticker='../orders',event_ticker='x',close_time='2026-10-30T00:00:00Z')))
        feed=LiveFeed(Mock(),Mock(),Mock(),Mock(),clock=lambda:NOW);feed.watch_limit=10
        s=initial(10000);s['positions']=[dict(ticker='held')];s['markets']['held']=dict(ticker='held',series='KXBTC15M',close=NOW-60,status='closed')
        catalog={str(i):dict(ticker=str(i),series='KXBTC15M',close=NOW+100,status='open') for i in range(1000)}
        watch=feed.watched(catalog,s,[strategy()])
        self.assertEqual(len(watch),10);self.assertEqual(watch[0]['ticker'],'held')
