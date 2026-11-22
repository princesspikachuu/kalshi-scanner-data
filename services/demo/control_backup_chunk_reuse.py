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


def _receipt_valid(reference,*,catalog=False):
    if not isinstance(reference,dict):
        return False
    digest=reference.get('sha256')
    size=reference.get('size')
    return (isinstance(digest,str) and len(digest)==64
            and all(c in '0123456789abcdef' for c in digest)
            and type(size) is int and 1<=size<=MAX_OBJECT
            and reference.get('key')==(PREFIX+('roots/' if catalog else '')+digest+'.json.gz'))


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
            and _receipt_valid(catalog_reference,catalog=True)):
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


# Deliberately conservative. The opt-in writer only reuses a prior part if
# today's actual bucket lifecycle has been read successfully and no enabled
# completed-object expiry can affect our backup namespace. This is not a
# substitute for a human audit or recovery test; lifecycle rules can change.
def _lifecycle_expiration_might_touch_backups(rule):
    if not isinstance(rule,dict) or rule.get('Status') not in ('Enabled','Disabled'):
        return True
    if rule['Status']=='Disabled':
        return False
    known={'ID','Status','Filter','Prefix','Expiration',
           'NoncurrentVersionExpiration','AbortIncompleteMultipartUpload',
           'Transitions','NoncurrentVersionTransitions'}
    if set(rule)-known:
        # Unknown future R2 deletion semantics must not be assumed harmless.
        return True
    if not any(name in rule for name in ('Expiration','NoncurrentVersionExpiration')):
        # Abort-incomplete-multipart and storage-class-only rules cannot expire
        # already completed immutable backup objects.
        return False
    if 'Filter' in rule:
        # A valid S3 lifecycle rule has one filter selector at most.
        # Conflicting legacy top-level prefixes must not make a deletion safe.
        selector=rule['Filter']
        if 'Prefix' in rule or not isinstance(selector,dict) or len(selector)>1:
            return True
        if 'Prefix' in selector:
            prefix=selector['Prefix']
        elif 'And' in selector:
            compound=selector['And']
            if (not isinstance(compound,dict) or
                    set(compound)-{'Prefix','Tags',
                                   'ObjectSizeGreaterThan','ObjectSizeLessThan'}):
                return True
            # Other And conditions narrow matching, never expand beyond Prefix.
            prefix=compound.get('Prefix','')
        elif set(selector).issubset({'Tag','ObjectSizeGreaterThan',
                                    'ObjectSizeLessThan'}):
            prefix=''  # Tags/size alone might select any backup object.
        else:
            return True
    else:
        prefix=rule.get('Prefix','')
    if not isinstance(prefix,str):
        return True
    return (PREFIX.startswith(prefix) or prefix.startswith(PREFIX))


def lifecycle_reuse_allowed(objects):
    """Read-only S3 lifecycle gate. Unknown/denied/malformed => full backup.

    No rule IDs, object keys, bucket names, credential/exception strings or
    provider bodies are logged. Only an authoritative absent-configuration
    response or a parsable non-expiring policy permits consideration of reuse.
    """
    try:
        configuration=objects.client.get_bucket_lifecycle_configuration(
            Bucket=objects.bucket)
    except Exception as error:
        response=getattr(error,'response',None)
        reason=response.get('Error',{}) if isinstance(response,dict) else {}
        metadata=response.get('ResponseMetadata',{}) if isinstance(response,dict) else {}
        return (isinstance(reason,dict) and isinstance(metadata,dict)
                and reason.get('Code')=='NoSuchLifecycleConfiguration'
                and metadata.get('HTTPStatusCode')==404)
    if not isinstance(configuration,dict):
        return False
    rules=configuration.get('Rules')
    return (isinstance(rules,list)
            and all(not _lifecycle_expiration_might_touch_backups(rule)
                    for rule in rules))
