"""Bounded immutable JSON archives, independent of any hosted bucket or credential."""
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
import re
import zlib
from typing import Protocol

MAX_COMPRESSED = 8 * 1024 * 1024
MAX_DECODED = 32 * 1024 * 1024
_KEY = re.compile(r'raw/v1/[a-z][a-z0-9_-]{0,63}/[0-9a-f]{2}/([0-9a-f]{64})\.json\.gz\Z')


class ArchiveInvalid(ValueError):
    pass


class ObjectStore(Protocol):
    """Future R2 adapter contract; no unbounded body reads or overwrites.

    put_if_absent returns True when created, False when the key already exists.
    Network failures must raise, never be represented as an existing object.
    get raises for absence/error and enforces max_bytes while streaming the body.
    """
    def put_if_absent(self, key: str, body: bytes, content_type: str) -> bool: ...
    def get(self, key: str, max_bytes: int) -> bytes: ...


def _validate_value(value):
    # Bound nesting before JSON's recursive serializer. Provider JSON keys are strings.
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > 64:
            raise ArchiveInvalid('JSON nesting too deep')
        if isinstance(item, dict):
            if any(not isinstance(k, str) for k in item):
                raise ArchiveInvalid('JSON object keys must be strings')
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ArchiveInvalid('Unsupported JSON value')


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveInvalid('Duplicate JSON key')
        result[key] = value
    return result


def _no_constant(value):
    raise ArchiveInvalid('Nonfinite JSON number')


def decode(body, max_decoded=MAX_DECODED):
    if not isinstance(body, bytes) or len(body) > MAX_COMPRESSED:
        raise ArchiveInvalid('Invalid compressed archive size')
    if type(max_decoded) is not int or not 1 <= max_decoded <= MAX_DECODED:
        raise ArchiveInvalid('Invalid decoded limit')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body), mode='rb') as source:
            raw = source.read(max_decoded + 1)
        if len(raw) > max_decoded:
            raise ArchiveInvalid('Decoded archive too large')
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
        if not isinstance(value, (dict, list)):
            raise ArchiveInvalid('Expected provider object or array')
        _validate_value(value)
        # 1e999 is syntactically legal JSON but decodes to infinity in Python.
        json.dumps(value, allow_nan=False)
        return value
    except (OSError, EOFError, UnicodeError, ValueError, TypeError, RecursionError, zlib.error) as error:
        if isinstance(error, ArchiveInvalid): raise
        raise ArchiveInvalid('Invalid JSON archive') from None


@dataclass(frozen=True)
class PreparedArchive:
    key: str
    sha256: str
    body: bytes
    decoded_bytes: int
    provider: str

    def receipt(self):
        return {'object_key': self.key, 'sha256': self.sha256, 'provider': self.provider,
                'content_type': 'application/gzip', 'byte_length': len(self.body),
                'metadata': {'format': 'json-gzip-v1', 'decoded_bytes': self.decoded_bytes}}


def prepare(provider, value):
    if not isinstance(provider, str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', provider):
        raise ArchiveInvalid('Invalid provider')
    if not isinstance(value, (dict, list)):
        raise ArchiveInvalid('Expected provider object or array')
    _validate_value(value)
    try:
        # Iterative output bounds allocations for large serialized provider responses.
        output = io.BytesIO()
        encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        for part in encoder.iterencode(value):
            chunk = part.encode('utf-8')
            if output.tell() + len(chunk) > MAX_DECODED:
                raise ArchiveInvalid('Decoded archive too large')
            output.write(chunk)
        raw = output.getvalue()
        packed = io.BytesIO()
        with gzip.GzipFile(filename='', mode='wb', fileobj=packed, mtime=0, compresslevel=6) as stream:
            stream.write(raw)
        body = packed.getvalue()
        if len(body) > MAX_COMPRESSED:
            raise ArchiveInvalid('Compressed archive too large')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ArchiveInvalid('Cannot encode provider JSON') from None
    digest = hashlib.sha256(body).hexdigest()
    return PreparedArchive(f'raw/v1/{provider}/{digest[:2]}/{digest}.json.gz', digest, body, len(raw), provider)


def verify(key, body, expected_length=None):
    match = _KEY.fullmatch(key) if isinstance(key, str) else None
    if not match or key.split('/')[3] != match[1][:2]:
        raise ArchiveInvalid('Invalid object key')
    if not isinstance(body, bytes) or len(body) > MAX_COMPRESSED:
        raise ArchiveInvalid('Invalid compressed archive size')
    if expected_length is not None and (type(expected_length) is not int or len(body) != expected_length):
        raise ArchiveInvalid('Archive size mismatch')
    if hashlib.sha256(body).hexdigest() != match[1]:
        raise ArchiveInvalid('Archive checksum mismatch')


class ArchiveStore:
    def __init__(self, objects: ObjectStore):
        self.objects = objects

    def upload(self, provider, payload):
        archive = prepare(provider, payload)
        self.objects.put_if_absent(archive.key, archive.body, 'application/gzip')
        # Read after write also verifies an object that already existed. Only issue
        # a DB checkpoint receipt after exact bytes are durably retrievable.
        body = self.objects.get(archive.key, MAX_COMPRESSED)
        verify(archive.key, body, len(archive.body))
        if body != archive.body:
            raise ArchiveInvalid('Archive evidence mismatch')
        return archive.receipt()

    def read(self, receipt):
        key = receipt['object_key']
        # Reject invalid keys before touching the object store.
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ArchiveInvalid('Invalid object key')
        match = _KEY.fullmatch(key)
        if receipt.get('sha256') != match[1] or receipt.get('provider') != key.split('/')[2]:
            raise ArchiveInvalid('Invalid archive receipt')
        if receipt.get('content_type') != 'application/gzip':
            raise ArchiveInvalid('Invalid archive content type')
        length = receipt.get('byte_length')
        if type(length) is not int or not 0 <= length <= MAX_COMPRESSED:
            raise ArchiveInvalid('Invalid archive receipt size')
        body = self.objects.get(key, MAX_COMPRESSED)
        verify(key, body, length)
        return decode(body)
