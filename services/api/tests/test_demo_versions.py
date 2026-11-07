import unittest
from services.api.demo_versions import infer_versions,version_clause

class VersionInference(unittest.TestCase):
    def bot(self,key='b',revision=3,strategy='buy_low_sell_high',buy=3,sell=6):
        return dict(key=key,revision=revision,created_at=1,config=dict(strategy=strategy,cycle_buy_cents=buy,cycle_sell_cents=sell))
    def test_latest_version_advances_again_instead_of_staying_at_the_first_sell_change(self):
        orders=[dict(bot='b',revision=1,first_at=50,last_at=90),dict(bot='b',revision=2,first_at=110,last_at=130),dict(bot='b',revision=3,first_at=140,last_at=150)]
        events=[dict(bot='b',at=100,details={}),dict(bot='b',at=135,details={})]
        second=infer_versions([self.bot(revision=2)],orders,events)['b']
        self.assertEqual(second['revision'],2);self.assertEqual(second['changed_at'],100)
        third=infer_versions([self.bot(sell=5)],orders,events)['b']
        self.assertEqual(third['revision'],3);self.assertEqual(third['changed_at'],135)
        self.assertEqual(third['first_entry_at'],140);self.assertEqual(third['sell_cents'],5)
    def test_new_revision_without_orders_does_not_keep_reporting_the_previous_version(self):
        orders=[dict(bot='b',revision=2,first_at=110,last_at=130)]
        events=[dict(bot='b',at=135,details=dict(revision=3,rule_revision_changed=True)),dict(bot='b',at=140,details=dict(revision=3,rule_revision_changed=False))]
        result=infer_versions([self.bot()],orders,events)['b']
        self.assertEqual(result['revision'],3);self.assertIsNone(result['first_entry_at']);self.assertEqual(result['changed_at'],135)
    def test_ambiguous_history_keeps_a_window_instead_of_inventing_a_timestamp(self):
        orders=[dict(bot='b',revision=1,first_at=50,last_at=90),dict(bot='b',revision=2,first_at=110,last_at=130)]
        result=infer_versions([self.bot(revision=2)],orders,[dict(bot='b',at=95,details={}),dict(bot='b',at=100,details={})])['b']
        self.assertIsNone(result['changed_at']);self.assertEqual((result['window_start'],result['window_end']),(95,100))
    def test_other_bot_strategies_and_new_bots_use_their_own_latest_rules(self):
        result=infer_versions([self.bot(revision=1),self.bot('weather',strategy='price_time')],[],[])
        self.assertEqual(result['b']['changed_at'],1);self.assertEqual(result['weather']['revision'],3)
        self.assertIsNone(result['weather']['buy_cents']);self.assertIsNone(result['weather']['first_entry_at'])
        self.assertEqual(version_clause('full',result),('TRUE',[]))
        with self.assertRaises(ValueError):version_clause('invalid',result)
