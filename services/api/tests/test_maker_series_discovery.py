"""Bounded targeted discovery complements broad pagination without new feeds."""
import unittest
from unittest.mock import Mock
from services.paper_demo.shadow.market_maker import maker_event_page,CATEGORIES
from services.paper_demo.shadow.maker_discovery import SERIES_PER_CATEGORY

class MakerSeriesDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def host(self,series=None):
        h=Mock()
        def call(method,path,params):
            if path=='/series':return dict(series=series or [])
            if path=='/events':return dict(events=[],cursor='next-'+params.get('series_ticker','broad'))
            raise AssertionError(path)
        h.verified_data.call.side_effect=call;return h
    async def test_initial_page_has_no_catalog_overhead(self):
        h=self.host();s=dict(cursor='broad-start',reads=0)
        await maker_event_page(h,s,200,86400)
        self.assertEqual(h.verified_data.call.call_count,1)
        self.assertEqual(s['cursor'],'next-broad');self.assertEqual(s['pages'],1)
    async def test_volume_prior_targets_balanced_categories_without_replacing_broad_cursor(self):
        h=self.host([dict(ticker='POL',category='Politics',title='Election',volume=100),
            dict(ticker='FED',category='Economics',title='Federal Reserve',volume=90),
            dict(ticker='CUP',category='Sports',title='World Cup champion',volume=80),
            dict(ticker='OSCARS',category='Entertainment',title='Academy awards',volume=70),
            dict(ticker='BTC',category='Financials',title='Bitcoin target',volume=9999),
            dict(ticker='RAIN',category='Weather',title='Rain',volume=9999)])
        s=dict(cursor='broad-next',reads=0,pages=1)
        await maker_event_page(h,s,200,86400)
        self.assertEqual(s['series_pool'],['POL','FED','CUP','OSCARS'])
        self.assertEqual(s['cursor'],'broad-next')
        self.assertEqual(s['series_cursors']['POL'],'next-POL')
        self.assertEqual(h.verified_data.call.call_args.args[2]['min_close_ts'],86600)
        self.assertEqual(h.verified_data.call.call_args.args[2]['series_ticker'],'POL')
        await maker_event_page(h,s,230,86400)
        self.assertEqual(s['discovery_source'],'FED')
        self.assertEqual(sum(c.args[1]=='/series' for c in h.verified_data.call.call_args_list),2)
        self.assertEqual(sum(c.args[1]=='/events' for c in h.verified_data.call.call_args_list),2)
    async def test_every_fourth_page_preserves_broad_progress(self):
        h=self.host();s=dict(cursor='broad-old',reads=0,pages=4,series_at=1000,series_pool=['POL'],series_cursors={'POL':'pol-old'})
        await maker_event_page(h,s,200,86400)
        params=h.verified_data.call.call_args.args[2]
        self.assertNotIn('series_ticker',params);self.assertEqual(params['cursor'],'broad-old')
        self.assertEqual(s['cursor'],'next-broad');self.assertEqual(s['series_cursors']['POL'],'pol-old')
    async def test_missing_catalog_falls_back_and_tries_other_categories(self):
        h=self.host()
        def call(method,path,params):
            if path=='/series':raise ValueError('unavailable')
            return dict(events=[],cursor='next')
        h.verified_data.call.side_effect=call;s=dict(cursor='',reads=0,pages=1)
        await maker_event_page(h,s,200,86400);await maker_event_page(h,s,230,86400)
        self.assertEqual(s['discovery_source'],'broad_events')
        self.assertEqual(sum(c.args[1]=='/series' for c in h.verified_data.call.call_args_list),2)
        self.assertEqual(len(s['series_query_at']),2)
    async def test_broader_catalog_includes_lower_ranked_series_without_extra_event_reads(self):
        series=[dict(ticker='POL-'+str(i),category='Politics',title='Election',
                     volume=1000-i) for i in range(32)]
        h=self.host(series);s=dict(cursor='',reads=0,pages=1)
        await maker_event_page(h,s,200,86400)
        self.assertEqual(len(s['series_pool']),16)
        self.assertEqual(s['series_pool'],['POL-'+str(i) for i in range(16)])
        # Only a single bounded category catalogue and one event page.
        self.assertEqual(sum(c.args[1]=='/events' for c in h.verified_data.call.call_args_list),1)
        self.assertEqual(sum(c.args[1]=='/series' for c in h.verified_data.call.call_args_list),1)
        # No extra subscriptions, admission, or orders from discovery alone.
        h.put.assert_not_called()

    async def test_verified_hot_series_gets_one_page_without_starving_round_robin_or_broad(self):
        # The best live series need not be among the lifetime-volume top series.
        h=self.host();s=dict(cursor='BROAD',reads=0,pages=1,series_at=999999,
            series_pool=['COLD-A','COLD-B','COLD-C'],
            candidates={'HOT-A':dict(event=dict(series_ticker='HOT'),
                inspected_at=200,trades_last_hour=12,recent_quote_touch_count=3,reason='admitted_to_shared_monitoring')})
        selected=[]
        for step in range(8):
            await maker_event_page(h,s,230+step*30,86400)
            params=[c.args[2] for c in h.verified_data.call.call_args_list
                    if c.args[1]=='/events'][-1]
            selected.append(params.get('series_ticker','BROAD'))
        self.assertEqual(selected,['COLD-A','HOT','COLD-B','BROAD',
                                   'COLD-C','HOT','COLD-A','BROAD'])
        self.assertEqual(s['series_index'],4)
        self.assertEqual(s['priority_reads_total'],2)
        self.assertEqual(s['priority_index'],2)
        self.assertEqual(s['cursor'],'next-broad')
        self.assertEqual(s['series_cursors']['HOT'],'next-HOT')
        self.assertEqual(sum(c.args[1]=='/events' for c in h.verified_data.call.call_args_list),8)
        h.put.assert_not_called()

    async def test_stale_unverified_and_low_activity_series_never_receive_priority(self):
        from services.paper_demo.shadow.maker_discovery import verified_hot_series
        s=dict(candidates={
            'stale':dict(event=dict(series_ticker='STALE'),inspected_at=100,
                trades_last_hour=20,reason='admitted_to_shared_monitoring'),
            'unverified':dict(event=dict(series_ticker='UNVERIFIED'),
                trades_last_hour=30,reason='admitted_to_shared_monitoring'),
            'poor':dict(event=dict(series_ticker='QUIET'),inspected_at=3900,
                trades_last_hour=5,recent_quote_touch_count=1,reason='awaiting_shared_admission'),
            'unstable':dict(event=dict(series_ticker='BAD'),inspected_at=3990,
                trades_last_hour=30,recent_quote_touch_count=5,reason='recent_trade_prices_unstable'),
            'genuine':dict(event=dict(series_ticker='LIVE'),inspected_at=3990,
                trades_last_hour=6,reason='awaiting_shared_admission')})
        self.assertEqual(verified_hot_series(s,4000),['LIVE'])
        h=self.host();s.update(cursor='BROAD',reads=0,pages=2,
            series_at=999999,series_pool=['NORMAL'])
        await maker_event_page(h,s,4000,86400)
        self.assertEqual(h.verified_data.call.call_args.args[2]['series_ticker'],'LIVE')
        s['pages']=2;s['candidates']['genuine']['inspected_at']=0
        await maker_event_page(h,s,5000,86400)
        self.assertEqual(h.verified_data.call.call_args.args[2]['series_ticker'],'NORMAL')

    async def test_priority_split_page_retains_exact_cursor_and_round_robin_index(self):
        h=self.host();s=dict(cursor='broad-start',reads=0,pages=2,series_at=999999,
            series_pool=['COLD'],series_index=3,
            candidates={'active':dict(event=dict(series_ticker='HOT'),
                inspected_at=200,trades_last_hour=7,reason='awaiting_shared_admission')})
        calls=[]
        def respond(method,path,params):
            calls.append((path,dict(params)))
            if path=='/events':
                if params.get('with_nested_markets')=='true':
                    from services.demo.exchange import ExchangeFailure
                    raise ExchangeFailure('paper_data_capacity')
                return dict(events=[dict(event_ticker='HOT-EVENT',series_ticker='HOT',
                    category='Politics',title='Election')],cursor='NEXT',milestones=[])
            self.assertEqual(path,'/markets')
            return dict(markets=[],cursor='')
        h.verified_data.call.side_effect=respond
        s['event_page_limit']=1
        await maker_event_page(h,s,230,86400)
        self.assertEqual(s['series_index'],3)
        self.assertEqual(s['priority_index'],1)
        self.assertEqual(s['series_cursors']['HOT'],'NEXT')
        self.assertEqual(s['cursor'],'broad-start')
        self.assertEqual(len([v for k,v in calls if k=='/events']),2)
        self.assertEqual(len([v for k,v in calls if k=='/markets']),1)

    async def test_catalog_refresh_keeps_fresh_hot_cursor_outside_top_volume_pool(self):
        h=self.host([dict(ticker='COLD',category='Politics',title='Election',volume=100)])
        s=dict(cursor='broad',reads=0,pages=2,series_at=0,
            series_pool=['COLD'],series_cursors={'HOT':'saved-hot-page','OLD':'discard-me'},
            candidates={'recent':dict(event=dict(series_ticker='HOT'),
                 inspected_at=300,trades_last_hour=7,reason='awaiting_shared_admission')})
        await maker_event_page(h,s,330,86400)
        self.assertEqual(s['series_pool'],['COLD'])
        self.assertEqual(h.verified_data.call.call_args.args[2]['series_ticker'],'HOT')
        self.assertEqual(h.verified_data.call.call_args.args[2]['cursor'],'saved-hot-page')
        self.assertNotIn('OLD',s['series_cursors'])

    async def test_catalog_cache_is_bounded_and_never_creates_orders(self):
        h=self.host([dict(ticker=str(i),category='Politics',title='Election',volume=100+i) for i in range(200)]+[dict(ticker='NAN',category='Politics',volume='nan')])
        s=dict(cursor='',reads=0,pages=1,series_cursors={'old':'cursor'})
        await maker_event_page(h,s,200,86400)
        self.assertEqual(len(s['series_pool']),SERIES_PER_CATEGORY);self.assertNotIn('NAN',s['series_pool'])
        self.assertNotIn('old',s['series_cursors']);h.put.assert_not_called()
