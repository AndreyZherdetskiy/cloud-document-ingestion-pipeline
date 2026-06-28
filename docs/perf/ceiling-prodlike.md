# Local health RPS ceiling on prod-like overlay (2026-06-28)

Laptop characterization on Docker Compose + LocalStack — **not** spec §10.1 contractual throughput (500–5000 docs/h) and **not** an HTTP health RPS SLA.

## Overlay knobs

| Knob | Value |
|------|-------|
| Compose files | `docker-compose.yml` + `docker-compose.perf.yml` |
| API uvicorn workers | 4 (`--workers 4`) |
| Worker scale | `ingestion-worker` ×2, `processing-worker` ×2 (`make perf-up`; never `--scale api`) |
| `RATE_LIMIT_PER_MINUTE` | `0` (unlimited **on overlay only** — not a production default) |
| API SQLAlchemy pool | `DATABASE_POOL_SIZE=5`, `DATABASE_MAX_OVERFLOW=5` (10 × 4 workers = 40) |
| Worker / stuck-scanner pool | `DATABASE_POOL_SIZE=3`, `DATABASE_MAX_OVERFLOW=2` (5 × 5 processes = 25) |
| Pool budget | **65** checkouts vs Postgres default `max_connections=100` (do not raise `max_connections` as the first lever) |
| SQS receive batch | `SQS_MAX_NUMBER_OF_MESSAGES=10` (process sequentially in-process; DELETE only after durable ACK) |
| OTel | `OTEL_SDK_DISABLED=true` (characterization only) |
| Grafana plugins path | `GF_PATHS_PLUGINS=/etc/grafana/plugins` (off `grafana-data` volume) |

Safe hot-path changes on this overlay (invariants kept): insert-first create with `UNIQUE (tenant_id, idempotency_key)` replay; one engine per asyncio event loop; no `session.refresh()` after create commit; SQS batch ≤10 with per-message commit then delete.

## Commands

```bash
make perf-up
make load-k6-health
# Authenticated create burst (host httpx; mint JWT via scripts/mint_dev_jwt.py — do not pass AUTH_TOKEN into docker run)
make live-demo   # optional single-doc create→PROCESSED wall time
```

k6 stdin on Compose network `doc-pipeline` (`Makefile` `load-k6-health`); script `scripts/k6/ceiling_health_rps.js`.

## Health ceiling (`GET /v1/health`, k6 `ramping-arrival-rate`)

Stages: 50 → 100 → 200 → 400 → 800 iters/s × 15s (`preAllocatedVUs` 50, `maxVUs` 400). Threshold `http_req_failed rate<0.01` with `abortOnFail: false`.

| Metric | Prior overlay (pool 2+1) | This overlay (pool 5+5 / 3+2, insert-first, SQS batch 10) |
|--------|--------------------------|-----------------------------------------------------------|
| Hold / break | **Hold** through 800 iters/s; no break | **Hold** through 800 iters/s; no break |
| `http_reqs` | 17,249; **237.5/s** mean over full ramp | 17,249; **240.6/s** mean (~71.7s observed runtime; early stages dominate the mean). Same planned iteration count: k6 `ramping-arrival-rate` is deterministic for this stage table. |
| Peak stage arrival | ~**800 iters/s** | ~**800 iters/s** (799.98 reported at end of final stage) |
| `http_req_failed` | **0.00%** (0 / 17,249) | **0.00%** (0 / 17,249) |
| `dropped_iterations` | **0** | **0** |
| `http_req_duration` p50 | **1.26 ms** | **1.29 ms** (median) |
| `http_req_duration` p95 | **2.10 ms** | **2.21 ms** |
| `http_req_duration` p99 | **2.73 ms** | not in this k6 summary (p90=1.95 ms; max=76.55 ms) |
| Max VUs used | 2 | 2 |

Spec §10.1 load is **5000 docs/h ≈ 1.39 docs/s** end-to-end, not health RPS. Hundreds of health RPS on a laptop overlay does not imply the pipeline meets docs/h NFR. Health throughput is unchanged in substance: the handler was never the limiter.

## Authenticated create path (`POST /v1/documents`)

Host-only bursts, unique `Idempotency-Key` per request; JWT minted on host (`uv run python scripts/mint_dev_jwt.py` / settings PEM). Do not pass `AUTH_TOKEN` into `docker run`. Confirmed overlay `RATE_LIMIT_PER_MINUTE=0`, API pool 5+5. Omit `X-Correlation-ID` (middleware mints UUIDv7); a v4 UUID in that header is 422.

| Method | Prior overlay | This overlay |
|--------|---------------|--------------|
| Sequential host httpx ~15s | **72.99 POST/s** (1,095 × 201) | **117.68 POST/s** (1,766 × 201, 15.01s) |
| Concurrent host httpx, 32 in-flight ~15s | not measured | **255.92 POST/s** (3,840 × 201, 15.00s) |

Status mix on this overlay: **201** only (0 errors) for both bursts.

Optional single-doc happy path (`make live-demo`): **~3.0 s** wall time create→`PROCESSED` on this overlay (2981 ms including interpreter startup; default `--poll-interval` is **2.0s** — not a steady-state docs/s capacity figure). Prior overlay was ~3.1 s.

Create POST RPS (118 sequential / 256 concurrent on this laptop) far exceeds spec ingest NFR (~1.39 docs/s). End-to-end **docs/s** is still bounded by worker polling, LocalStack SQS notify latency, and per-stage DB work—not by unauthenticated health throughput.

## Primary limiter (one sentence)

On this overlay, **end-to-end docs/h is limited by the worker + LocalStack SQS ingest/processing path** (LocalStack notify latency and per-document hook/DB work even with `MaxNumberOfMessages=10` and competing consumers), while **authenticated create POST** is limited by **per-request INSERT + UNIQUE replay under the documented pool budget**—not by `RATE_LIMIT` (0 on overlay), uvicorn worker count, health-handler capacity, or Postgres `max_connections`.
