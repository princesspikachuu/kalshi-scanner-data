import unittest
from unittest.mock import Mock,patch
from services.demo.cycles import eligible,entry_deadline,buy_cancel_deadline,entry_block_reason
from services.api.tests.test_demo_cycles import worker,bot,book,entry,NOW
from services.api.demo_models import BotConfig

class EntryWindow(unittest.TestCase):
    def test_window_begins_at_market_open_not_discovery(self):
        b=bot(cycle_entry_minutes=5);q=book();q['open']=NOW-299;q['close']=NOW+601
        self.assertTrue(eligible(b['config'],b['config']['squares'][0],q,NOW))
        self.assertFalse(eligible(b['config'],b['config']['squares'][0],q,NOW+1))
        q['at']=NOW+2
        self.assertFalse(eligible(b['config'],b['config']['squares'][0],q,NOW+2))
    def test_close_buffer_can_end_window_earlier_and_unknown_open_cannot_authorize_entry(self):
        b=bot(cycle_entry_minutes=5,cycle_cutoff_minutes=3);q=book();q.update(open=NOW-10,close=NOW+100)
        self.assertEqual(entry_deadline(b['config'],q),NOW-80)
        q.update(open=0,close=NOW+900)
        self.assertFalse(eligible(b['config'],b['config']['squares'][0],q,NOW))
    def test_old_config_without_window_keeps_existing_cutoff(self):
        b=bot();q=book();self.assertEqual(entry_deadline(b['config'],q),q['close']-180)
    def test_existing_partial_buy_cancels_remainder_after_window_while_inventory_is_retained(self):
        w=worker();w.bots[0]['config']['cycle_entry_minutes']=5
        w.quotes['t']['open']=NOW-301;order=entry(filled=2,remaining=8);w.orders=[order];w.cancel=Mock()
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        w.cancel.assert_called_once();self.assertIs(w.cancel.call_args.args[0],order)
        self.assertEqual(order['filled'],2);w.submit.assert_not_called()
    def test_native_expiry_and_durable_open_are_saved_at_preparation(self):
        w=worker();w.bots[0]['config']['cycle_entry_minutes']=5
        with patch('services.demo.runtime.time.time',return_value=NOW):w.trade()
        intent=w.submit.call_args.args[0]
        self.assertEqual(intent['close'],w.quotes['t']['open']+300)
        self.assertEqual(buy_cancel_deadline(intent),intent['close'])
    def test_no_repeat_uses_filled_round_lock_even_after_config_revision_or_full_sale(self):
        for side in ('yes','no'):
            item=dict(bot='bot',price=3,side=side,no_repeat=True)
            self.assertEqual(entry_block_reason(item,[],locked_side='yes'),'complete')
        self.assertIsNone(entry_block_reason(dict(bot='bot',price=3,side='yes'),[],locked_side='yes'))
    def test_persisted_deadline_remains_stricter_than_a_later_settings_change(self):
        order=entry(market_open_at=NOW-300,entry_deadline_at=NOW,market_close_at=NOW+600)
        self.assertEqual(buy_cancel_deadline(order,config=dict(cycle_entry_minutes=10)),NOW)
    def test_optional_window_roundtrips_and_is_bounded(self):
        value=bot(cycle_entry_minutes=5)['config'];self.assertEqual(BotConfig.model_validate(value).cycle_entry_minutes,5)
        for invalid in (0,1441,True):
            with self.assertRaises(ValueError):BotConfig.model_validate(dict(value,cycle_entry_minutes=invalid))
