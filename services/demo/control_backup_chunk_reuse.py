"""Optional content-addressed reuse for *unchanged* verified R2 backup parts.

This is a network-write optimization, not partial/delta recovery. New snapshot
roots ALWAYS enumerate every source row in order, and the caller MUST read
back and verify every referenced chunk (new or reused) before catalog/health
publication. The full consistent source snapshot is still staged locally.
"""
import gzip
import hashlib
import json

from services.demo.maintenance import MAX_OBJECT,read_verified

FORMAT='control-snapshot-multipart-v2'
CATALOG_FORMAT='control-snapshot-root-receipt-v1'
PREFIX='demo/backups/'


def _receipt_valid(reference):
    if not isinstance(reference,dict):
        return False
    digest=reference.get('sha256')
    size=reference.get('size')
    return (isinstance(digest,str) and len(digest)==64
            and all(c in '0123456789abcdef' for c in digest)
            and type(size) is int and 1<=size<=MAX_OBJECT
            and reference.get('key')==PREFIX+digest+'.json.gz')


def prior_verified_chunks(store,objects,*,max_parts=100000):
    """Read a previously published *verified* root and recovery catalog.

    Returns no candidates for absent/legacy state. A claimed v2 root or
    catalog that is incomplete or inconsistent must fail closed rather than
    provide unverified receipt lineage.
    """
    health=store.get('backup-health')
    state=health.get('progress') if isinstance(health,dict) else None
    if not isinstance(state,dict) or state.get('verified') is not True or state.get('format')!=FORMAT:
        return {}
    root_reference=state.get('reference')
    catalog_reference=state.get('catalog_reference')
    if not (_receipt_valid(root_reference) and
            isinstance(catalog_reference,dict)
            and _receipt_valid(catalog_reference)
            and catalog_reference['key'].startswith('demo/backups/roots/')):
        # A valid v2 recovery root always has an independently stored receipt.
        raise ValueError('Verified backup reuse catalog unavailable')
    catalog=read_verified(objects,catalog_reference)
    root=read_verified(objects,root_reference)
    if (not isinstance(catalog,dict)
            or catalog.get('format')!=CATALOG_FORMAT
            or catalog.get('root_reference')!=root_reference
            or not isinstance(root,dict) or root.get('format')!=FORMAT
            or type(root.get('records')) is not int
            or root['records']<=0 or root['records']!=state.get('records')
            or root.get('sha256')!=catalog.get('snapshot_sha256')
            or catalog.get('records')!=root['records']
            or not isinstance(root.get('chunks'),list)
            or not 1<=len(root['chunks'])<=max_parts
            or catalog.get('chunks')!=len(root['chunks'])):
        raise ValueError('Verified backup reuse root mismatch')
    refs={}
    for section in root['chunks']:
        if (not isinstance(section,dict)
                or type(section.get('count')) is not int
                or not 1<=section['count']<=200
                or not _receipt_valid(section.get('reference'))):
            raise ValueError('Verified backup reuse part invalid')
        ref=section['reference']
        refs[ref['sha256']]=ref
    return refs


def exact_part_fingerprint(payload):
    """Compute exactly the digest used by maintenance.put_verified.

    Only a single bounded part is compressed in memory. Compression is
    deterministic (gzip mtime=0), so equality implies byte identity with the
    immutable content-addressed archive key.
    """
    body=gzip.compress(json.dumps(payload,separators=(',',':'),default=str).encode(),mtime=0)
    return hashlib.sha256(body).hexdigest(),len(body)


def matching_reference(part,candidates):
    if not candidates:return None
    digest,size=exact_part_fingerprint(part)
    ref=candidates.get(digest)
    if _receipt_valid(ref) and ref['size']==size:
        # Reused objects will be independently fetched and hashed by the
        # caller's complete verify_staged_archive before publishing a root
        # receipt or updating backup-health.
        return ref
    return None
