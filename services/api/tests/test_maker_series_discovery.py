"""Bounded targeted discovery complements broad pagination without new feeds."""
import unittest
from unittest.mock import Mock
from services.paper_demo.shadow.market_maker import maker_event_page,CATEGORIES

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
        self.assertEqual(sum(c.args[1]=='/series' for c in h.verified_data.call.call_args_list),1)
        self.assertEqual(sum(c.args[1]=='/events' for c in h.verified_data.call.call_args_list),2)
    async def test_every_fourth_page_preserves_broad_progress(self):
        h=self.host();s=dict(cursor='broad-old',reads=0,pages=4,series_at=1000,series_pool=['POL'],series_cursors={'POL':'pol-old'})
        await maker_event_page(h,s,200,86400)
        params=h.verified_data.call.call_args.args[2]
        self.assertNotIn('series_ticker',params);self.assertEqual(params['cursor'],'broad-old')
        self.assertEqual(s['cursor'],'next-broad');self.assertEqual(s['series_cursors']['POL'],'pol-old')
    async def test_missing_catalog_falls_back_without_retrying_every_scan(self):
        h=self.host()
        def call(method,path,params):
            if path=='/series':raise ValueError('unavailable')
            return dict(events=[],cursor='next')
        h.verified_data.call.side_effect=call;s=dict(cursor='',reads=0,pages=1)
        await maker_event_page(h,s,200,86400);await maker_event_page(h,s,230,86400)
        self.assertEqual(s['discovery_source'],'broad_events')
        self.assertEqual(sum(c.args[1]=='/series' for c in h.verified_data.call.call_args_list),1)
    async def test_catalog_cache_is_bounded_and_never_creates_orders(self):
        h=self.host([dict(ticker=str(i),category='Politics',title='Election',volume=100+i) for i in range(200)]+[dict(ticker='NAN',category='Politics',volume='nan')])
        s=dict(cursor='',reads=0,pages=1,series_cursors={'old':'cursor'})
        await maker_event_page(h,s,200,86400)
        self.assertEqual(len(s['series_pool']),12);self.assertNotIn('NAN',s['series_pool'])
        self.assertNotIn('old',s['series_cursors']);h.put.assert_not_called()
