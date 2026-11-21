"""Lossless encoding of repeated evidence-manifest references; identities unchanged."""
import re

_WRITE_COMPACT=False

def enable_compact_writes():
    global _WRITE_COMPACT
    _WRITE_COMPACT=True

def decode_scope(value):
    result=dict(value)
    if 'manifest_v1' not in result:return result
    if any(k in result for k in ('manifest_key','manifest_sha256','manifest_bytes')):raise ValueError('Ambiguous manifest encoding')
    manifest=result.pop('manifest_v1')
    if (not isinstance(manifest,list) or len(manifest)!=2 or not isinstance(manifest[0],str)
        or not re.fullmatch('[a-f0-9]{64}',manifest[0]) or type(manifest[1]) is not int or not 1<=manifest[1]<=8*1024*1024):raise ValueError('Invalid compact manifest')
    sha,size=manifest
    result.update(manifest_key=f'raw/v1/research/{sha[:2]}/{sha}.json.gz',manifest_sha256=sha,manifest_bytes=size)
    return result

def encode_scope(value):
    original=decode_scope(value)
    sha=original.get('manifest_sha256');size=original.get('manifest_bytes')
    if not isinstance(sha,str) or original.get('manifest_key')!=f'raw/v1/research/{sha[:2]}/{sha}.json.gz':return original
    compact={k:v for k,v in original.items() if k not in ('manifest_key','manifest_sha256','manifest_bytes')}
    compact['manifest_v1']=[sha,size]
    if decode_scope(compact)!=original:raise ValueError('Manifest round trip changed evidence')
    return compact

def stored_scope(value):return encode_scope(value) if _WRITE_COMPACT else value

def canonical_parameters(value):
    if value.get('collector')=='evidence-v1' and isinstance(value.get('scope'),dict):return dict(value,scope=decode_scope(value['scope']))
    return value
