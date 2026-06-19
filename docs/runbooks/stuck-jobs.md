# Stuck jobs

## When

Jobs remain in non-terminal statuses longer than expected; queue age high; operators query `GET /v1/jobs?older_than=…` (or equivalent filters). May coincide with **DocPipelineQueueOldestAge** or **DocPipelineWorkerDownWithQueueDepth**.

## Symptoms

- Document status stuck mid-pipeline (e.g. after virus/OCR stub stage).
- Worker not consuming; visibility timeouts recycling the same messages.
- Audit trail stops advancing for affected documents.

## Diagnosis

1. Confirm worker process is up (`doc_pipeline_worker_up`, Compose/ECS).
2. For a sample `document_id`, read status + audit via API; note last `from_status` / `to_status`.
3. Check Redis idempotency keys — a prior crash may have left a key while DB status lagged (handlers must be safe under replay; see ADR-002).
4. Check hook stub config (`STUB_VIRUS_CLEAN`, etc.) and S3 `HeadObject` errors.

## Automated detection

The **stuck-scanner** sidecar (`python -m doc_pipeline.worker.stuck_main`, Compose service `stuck-scanner`) runs an asyncio periodic loop — not Celery, not a second SQS consumer. Each interval it:

1. Marks `PENDING` / `RUNNING` jobs whose `started_at` is older than `STUCK_JOB_OLDER_THAN_SECONDS` (default 30m) as `STUCK`. Already-terminal jobs and jobs already `STUCK` are unchanged (idempotent select filter).
2. Re-enqueues `PROCESS_DOCUMENT` for documents left in `QUEUED` longer than the same threshold — recovery when ingest committed `QUEUED` but the processing-queue `send_message` failed (Task 0). Processing worker duplicate delivery remains safe (Redis NX + terminal short-circuit).

Operators **retry via API only** — `POST /v1/jobs/{job_id}/retry` for `FAILED` / `STUCK` jobs. Do not mutate job or document status with manual SQL.

## Mitigation

1. Restore worker capacity; clear crash loops.
2. Prefer natural redelivery after visibility timeout once the cause is fixed.
3. Operator retry/cancel only through control-plane APIs — never mutate status in the DB by hand.
4. If messages exhausted receives → DLQ, follow `dlq-replay.md` after the fix.

## Exit criteria

Jobs reach terminal statuses; queue age and depth normalize; audit completeness holds for new transitions.

## Related

- `docs/runbooks/incident-queue-backlog.md`
- `docs/runbooks/dlq-replay.md`
- `docs/architecture.md`
