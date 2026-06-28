# Performance evidence

Recorded load-test results for operator review. Laptop numbers describe **local characterization** on Compose/LocalStack — not spec §10.1 contractual throughput (500–5000 docs/h) and not HTTP health RPS as an SLA.

| Scenario | Document |
|----------|----------|
| Prod-like overlay health RPS ceiling (`GET /v1/health`, k6 `ramping-arrival-rate`) | [ceiling-prodlike.md](./ceiling-prodlike.md) |
| Stage 3 local peak ≈ 5000 docs/h (`constant-arrival-rate`, create→presign→PUT when `AUTH_TOKEN` set) | [scripts/k6/README.md](../../scripts/k6/README.md) |

Run health ceiling via `make load-k6-health` (stdin k6 on Compose network `doc-pipeline`). Overlay: `make perf-up` before measuring.
