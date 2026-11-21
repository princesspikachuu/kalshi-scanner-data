"""Single-thread token pacing using exchange-reported budgets and costs."""
import math,time

class Bucket:
    def __init__(self,rate,capacity):
        self.rate,self.capacity=rate,capacity
        self.tokens=0.;self.at=time.monotonic()
    def available(self):
        now=time.monotonic()
        self.tokens=min(self.capacity,self.tokens+max(0,now-self.at)*self.rate);self.at=now
        return self.tokens
    def delay(self,cost):return max(0,(cost-self.available())/self.rate)
    def take(self,cost):self.tokens=max(0,self.available()-cost)

def positive(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<=1e7:
        raise ValueError('Invalid exchange budget')
    return float(value)
