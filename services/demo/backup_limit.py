"""Fixed, non-sensitive categories for capacity-only backup diagnostics.

Never attach control rows, environment values, SQL, credentials, or exception
messages to log fields. Failing a capacity gate cannot publish a partial backup.
"""

BACKUP_SCOPES=frozenset({
    'demo_bots','demo_open_orders','shadow_folders','shadow_bots',
    'paper_resting','paper_positions','paper_open_orders',
    'live_bots','live_orders','live_writes','live_onboarding_ops',
    'singletons',
})


class BackupSnapshotLimit(ValueError):
    """Bounded counter-only explanation of a rejected consistent snapshot."""

    def __init__(self, kind, scope, records, staged_bytes, limit):
        if (kind not in ('rows','bytes') or scope not in BACKUP_SCOPES
                or any(type(v) is not int or v < 0 for v in
                       (records, staged_bytes, limit))):
            raise ValueError('Invalid control backup capacity diagnostic')
        # Preserve the existing safe ValueError contract for compatibility.
        super().__init__('Spool size budget exceeded; no partial backup published')
        self.kind=kind
        self.scope=scope
        self.records=records
        self.staged_bytes=staged_bytes
        self.limit=limit
