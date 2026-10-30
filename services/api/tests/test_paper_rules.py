"""Multi-square matching is shared between historical and live paper engines."""
from services.paper.rules import entry_rules, matching_rule


def test_legacy_single_square_still_matches():
    s=dict(min_price=70,max_price=79,entry_minute_min=5,entry_minute_max=10)
    assert entry_rules(s)==[s]
    assert matching_rule(s,75,7)==s
    assert matching_rule(s,75,5) is None
    assert matching_rule(s,80,7) is None


def test_multiple_disjoint_windows_and_prices_one_strategy():
    a=dict(min_price=70,max_price=79,entry_minute_min=5,entry_minute_max=10,
           statistical_yield_percent=1.0)
    b=dict(min_price=90,max_price=99,entry_minute_min=1,entry_minute_max=3,
           statistical_yield_percent=2.0)
    s=dict(asset='btc',statistical_yield_percent=2.0,rules=[a,b])
    assert matching_rule(s,75,8)==a
    assert matching_rule(s,95,2)==b
    assert matching_rule(s,85,8) is None
    assert matching_rule(s,75,2) is None


def test_overlapping_rules_choose_higher_priority():
    a=dict(min_price=70,max_price=79,entry_minute_min=5,entry_minute_max=10,
           statistical_yield_percent=-5.0)
    b=dict(min_price=75,max_price=85,entry_minute_min=5,entry_minute_max=10,
           statistical_yield_percent=3.0)
    assert matching_rule(dict(rules=[a,b]),77,8)==b
