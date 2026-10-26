import csv
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from loss_prevention import scenario, analyze, choose_rule, pack_path


def row(day='2026-10-01', ticker='A', won=0, side='yes'):
    return {'date':day,'ticker':ticker,'event_ticker':ticker,'asset':'btc',
        'series':'KXBTC15M','weather_type':'crypto15m','side':side,'maker_bid':'.95',
        'minutes_before_close':'5','price_band':'90-100','won':str(won),'quote_age_seconds':'0'}


def path(values=(88,70,80,90)):
    return {'close_ts':600,'bars':[[ts,v,100-v] for ts,v in zip((360,420,480,540),values)]}


class LossPreventionTests(unittest.TestCase):
    def test_sale_uses_available_bid_and_both_costs_not_threshold_price(self):
        item=scenario(row(),path())
        self.assertEqual(item['hold'],-96)
        self.assertEqual(item['exits'][90],(-10,88,4))
        self.assertEqual(item['exits'][80],(-28,70,3))
        self.assertTrue(all(t<=90 for t in item['exits']))

    def test_recovery_is_counted_against_early_sale(self):
        item=scenario(row(won=1),path())
        self.assertEqual(item['hold'],4)
        self.assertEqual(item['exits'][90][0]-item['hold'],-14)

    def test_missing_path_or_gap_is_excluded_instead_of_filled(self):
        self.assertIsNone(scenario(row(),None))
        p=path();p['bars'].pop(1)
        self.assertIsNone(scenario(row(),p))
        p=path();p['bars'][1][1]=None
        self.assertIsNone(scenario(row(),p))

    def test_zero_bid_is_no_buyer_and_settlement_quote_is_not_an_exit(self):
        item=scenario(row(),path((0,88,92,93)))
        self.assertEqual(item['exits'][90][1],88)
        p=path((96,96,96,96));p['bars']+=[[600,20,80],[300,20,80]]
        self.assertIsNone(scenario(row(),p)['exits'][90][1])

    def test_no_side_and_empty_quote_are_preserved(self):
        packed=pack_path([{'end_period_ts':360,'yes_bid':{'close_dollars':'.20'},'yes_ask':{'close_dollars':'.25'}}],600)
        self.assertEqual(packed['bars'],[[360,20,75]])
        packed=pack_path([{'end_period_ts':360}],600)
        self.assertEqual(packed['bars'],[[360,None,None]])
        item=scenario(row(side='no'),{'close_ts':600,'bars':[[ts,100-v,v] for ts,v in zip((360,420,480,540),(88,70,80,90))]})
        self.assertEqual(item['exits'][90][1],88)

    def examples(self,validation_wins=False,recovery=False):
        rows=[];paths={}
        for day in range(1,8):
            for i in range(10):
                date=f'2026-10-{day:02}'
                won=int(day>=6 and (validation_wins or recovery and i==0))
                r=row(date,f'D{day}M{i}',won)
                rows.append(r);paths[(date,r['ticker'])]=path()
        return rows,paths

    def test_threshold_selected_on_training_and_applied_only_to_later_dates(self):
        rows,paths=self.examples(recovery=True)
        keys={(r['date'],r['ticker'],5) for r in rows if r['date']=='2026-10-07'}
        study,latest=analyze(rows,paths,'btc',keys)
        rule=study['rules'][0]
        self.assertTrue(rule['supported'])
        self.assertEqual(rule['threshold_cents'],90)
        self.assertEqual(rule['training_last_date'],'2026-10-05')
        self.assertEqual(study['comparison_observations'],20)
        self.assertEqual(latest['comparison_observations'],10)
        self.assertEqual(study['records'][0]['missed_recoveries'],2)
        self.assertEqual(study['records'][0]['hold_wins'],2)
        self.assertEqual(study['records'][0]['sampled_dates'],['2026-10-06','2026-10-07'])
        self.assertEqual(study['first_date'],'2026-10-06')

    def test_later_recoveries_can_reject_profitable_training_candidate(self):
        rows,paths=self.examples(validation_wins=True)
        study,_=analyze(rows,paths,'btc')
        rule=study['rules'][0]
        self.assertFalse(rule['supported'])
        self.assertEqual(rule['candidate_cents'],90)
        self.assertLess(rule['validation_gain_cents'],0)
        self.assertEqual(study['records'][0]['improvement_cents'],0)
        self.assertEqual(study['records'][0]['early_exits'],0)

    def test_old_entry_only_data_is_not_claimed_as_path_coverage(self):
        study,_=analyze([row()],{},'btc')
        self.assertEqual(study['saved_observations'],1)
        self.assertEqual(study['path_observations'],0)
        self.assertEqual(study['records'],[])

    def test_fewer_than_seven_days_does_not_invent_a_recommendation(self):
        item=scenario(row(),path())
        rule,_,_=choose_rule([item]*100)
        self.assertFalse(rule['supported'])
        self.assertIsNone(rule['threshold_cents'])

    def test_collection_stages_new_paths_and_preserves_previous_markets(self):
        import collect_backtest as collector
        with tempfile.TemporaryDirectory() as temp:
            original=Path.cwd()
            try:
                os.chdir(temp)
                day=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=2)).date()
                close=int(dt.datetime.combine(day,dt.time(1),dt.timezone.utc).timestamp())
                market={'ticker':'NEW','series_ticker':'KXBTC15M','event_ticker':'EVENT','close_time':dt.datetime.fromtimestamp(close,dt.timezone.utc).isoformat(),'result':'no'}
                bars=[{'end_period_ts':close-60*i,'yes_bid':{'close_dollars':'.95'},'yes_ask':{'close_dollars':'.96'}} for i in range(16)]
                folder=Path('backtests/btc15m');folder.mkdir(parents=True)
                file=folder/(str(day)+'.paths.json');file.write_text(json.dumps({'OLD':{'close_ts':close,'bars':[]}}))
                with patch.dict(os.environ,{'POCKET_COLLECTION_STAGE':'.run-collection'}), patch.object(collector,'req',return_value={'market_settled_ts':'1970-01-01T00:00:00Z'}), patch.object(collector,'markets',return_value=[market]), patch.object(collector,'candle_batches',return_value=iter([(market,bars)])), patch.object(collector,'quick_trade_history',return_value=None):
                    collector.run('btc',2,1)
                self.assertEqual(set(json.loads(file.read_text())),{'OLD','NEW'})
                staged=Path('.run-collection/btc')/(str(day)+'.paths.json')
                self.assertEqual(set(json.loads(staged.read_text())),{'NEW'})
                with (folder/(str(day)+'.csv')).open() as handle:rows=list(csv.DictReader(handle))
                self.assertTrue(rows)
                report,_=analyze(rows,{(str(day),'NEW'):json.loads(staged.read_text())['NEW']},'btc')
                self.assertEqual(report['path_observations'],len(rows))
            finally:
                os.chdir(original)

if __name__=='__main__':unittest.main()
