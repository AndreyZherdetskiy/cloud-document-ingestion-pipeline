# Incident: queue backlog

## When

Alert **DocPipelineQueueOldestAge**: `doc_pipeline_sqs_queue_oldest_age_seconds > 600` (10 minutes). Distinct from DLQ > 0 (poison) and from idle `rate()` NaN on throughput counters.

## Symptoms

- Grafana **Queue oldest message age** climbing; **Document throughput** flat or falling.
- Possible companion: **Worker down with queue depth** (`DocPipelineWorkerDownWithQueueDepth`).

## Diagnosis

1. Check `doc_pipeline_worker_up` and Compose/ECS worker task health.
2. Check main queue visible depth vs DLQ depth — backlog ≠ poison.
3. Check Postgres / Redis saturation (`DocPipelinePostgresCPUHigh`, connection errors in logs).
4. Inspect recent deploys, LocalStack/AWS API errors, and hook latency histograms.

## Mitigation

1. Scale out workers (Compose replicas locally; ECS desired count / autoscaling on AWS).
2. If workers are crash-looping, roll back task definition / image and follow `stuck-jobs.md`.
3. If data plane is saturated, reduce intake (rate limit / pause presign) temporarily.
4. If DLQ is also non-zero, triage poison separately (`dlq-replay.md`) — do not confuse the two.

## Exit criteria

Oldest age back under 600s for 15+ minutes; throughput recovering; no worker-down-with-depth alert.

## Related

- `docs/slo.md`
- `docs/runbooks/stuck-jobs.md`
- `docs/runbooks/dlq-replay.md`
