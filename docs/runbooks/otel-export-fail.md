# OTel export failure

## When

Metrics/traces stop appearing in Grafana / Prometheus / Jaeger; Collector logs show export errors; apps log OTLP failures. Local backends are Prometheus + Grafana + **Jaeger** (not Tempo).

## Symptoms

- Grafana panels empty while traffic exists (after ruling out idle `rate()` NaN).
- Jaeger UI shows no new traces for `doc-pipeline-api`, `doc-pipeline-ingestion-worker`, or `doc-pipeline-processing-worker`.
- Collector cannot scrape or export; `OTEL_SDK_DISABLED` accidentally true.

## Diagnosis

1. Confirm Compose services: `otel-collector`, `prometheus`, `grafana`, `jaeger` (`make observability-up` when Docker is available).
2. Check app Settings: `OTEL_EXPORTER_OTLP_ENDPOINT` points at the Collector (`4317`/`4318`); apps must **not** scrape themselves with `prometheus_client`.
3. Read Collector config `infra/otel/collector.yaml` — exporters must include Prometheus + Jaeger OTLP; **no Tempo**.
4. Verify Prometheus scrapes `otel-collector:8889` (`infra/prometheus/prometheus.yml`).

## Mitigation

1. Restart Collector after config fixes; confirm OTLP ports published.
2. Fix endpoint / TLS / docker network DNS (`doc_pipeline` network).
3. If SDK was disabled via empty/true env, correct `.env` (empty string must not break bool parsing).
4. Do not dual-export to CloudWatch PutMetricData from the app — use ADOT on the AWS path only.

## Exit criteria

New series appear in Prometheus; Grafana overview dashboard updates; Jaeger shows `doc-pipeline-api` → `doc-pipeline-ingestion-worker` → `doc-pipeline-processing-worker` spans under load (`ingest.handle_message`, `process.handle_message`).

## Related

- `docs/slo.md`
- `docs/architecture.md`
- Root `README.md` (observability ports)
