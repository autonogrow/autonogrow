# Backend pre-pilot robustness audit (Sprint 10B-7)

## Scope and evidence

The audit was performed against initial HEAD `3b9a7c71cf1b90137a15557caec1e1ad4af367a7`.
It covered Owner and Admin collections, bookings, customer identity/home, conversations,
Instagram content and assets, persistent queues, maintenance, storage, audit data, indexes,
rate limiting and migrations. No external provider was called and no worker or publisher was
enabled.

Measured findings:

- `GET /api/owner/businesses` used 10 SQL statements for one business and 181 for 20.
- Conversation previews repeated integration, plan, channel-control, unread and WhatsApp-window
  queries for every row. The WhatsApp window also loaded the complete inbound history.
- Admin customers, message outbox, review requests, public businesses, Instagram raw/content/job
  history, suggestions and channel candidates returned growing collections without a server cap.
- Lazy default creation was protected by unique constraints, but a concurrent loser could still
  surface `IntegrityError`. Customer account linking had the same check-then-insert race.
- The in-memory rate limiter expired timestamps inside the active key only; inactive client keys
  remained forever.
- Booking attachment upload read the complete body before checking its size and could leave files
  behind when a later item in the same batch failed.
- Retention maintenance returned zero in dry-run instead of the number of terminal rows selected.
- There was no unified DB/filesystem reconciliation for managed uploads.

After the change, Owner uses seven SQL statements for both one and 20 businesses. Conversation
preview enrichment is also constant for one or 20 rows. Tests assert controlled growth rather
than an exact implementation-specific statement sequence.

## Classification

### Resolved previously

- Customer Home joins each booking to its business, returns three recent services and constrains
  calendar queries to at most 62 days.
- Conversation collection pagination was already `limit=50`, maximum 100, with offset and total.
- Opportunity, growth-signal and social-proposal collection limits were already capped at 250.
- Booking availability/calendar queries already had bounded ranges and composite hot-path indexes.
- Webhook inbox, channel outbox, Meta jobs and Instagram publish jobs already had idempotency keys,
  bounded attempts, terminal/dead-letter states, expiring claims and bounded backoff.
- Webhook payload limits, sanitised operational errors and secret-safe audit metadata remain in
  place. No token, OAuth code, signature or cookie logging was found in the audited paths.
- Raw asset association protection, final provenance and tenant-scoped IDOR behaviour were already
  covered by tests.
- Image uploads for branding and Instagram already used MIME/signature checks, empty-file checks
  and `max + 1` bounded reads.
- Customer identity constraints already enforce one link per customer and one customer per
  user/business. Existing lookup indexes and booking composite indexes cover pilot hot paths.
- Alembic has one head (`20260821_22`); historical revisions were not edited.

### Corrected in 10B-7

- Owner businesses: compatible list response, default 100, maximum 200, offset, aggregate metrics
  and fixed query growth.
- Public businesses and Admin customers: default 100, maximum 200, offset.
- Admin message/review histories: default 200, maximum 500, offset.
- Instagram raw assets: default 100, maximum 200, offset. Content: default 200, maximum 500,
  offset. Publish history and audit events: default 100, maximum 200.
- Conversation suggestions and Instagram/WhatsApp approval candidates: default 100, maximum 200.
- Conversation previews: batched integration/settings/control/unread/latest-inbound context.
- Default templates, automation settings/rules and customer identity links: SQLite/PostgreSQL
  conflict-safe inserts followed by authoritative reads.
- Rate limiter: periodic TTL pruning plus a hard 10,000-key bound.
- Booking attachments: bounded reads, validate-complete-batch-before-write and rollback cleanup.
- Maintenance dry-run now reports actual terminal queue and heartbeat candidates.
- Managed storage reconciliation was added to the existing maintenance command.

### Partial or deferred

- Service, staff, availability exception and attachment lists are business/booking scoped and
  operationally small for pilots, but do not expose pagination. Add pagination before tenants can
  configure these in bulk.
- Summary endpoints for active growth signals and social proposals do not return collections, but
  still aggregate rows in Python. Move these aggregates to SQL if pilot volumes show pressure.
- Audit logs, conversations/messages, bookings, reviews and publication evidence grow indefinitely.
  They require legal/product retention decisions; this sprint does not delete them.
- The rate limiter is suitable only for a single application process. A shared limiter is required
  before horizontal scaling.
- SQLite concurrency tests cover deterministic conflict behaviour. PostgreSQL concurrency and load
  remain part of staging/integral QA.

## Storage reconciliation

Run a report only:

```text
python scripts/run_maintenance.py --task storage-reconciliation --json
```

The storage task is deliberately excluded from the default scheduled maintenance task set. It scans
only AutonoGrow-managed namespaces:

- `_instagram_content` for raw/final assets and deletion staging;
- `businesses` for logo/gallery media;
- legacy booking-attachment paths matching `<business>/<numeric-booking-id>/...`.

The report contains `orphan_files` (file without DB reference), `missing_files` (DB reference without
file), invalid DB paths, symlinks/invalid storage paths and `cleanup_candidates`. Missing files are
reported and never fabricated or hidden. Absolute paths, traversal outside the configured uploads
root and symlinks are rejected.

Cleanup requires both an explicit task and `--apply`:

```text
python scripts/run_maintenance.py --task storage-reconciliation --apply --json
```

Only unreferenced regular files older than 24 hours are candidates. References are read again before
unlinking to narrow the upload/reconciliation race. Referenced raw assets, final provenance,
publication versions, gallery/logo media and customer booking attachments are never selected. Take a
database/uploads backup before applying and retain the JSON report with the operational change.

## Retention classification

`SAFE_TO_CLEAN` with existing criteria:

- processed/ignored/cancelled webhook inbox rows older than configured retention;
- sent/cancelled channel outbox rows older than configured retention;
- stopped/error worker heartbeats older than configured retention;
- expired OAuth/embedded-signup attempts through the existing credential-destroying cleanup;
- storage orphans that pass namespace, path, reference and 24-hour grace checks.

`REQUIRES_POLICY`:

- audit logs, conversation messages, assisted-delivery records, review requests;
- Instagram publish attempts/history and Meta integration job history;
- superseded customer memory, growth history and accepted/resolved proposals;
- old customer uploads, raw/final assets and signed-delivery metadata.

`MUST_RETAIN_OR_UNKNOWN`:

- bookings and attribution, customer/account identity links, business/user membership history;
- audit/security evidence, financial/automation credit transactions and publication evidence.

## Operational notes

- Use maintenance dry-run output before every cleanup. `--apply` is never implied.
- Monitor dead-letter/action-required counts and expired claims through Owner queue/health views.
- Keep workers and Instagram publisher disabled until their existing deployment gates are approved.
- Before multi-instance deployment, add a distributed limiter and run PostgreSQL contention/load
  testing. Before broad production, approve retention periods with legal/product owners.
- No database migration or speculative index was added. Existing constraints/indexes cover the
  measured queries; bounded collections and aggregate query changes removed the demonstrated load.
