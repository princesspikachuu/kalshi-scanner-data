"""Football fallback remains bounded and never admits individual game markets."""
import unittest
from unittest.mock import Mock
from services.paper_demo.shadow.market_maker import category,maker_event_page

class SportsFutureClassificationTests(unittest.TestCase):
    def test_championships_divisions_and_season_awards_are_eligible(self):
        for title in ('Super Bowl','NCAAF Championship','National Football Conference East Winner','AP Pro Football Regular Season MVP','Heisman Trophy Winner','College Football Playoff Qualifiers'):
            self.assertEqual(category(dict(category='Sports',title=title)),'sports_futures',title)
    def test_game_periods_and_props_are_excluded_even_when_they_say_winner(self):
        for title in ('Pro Football 1st Half Winner','Pro Football 1st Quarter Winner','College Football 3rd Quarter Winner','Super Bowl Touchdowns','Pro Football Game','Pro Football Spread','Pro Football Receiving Yards','Cup Match Winner','Unclassified Winner'):
            self.assertIsNone(category(dict(category='Sports',title=title)),title)

class SportsCatalogueFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_after_failed_sports_catalogue_probes_smaller_tagged_catalogue(self):
        h=Mock();queries=('Politics','Economics','Financials','Sports','Entertainment','Social')
        s=dict(cursor='broad',pages=1,reads=0,series_at=9999,series_query_at={q:9999 for q in queries},series_catalogs={},series_cursors={})
        def call(method,path,params):
            if path=='/series':
                self.assertEqual(params['category'],'Sports');self.assertEqual(params['tags'],'Football')
                return dict(series=[dict(ticker='KXSB',title='Super Bowl',category='Sports',volume_fp='10000'),dict(ticker='KXNFL1H',title='Pro Football 1st Half Winner',category='Sports',volume_fp='20000')])
            self.assertEqual(params['series_ticker'],'KXSB');return dict(events=[],cursor='')
        h.verified_data.call.side_effect=call
        await maker_event_page(h,s,200,86400)
        self.assertEqual(s['series_pool'],['KXSB']);self.assertEqual(s['cursor'],'broad')
        await maker_event_page(h,s,230,86400)
        self.assertEqual(sum(c.args[1]=='/series' for c in h.verified_data.call.call_args_list),1)
        h.put.assert_not_called()
