"""Lossless bounded transport for the hot paper checkpoint; legacy JSON remains readable."""
import base64,gzip,hashlib,io,json
ENCODING='shadow-checkpoint-gzip-v1'
MAX_BYTES=64*1024*1024

def pack_checkpoint(data,threshold=65536):
    raw=json.dumps(data,default=str,separators=(',',':')).encode()
    if len(raw)>MAX_BYTES:raise ValueError('Paper checkpoint exceeds supported capacity')
    if len(raw)<threshold:return json.loads(raw)
    return dict(checkpoint_encoding=ENCODING,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
        data=base64.b64encode(gzip.compress(raw,compresslevel=1,mtime=0)).decode())

def unpack_checkpoint(data,max_bytes=MAX_BYTES):
    if not isinstance(data,dict) or 'checkpoint_encoding' not in data:return data
    if data.get('checkpoint_encoding')!=ENCODING:raise ValueError('Unsupported checkpoint encoding')
    try:
        size=data['bytes']
        if isinstance(size,bool) or not isinstance(size,int) or not 0<size<=max_bytes:raise ValueError('Checkpoint capacity exceeded')
        payload=data['data']
        if not isinstance(payload,str) or len(payload)>max_bytes*2:raise ValueError('Invalid checkpoint payload')
        encoded=base64.b64decode(payload,validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(encoded)) as stream:raw=stream.read(size+1)
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=data['sha256']:raise ValueError('Checkpoint integrity mismatch')
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('Invalid checkpoint state')
        return value
    except (KeyError,TypeError,ValueError,OSError,EOFError) as exc:
        raise ValueError('Invalid compressed paper checkpoint') from exc
