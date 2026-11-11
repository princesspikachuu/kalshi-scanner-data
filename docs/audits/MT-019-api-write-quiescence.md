# MT-019 — API write-quiescence gate (OFF by default)

## Why API writes matter

Stopping both background workers does **not** stop all PostgreSQL writes.
The API has authenticated mutation paths for `/collection/campaigns`,
`/paper/strategies`, `/paper/replays`, `/demo/bots`,
`/demo/shadow/bots`, `/demo/shadow/funds`,
`/demo/shadow/folders/{folder}/reset`, `/live/budget`,
`/live/pause` and other live-bot settings. Even ordinary login/challenge
routes mutate session/rate-limit data. Its startup also calls
`seed_live_bots` and `configure_approved_pilot` under normal conditions.

Therefore do not claim `MT_ARCHIVE_WRITERS_STOPPED=true` solely because the
collector and research workers are disabled.

## Proposed guarded recovery-only behavior

`MT_API_RECOVERY_HOLD=true` is an explicit private API environment toggle,
**default OFF**. When enabled in a supported deployment:

- API startup opens the DB connection as usual but skips optional analysis
  inventory, live bot seeding and approved-pilot configuration.
- The HTTP gateway rejects every non-health route with status 503, including
  GET routes that mutate login/rate-limit data, collection changes, demo
  settings, and live controls. It performs this check before executing routes.
- `/health/live` and `/health/ready` stay available for health checks
  (`ready` performs a simple SELECT). No background worker is started by
  this API toggle.
- It does not delete, mutate, pause, reset or restore any saved strategy
  settings or financial history. All normal behavior resumes when the flag
  is OFF.

**Important:** The dashboard and sign-in will be temporarily unavailable
while this API hold is enabled, even though the API service remains healthy.
The flag is a temporary recovery maintenance window, **not** a normal-mode
read-only dashboard. It cannot stop manual SQL commands, other services, or
workers that are not subject to this hold.

## Operator sequence (not performed automatically)

1. Wait until PR's complete CI passes; manually deploy the API through its
   existing Render manual-deployment configuration, verify the exact commit
   and retain `MT_API_RECOVERY_HOLD=false` initially.
2. Keep `pocket-processing-staging` and `pocket-research-staging`
   explicitly recovery-held and not collecting or trading. Document
   successful R2 backup/restore evidence before any maintenance.
3. At an announced temporary API maintenance window, set
   `MT_API_RECOVERY_HOLD=true` *only* on `pocket-api-staging`; verify
   a successful deploy and a 503 on one non-health endpoint, and health
   status on `/health/live`. Do not send authenticated trading requests.
4. Inspect PostgreSQL sessions from private operator context. Low active
   connection counts alone do **not** certify all database writers stopped.
   Check any cron jobs, operator shells, disconnected workers and external
   services separately. This API hold is only one part of writer quiescence.
5. If independent R2/financial verification, actual physical disk/WAL
   headroom, scoped maintenance credential and all writers-stopped checks
   pass, perform only a *small*, manually supervised R2-verified diagnostic
   archive. **Never delete protected financial, order, settlement or live
   control records.** Do not run automatic archival during normal trading.
6. When the recovery operation is finished, reset
   `MT_API_RECOVERY_HOLD=false`, verify the API's sign-in/dashboard
   functionality, and leave paper collection/trading separately disabled
   until the full MT-019 acceptance gates pass.

This code cannot independently guarantee database-wide read-only operation:
the database account retains its existing privileges. For stronger safety,
a separate DB-enforced role/session or isolated maintenance service remains
recommended before longer unattended archival.
