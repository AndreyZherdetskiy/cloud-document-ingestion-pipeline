# DLQ replay (poison messages)

## When

Alert **DocPipelineDLQVisible**: `doc_pipeline_sqs_dlq_visible_messages > 0` (Appendix B #1). Also fire after a planned poison drill.

## Symptoms

- Grafana panel **DLQ depth** non-zero (`docs/grafana/dashboards/pipeline_overview.json`).
- Worker logs show repeated failures for the same payload; main queue may still drain.

## Diagnosis

1. Confirm depth and age metrics in Grafana / Prometheus (`docs/slo.md`).
2. Inspect a sample DLQ message (LocalStack console / AWS SQS console) — do **not** delete yet.
3. Correlate with Jaeger traces and structured logs by `correlation_id` / `document_id` in logs only (never as metric labels).
4. Classify: bad payload, hook stub failure (`stub_virus_clean=false`), IAM/`AccessDenied`, or dependency outage.

## Mitigation

1. Fix the root cause (code, config, IAM, dependency).
2. Replay via Platform Admin: `POST /v1/admin/dlq/replay` (LocalStack-compatible redrive wrapper).
3. Watch main queue age and DLQ depth return to zero.
4. Do not bulk-replay until the fix is verified on one message.

## Policy notes

- Redrive: `maxReceiveCount=5` → `{env}-document-ingestion-dlq` (`infra/localstack/init-aws.sh` locally; Terraform SQS module on AWS).
- Idempotency: duplicate delivery is safe via Redis `SET NX` + terminal status check ([ADR-002](../adr/002-at-least-once-idempotency.md)).
- Ownership: Platform SRE primary / Backend secondary — see `docs/ownership-raci.md`.

## Related

- `docs/runbooks/stuck-jobs.md`
- `docs/runbooks/incident-queue-backlog.md`
- `docs/runbooks/iam-access-denied.md`
