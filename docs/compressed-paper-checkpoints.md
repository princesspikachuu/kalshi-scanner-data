# Compressed paper checkpoints

Hot paper execution state is serialized once and stored in a lossless gzip/base64 envelope above 64 KiB. Wallet balances, deposits, lots, fees, pending actions, RNG state and all experimental research remain intact. Audit events and their checkpoint still commit in the same database transaction.

DemoStore.get('shadow/checkpoint') transparently reads both legacy JSON and encoded checkpoints. Direct engine restoration also accepts the envelope. Unknown encodings, malformed gzip, size violations and checksum mismatches fail closed; no fresh wallet replaces unreadable state. Decoding is bounded by the declared size and a 64 MiB ceiling.

Canonical raw snapshots remain available for session archives and existing callers. No schema, credential, permission, live-trading or retention settings change. Rollbacks must retain the decoder once an encoded checkpoint has been written. Historic events are not compressed or removed by this change.

Operational verification uses shadow_checkpoint_size (decoded/stored bytes), shadow_pipeline_cost (serialization/commit time and backlog), paper_monitoring_capacity, and actual trade audits. Compression is an execution-cost optimization; queue/fill assumptions, exposure controls and profitability thresholds are unchanged.
