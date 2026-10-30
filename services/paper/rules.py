"""Shared entry-rule selection for historical and live paper accounts.

Multiple price/time squares form one saved strategy. The first matching
rule with the highest saved reference priority wins; one order per market
is still enforced by each engine's attempted-order ledger.
"""

def entry_rules(strategy):
    return strategy.get('rules') or [strategy]


def matching_rule(strategy, ask_cents, minutes_remaining):
    matches = [
        rule for rule in entry_rules(strategy)
        if rule['entry_minute_min'] < minutes_remaining <= rule['entry_minute_max']
        and rule['min_price'] <= ask_cents <= rule['max_price']
    ]
    return max(matches, key=lambda rule: (
        rule.get('statistical_yield_percent', strategy.get('statistical_yield_percent', 0)),
        -rule['entry_minute_max'],
    ), default=None)


def entry_description(strategy):
    rules = entry_rules(strategy)
    return '; '.join(
        f"{r['min_price']}-{r['max_price']}c ask / "
        f">{r['entry_minute_min']} through {r['entry_minute_max']} min"
        for r in rules
    )
