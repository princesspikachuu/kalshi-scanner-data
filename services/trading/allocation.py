"""Exact-cent budget ceilings shared by planning and execution."""
from decimal import Decimal,ROUND_FLOOR

def allocation(config,basis,cash=None,market=0,bot=0,peers=1):
    d=lambda v:Decimal(str(v))
    bid=d(basis)*d(config['bid_percent'])/100
    market_left=max(Decimal(0),d(basis)*d(config['market_percent'])/100-d(market))
    bot_left=max(Decimal(0),d(basis)*d(config['bot_percent'])/100-d(bot))
    available=min(bid,market_left/max(1,peers),bot_left,d(cash) if cash is not None else d(basis))
    return max(Decimal(0),available)

def contracts(config,price,basis,cash=None,market=0,bot=0,peers=1):
    return max(0,int((allocation(config,basis,cash,market,bot,peers)/Decimal(str(price))).to_integral_value(rounding=ROUND_FLOOR)))
