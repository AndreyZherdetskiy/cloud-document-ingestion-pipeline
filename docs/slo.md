# Service level objectives (Stage 1 local + AWS path)

Metric names below are the **Prometheus / OTel** series used locally. AWS CloudWatch alarms (Terraform `cloudwatch` module) mirror the same conditions with native metrics — see Appendix B in `spec.md`.

## Cardinality rules

Allowed metric attributes: `tenant_slug`, `document_type`, `status`, `hook`, `http_response_status_code`, `service`.

Never attach `document_id`, `correlation_id`, `job_id`, or raw object keys to metrics (high cardinality). Use logs/traces (Jaeger) for those.

Traces: **Jaeger** locally (not Tempo). AWS path: X-Ray via ADOT.

## Metrics (canonical names)

| Metric | Type | Meaning |
|--------|------|---------|
| `doc_pipeline_documents_processed_total` | counter | Documents reaching a terminal / counted outcome; label with `tenant_slug`, `document_type`, `status` |
| `doc_pipeline_hook_duration_milliseconds` | histogram | Hook latency (`hook` = virus / ocr / extract) |
| `doc_pipeline_sqs_dlq_visible_messages` | gauge | DLQ `ApproximateNumberOfMessagesVisible` |
| `doc_pipeline_sqs_queue_oldest_age_seconds` | gauge | Main queue `ApproximateAgeOfOldestMessage` |
| `doc_pipeline_sqs_queue_visible_messages` | gauge | Main queue visible depth |
| `doc_pipeline_http_server_requests_total` | counter | API request count by `http_response_status_code` (local ALB 5xx substitute) |
| `doc_pipeline_postgres_cpu_percent` | gauge | Local substitute for RDS `CPUUtilization` |
| `doc_pipeline_worker_up` | gauge | `1` if worker process healthy; local substitute for ECS `RunningTaskCount` |

Apps export **OTLP only** to the Collector. Scraping Prometheus targets the Collector exporter (`otel-collector:8889`), not the apps.

## SLI → SLO

| SLI | How measured | Stage 1 SLO (local / design target) |
|-----|--------------|----------------------------------|
| Ingestion throughput | `rate(doc_pipeline_documents_processed_total[5m])` | Sustain **500 docs/h** in a local load note (not a contractual SLA) |
| Stage 3 local peak (design target) | k6 against local/LocalStack (`scripts/k6/peak_5000_docs_h.js`) | **~5000 docs/h** local only — see `docs/runbooks/cost-explorer-finops.md`; not contractual SLA |
| End-to-end latency proxy | `doc_pipeline_sqs_queue_oldest_age_seconds` | P50 pipeline latency goal ≤ **15 min** (queue age is the Stage 1 proxy) |
| Poison isolation | `doc_pipeline_sqs_dlq_visible_messages` | DLQ depth **= 0** in steady state; any > 0 is actionable |
| API availability | 5xx rate from `doc_pipeline_http_server_requests_total` | **5xx rate ≤ 1%** over 5 minutes |
| Data-plane capacity | Postgres CPU substitute + worker up vs queue depth | Postgres CPU ≤ **80%**; no “worker down with depth” |

Tenant economics and FinOps use `documents_processed` **per `tenant_slug`**, never per UUID.

FinOps: Cost Explorer tags + `documents_processed` by `tenant_slug` — `docs/runbooks/cost-explorer-finops.md`.

## Alert thresholds (local Prometheus)

Aligned with Appendix B and `infra/prometheus/alerts.yml`:

1. **DLQ > 0** — `DocPipelineDLQVisible` → `docs/runbooks/dlq-replay.md`
2. **Oldest message age > 10m (600s)** — `DocPipelineQueueOldestAge` → `docs/runbooks/incident-queue-backlog.md`
3. **API 5xx rate > 1% (5m)** — `DocPipelineAPI5xxRate`
4. **Postgres CPU > 80% (10m)** — `DocPipelinePostgresCPUHigh` (RDS substitute)
5. **Worker up = 0 and queue depth > 0** — `DocPipelineWorkerDownWithQueueDepth` (ECS substitute)

Grafana dashboard: `docs/grafana/dashboards/pipeline_overview.json` (`uid`: `doc-pipeline-overview`). Local UI: `http://localhost:3000`. Jaeger: `http://localhost:16686`.
