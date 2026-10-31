"""Real botocore request-model stubs; no network or account credentials."""
import base64
import hashlib
import io
import unittest
from unittest.mock import patch

from botocore.exceptions import ClientError, ReadTimeoutError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from services.research.archive import ArchiveInvalid, ArchiveStore, MAX_COMPRESSED, prepare
from services.research.r2 import R2Objects


class R2Tests(unittest.TestCase):
    def setUp(self):
        self.objects = R2Objects.connect(account_id='0' * 32, bucket='test-archives',
                                        access_key_id='stub-access', secret_access_key='stub-secret')
        self.client = self.objects.client
        self.stub = Stubber(self.client)
        self.stub.activate()
        self.addCleanup(self.stub.deactivate)
        self.addCleanup(self.client.close)
        self.archive = prepare('kalshi', {'price_dollars': '0.88', 'markets': []})

    def put_params(self):
        a = self.archive
        return dict(Bucket='test-archives', Key=a.key, Body=a.body,
                    ContentType='application/gzip', ContentLength=len(a.body), IfNoneMatch='*',
                    ContentMD5=base64.b64encode(hashlib.md5(a.body, usedforsecurity=False).digest()).decode())

    def add_get(self, body=None, length=None):
        body = self.archive.body if body is None else body
        stream = StreamingBody(io.BytesIO(body), len(body))
        self.stub.add_response('get_object', {'Body': stream,
                               'ContentLength': len(body) if length is None else length},
                               {'Bucket': 'test-archives', 'Key': self.archive.key})
        return stream

    def test_create_then_readback_issues_verified_receipt(self):
        self.stub.add_response('put_object', {}, self.put_params())
        stream = self.add_get()
        receipt = ArchiveStore(self.objects).upload('kalshi', {'markets': [], 'price_dollars': '0.88'})
        self.assertEqual(receipt, self.archive.receipt())
        self.assertTrue(stream._raw_stream.closed)
        self.stub.assert_no_pending_responses()

    def test_existing_conditional_object_is_verified_and_reused(self):
        self.stub.add_client_error('put_object', 'PreconditionFailed', http_status_code=412,
                                   expected_params=self.put_params())
        self.add_get()
        self.assertEqual(ArchiveStore(self.objects).upload('kalshi',
                         {'price_dollars': '0.88', 'markets': []}), self.archive.receipt())
        self.stub.assert_no_pending_responses()

    def test_conflict_permissions_and_service_errors_are_not_deduplication(self):
        for status, code in [(409, 'ConditionalRequestConflict'), (403, 'AccessDenied'),
                             (503, 'ServiceUnavailable'), (412, 'OtherError')]:
            self.stub.add_client_error('put_object', code, http_status_code=status,
                                       expected_params=self.put_params())
            with self.assertRaises(ClientError):
                self.objects.put_if_absent(self.archive.key, self.archive.body, 'application/gzip')
        self.stub.assert_no_pending_responses()

    def test_missing_object_raises(self):
        self.stub.add_client_error('get_object', 'NoSuchKey', http_status_code=404,
                                   expected_params={'Bucket': 'test-archives', 'Key': self.archive.key})
        with self.assertRaises(ClientError): self.objects.get(self.archive.key, MAX_COMPRESSED)

    def test_timeout_does_not_issue_receipt_or_fallback_write(self):
        with patch.object(self.client, 'put_object', side_effect=ReadTimeoutError(endpoint_url='stub')) as put:
            with self.assertRaises(ReadTimeoutError): ArchiveStore(self.objects).upload('kalshi', {})
            self.assertEqual(put.call_count, 1)

    def test_corrupt_existing_bytes_fail_readback(self):
        self.stub.add_client_error('put_object', 'PreconditionFailed', http_status_code=412,
                                   expected_params=self.put_params())
        stream = self.add_get(b'x' * len(self.archive.body))
        with self.assertRaises(ArchiveInvalid):
            ArchiveStore(self.objects).upload('kalshi', {'price_dollars': '0.88', 'markets': []})
        self.assertTrue(stream._raw_stream.closed)

    def test_oversize_header_rejected_before_body_read_and_stream_closed(self):
        stream = self.add_get(length=MAX_COMPRESSED + 1)
        with patch.object(stream, 'read', wraps=stream.read) as read:
            with self.assertRaises(ArchiveInvalid): self.objects.get(self.archive.key, MAX_COMPRESSED)
            read.assert_not_called()
        self.assertTrue(stream._raw_stream.closed)

    def test_stream_is_bounded_even_if_length_lies(self):
        stream = self.add_get(b'x' * 100, length=1)
        with patch.object(stream, 'read', wraps=stream.read) as read:
            with self.assertRaises(ArchiveInvalid): self.objects.get(self.archive.key, 10)
            read.assert_called_once_with(11)
        self.assertTrue(stream._raw_stream.closed)

    def test_truncated_body_and_read_error_close_stream(self):
        stream = self.add_get(length=len(self.archive.body) + 1)
        with self.assertRaises(ArchiveInvalid): self.objects.get(self.archive.key, MAX_COMPRESSED)
        self.assertTrue(stream._raw_stream.closed)
        stream = self.add_get()
        with patch.object(stream, 'read', side_effect=ReadTimeoutError(endpoint_url='stub')):
            with self.assertRaises(ReadTimeoutError): self.objects.get(self.archive.key, MAX_COMPRESSED)
        self.assertTrue(stream._raw_stream.closed)

    def test_invalid_inputs_fail_without_sdk_operations(self):
        for key in ('../secret', 'https://host', self.archive.key.replace('/' + self.archive.sha256[:2] + '/', '/zz/')):
            with self.assertRaises(ArchiveInvalid): self.objects.get(key, 10)
        for limit in (True, 0, -1, MAX_COMPRESSED + 1):
            with self.assertRaises(ArchiveInvalid): self.objects.get(self.archive.key, limit)
        for body, content_type in [(b'corrupt', 'application/gzip'), (self.archive.body, 'text/plain')]:
            with self.assertRaises(ArchiveInvalid): self.objects.put_if_absent(self.archive.key, body, content_type)

    def test_connect_requires_explicit_valid_config_before_constructing_client(self):
        base = dict(account_id='0' * 32, bucket='test-archives',
                    access_key_id='stub-access', secret_access_key='stub-secret')
        with patch('services.research.r2.boto3.client') as client:
            for change in ({'account_id': 'https://other'}, {'bucket': '../other'},
                           {'access_key_id': ''}, {'secret_access_key': None}):
                with self.assertRaises(ValueError): R2Objects.connect(**{**base, **change})
            client.assert_not_called()

    def test_sdk_serializes_conditional_header_and_has_bounded_retry_config(self):
        # Stubber checks models; serialization checks the actual HTTP header too.
        operation = self.client.meta.service_model.operation_model('PutObject')
        request = self.client._serializer.serialize_to_request(self.put_params(), operation)
        self.assertEqual(request['headers']['If-None-Match'], '*')
        config = self.client.meta.config
        self.assertEqual(config.retries['total_max_attempts'], 3)
        self.assertEqual((config.connect_timeout, config.read_timeout), (5, 10))
        self.assertEqual(config.request_checksum_calculation, 'when_required')
        self.assertEqual(self.client.meta.endpoint_url,
                         'https://' + '0' * 32 + '.r2.cloudflarestorage.com')
