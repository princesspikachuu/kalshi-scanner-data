"""Explicitly configured R2 S3 archive adapter. Importing performs no I/O."""
import base64
import hashlib
import re

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .archive import ArchiveInvalid, MAX_COMPRESSED, validate_key, verify


class R2Objects:
    """Narrow ObjectStore: no overwrite, delete, bucket creation or public URLs.

    Inject an S3 client for tests, or use connect() with explicit runtime secrets.
    Never log SDK exceptions or client configuration containing credentials.
    """
    def __init__(self, client, bucket):
        if not isinstance(bucket, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket):
            raise ValueError('Invalid archive bucket')
        self.client = client
        self.bucket = bucket

    @classmethod
    def connect(cls, *, account_id, bucket, access_key_id, secret_access_key):
        # No ambient AWS profile/metadata credential lookup, arbitrary endpoint,
        # bucket provisioning or automatically installed hooks.
        if not isinstance(account_id, str) or not re.fullmatch(r'[0-9a-f]{32}', account_id):
            raise ValueError('Invalid R2 account ID')
        if any(not isinstance(v, str) or not v.strip() for v in (access_key_id, secret_access_key)):
            raise ValueError('Explicit R2 credentials required')
        store = cls(None, bucket)
        store.client = boto3.client(
            's3', endpoint_url=f'https://{account_id}.r2.cloudflarestorage.com',
            region_name='auto', aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version='s3v4', connect_timeout=5, read_timeout=10,
                          retries={'mode': 'standard', 'total_max_attempts': 3},
                          s3={'addressing_style': 'path'},
                          request_checksum_calculation='when_required',
                          response_checksum_validation='when_required'))
        return store

    def put_if_absent(self, key, body, content_type):
        verify(key, body)
        if content_type != 'application/gzip':
            raise ArchiveInvalid('Invalid archive content type')
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=body, ContentType=content_type,
                ContentLength=len(body),
                ContentMD5=base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode('ascii'),
                IfNoneMatch='*')
        except ClientError as error:
            # Only an explicit precondition failure means the object exists.
            # Timeouts, 409 conflicts, denied access and 5xx must propagate.
            if (error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') == 412
                    and error.response.get('Error', {}).get('Code') == 'PreconditionFailed'):
                return False
            raise
        return True

    def get(self, key, max_bytes):
        validate_key(key)
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_COMPRESSED:
            raise ArchiveInvalid('Invalid object read limit')
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        stream = response['Body']
        try:
            size = response.get('ContentLength')
            if type(size) is not int or not 0 <= size <= max_bytes:
                raise ArchiveInvalid('Invalid object size')
            body = bytearray()
            while True:
                chunk = stream.read(min(64 * 1024, max_bytes + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ArchiveInvalid('Object too large')
            if len(body) != size:
                raise ArchiveInvalid('Object size mismatch')
            result = bytes(body)
            verify(key, result, size)
            return result
        finally:
            stream.close()
