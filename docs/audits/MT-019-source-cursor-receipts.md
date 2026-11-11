# MT-019 — Source cursor continuity receipts

The bounded owner-authenticated raw, packed and manifest index page responses
now echo their validated request cursor as `request_cursor`. The manifest
listing also labels `source=manifests` to match the existing pure
`verify_history_page_chain` checker.

These additions prevent later offline readers from having to invent source
request cursors from a response's next cursor. The first request returns a
null request cursor; following requests return the exact validated supplied
cursor, so the chain verifier can reject skipped or repeated pages.

No additional PostgreSQL query, R2 call, credential, background task,
archive/deletion operation, trading or collection action. The existing
`more`, `next_cursor`, `source_keys`, and `manifest_key` fields are
unchanged. This provides **evidence of supplied-page consistency only**:
it does not prove stable database snapshot, exhaustive R2 catalog enumeration,
all-time historical completeness, or financial reconciliation.
