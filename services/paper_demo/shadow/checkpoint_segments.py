"""Reuse compression of byte-identical cold state; decoded checkpoint schema is unchanged."""
import gzip
from collections import OrderedDict
import msgpack

class CheckpointSegments:
    def __init__(self,max_bytes=16*1024*1024,max_entries=128,min_bytes=4096):
        self.max_bytes=max_bytes;self.max_entries=max_entries;self.min_bytes=min_bytes
        self.cache=OrderedDict();self.bytes=0;self.hits=0;self.misses=0;self.evictions=0
    @staticmethod
    def descend(path,key):
        if not path:return key=='experiments'
        if len(path)==1:return not str(key).startswith('_')
        if len(path)==2:return key=='strategies'
        if len(path)==3:return True
        if len(path)==4:return key=='scalper'
        return False
    @staticmethod
    def cold(path):
        return (len(path)==2 and path[1] in ('_summary','_comparison') or
            len(path)==3 and path[2]=='model' or
            len(path)==5 and path[4]=='exit_evidence' or
            len(path)==6 and path[4:] == ('scalper','research'))
    def member(self,path,raw):
        old=self.cache.get(path)
        if old is not None and old[0]==raw:
            self.cache.move_to_end(path);self.hits+=1;return old[1]
        self.misses+=1;encoded=gzip.compress(raw,compresslevel=1,mtime=0)
        if old is not None:self.bytes-=len(old[0])+len(old[1]);del self.cache[path]
        size=len(raw)+len(encoded)
        if size<=self.max_bytes and self.max_entries>0:
            while self.cache and (self.bytes+size>self.max_bytes or len(self.cache)>=self.max_entries):
                _,(previous,compressed)=self.cache.popitem(last=False)
                self.bytes-=len(previous)+len(compressed);self.evictions+=1
            self.cache[path]=(raw,encoded);self.bytes+=size
        return encoded
    def parts(self,data,fallback):
        packer=msgpack.Packer(use_bin_type=True,default=fallback);buffer=bytearray();parts=[]
        def walk(value,path=()):
            if self.cold(path):
                raw=packer.pack(value)
                if len(raw)>=self.min_bytes:
                    if buffer:parts.append((bytes(buffer),None));buffer.clear()
                    parts.append((raw,self.member(path,raw)));return
                buffer.extend(raw);return
            if isinstance(value,dict) and len(path)<=5:
                buffer.extend(packer.pack_map_header(len(value)))
                for key,item in value.items():
                    buffer.extend(packer.pack(key))
                    if self.descend(path,key) or self.cold(path+(key,)):walk(item,path+(key,))
                    else:buffer.extend(packer.pack(item))
            else:buffer.extend(packer.pack(value))
        walk(data)
        if buffer:parts.append((bytes(buffer),None))
        return parts
    def metrics(self):
        return dict(hits=self.hits,misses=self.misses,evictions=self.evictions,
            entries=len(self.cache),retained_bytes=self.bytes,max_bytes=self.max_bytes)
