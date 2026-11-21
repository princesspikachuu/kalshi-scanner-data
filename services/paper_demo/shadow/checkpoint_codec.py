"""Lossless bounded transport for the hot paper checkpoint; legacy JSON remains readable."""
import base64,gzip,hashlib,io,json,time
import msgpack
ENCODING='shadow-checkpoint-gzip-v1'
BINARY_ENCODING='shadow-checkpoint-msgpack-gzip-v1'
MAX_BYTES=64*1024*1024

def reject_extension(code,data):raise ValueError('Unsupported checkpoint value')

def pack_checkpoint(data,threshold=65536,*,binary=False,segments=None,profile=None):
    # encode()/ExperimentSuite.state() supply string-keyed maps, JSON scalars
    # and Decimal amounts. Binary doubles avoid repeatedly formatting research
    # floats as decimal strings; Decimal money still becomes an exact string.
    encoding=BINARY_ENCODING if binary else ENCODING
    if binary:
        def fallback(value):
            if isinstance(value,int):raise OverflowError('Integer exceeds MessagePack capacity')
            return str(value)
        parts=None
        try:
            if segments is not None:
                split_start=time.monotonic() if profile is not None else None
                cold_before=segments.cold_member_compression_ms if profile is not None else None
                parts=segments.parts(data,fallback)
                raw=None
                if profile is not None:
                    # Cold member compression is INCLUDED in segment_pack_ms.
                    # Keep it separately visible to distinguish a cache miss
                    # from ordinary repeated MessagePack traversal.
                    profile['segment_pack_ms']=(time.monotonic()-split_start)*1000
                    profile['cold_member_compression_ms']=(
                        segments.cold_member_compression_ms-cold_before)
            else:raw=msgpack.packb(data,use_bin_type=True,default=fallback)
        except (OverflowError,TypeError,ValueError):
            if profile is not None:profile.clear()
            raw=json.dumps(data,default=str,separators=(',',':')).encode();encoding=ENCODING;parts=None
    else:raw=json.dumps(data,default=str,separators=(',',':')).encode()
    if binary and parts is not None:
        size=sum(len(raw_part) for raw_part,_ in parts)
        if size>MAX_BYTES:raise ValueError('Paper checkpoint exceeds supported capacity')
        if size<threshold:return json.loads(json.dumps(data,default=str))
        hash_started=time.monotonic() if profile is not None else None
        digest=hashlib.sha256()
        for raw_part,_ in parts:digest.update(raw_part)
        if profile is not None:profile['checksum_ms']=(time.monotonic()-hash_started)*1000
        compression_started=time.monotonic() if profile is not None else None
        compressed=b''.join(encoded if encoded is not None else gzip.compress(raw_part,compresslevel=1,mtime=0) for raw_part,encoded in parts)
        if profile is not None:profile['hot_compress_join_ms']=(time.monotonic()-compression_started)*1000
        b64_started=time.monotonic() if profile is not None else None
        encoded_payload=base64.b64encode(compressed).decode()
        if profile is not None:profile['base64_ms']=(time.monotonic()-b64_started)*1000
        return dict(checkpoint_encoding=encoding,bytes=size,sha256=digest.hexdigest(),data=encoded_payload)
    if len(raw)>MAX_BYTES:raise ValueError('Paper checkpoint exceeds supported capacity')
    if len(raw)<threshold:return json.loads(json.dumps(data,default=str)) if encoding==BINARY_ENCODING else json.loads(raw)
    return dict(checkpoint_encoding=encoding,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
        data=base64.b64encode(gzip.compress(raw,compresslevel=1,mtime=0)).decode())

def unpack_checkpoint(data,max_bytes=MAX_BYTES):
    if not isinstance(data,dict) or 'checkpoint_encoding' not in data:return data
    if data.get('checkpoint_encoding') not in (ENCODING,BINARY_ENCODING):raise ValueError('Unsupported checkpoint encoding')
    try:
        size=data['bytes']
        if isinstance(size,bool) or not isinstance(size,int) or not 0<size<=max_bytes:raise ValueError('Checkpoint capacity exceeded')
        payload=data['data']
        if not isinstance(payload,str) or len(payload)>max_bytes*2:raise ValueError('Invalid checkpoint payload')
        encoded=base64.b64decode(payload,validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(encoded)) as stream:raw=stream.read(size+1)
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=data['sha256']:raise ValueError('Checkpoint integrity mismatch')
        value=(msgpack.unpackb(raw,raw=False,strict_map_key=True,max_str_len=max_bytes,max_bin_len=0,
            max_array_len=1000000,max_map_len=1000000,max_ext_len=0,ext_hook=reject_extension)
            if data['checkpoint_encoding']==BINARY_ENCODING else json.loads(raw))
        if not isinstance(value,dict):raise ValueError('Invalid checkpoint state')
        return value
    except (KeyError,TypeError,ValueError,OSError,EOFError) as exc:
        raise ValueError('Invalid compressed paper checkpoint') from exc
