"""Thread-safe byte-bounded LRU. Only immutable bytes are shared between callers."""
from collections import OrderedDict
from threading import Lock

class ByteCache:
    def __init__(self,maximum):
        if type(maximum) is not int or not 0<=maximum<=32*1024*1024:raise ValueError('Invalid cache budget')
        self.maximum=maximum;self.size=0;self.values=OrderedDict();self.lock=Lock()
    def get(self,key):
        with self.lock:
            value=self.values.get(key)
            if value is not None:self.values.move_to_end(key)
            return value
    def __len__(self):
        with self.lock:return len(self.values)
    def pop(self,key):
        with self.lock:
            value=self.values.pop(key,None)
            if value is not None:self.size-=len(value)
            return value
    def put(self,key,value):
        if not isinstance(key,str) or len(key)>512 or not isinstance(value,bytes) or not 0<len(value)<=self.maximum:return
        with self.lock:
            old=self.values.pop(key,None)
            if old is not None:self.size-=len(old)
            while self.values and (self.size+len(value)>self.maximum or len(self.values)>=4096):
                _,removed=self.values.popitem(last=False);self.size-=len(removed)
            self.values[key]=value;self.size+=len(value)
