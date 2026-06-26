# Local peak load (k6) — Stage 3

**Label: local / LocalStack only — not contractual SLA.**

## Math

- Target: **5000 docs/h**
- 5000 / 3600 ≈ **1.389 docs/s**
- k6 `constant-arrival-rate`: `rate: 84`, `timeUnit: '1m'` ≈ 5040/h

## JWT caveat

- API mounts **public key only**.
- Host file comes from `make gen-dev-jwt` (gitignored JWT files); run it and recreate `api` so the mounted key matches your minted tokens.
- Container env: `JWT_PUBLIC_KEY_PATH` = `/keys/jwt/public.pem` (Compose bind-mounts host `JWT_PUBLIC_KEY_FILE` onto that path).
- `.env` `JWT_PUBLIC_KEY_PEM` stub is not what the API container uses.
Live `POST /v1/documents` returns **401** without a Bearer JWT signed with the matching private key (`make mint-jwt` or `AUTH_TOKEN`).
Do **not** commit PEM private keys.

## Run

```bash
# Health-only / honest skip when AUTH_TOKEN unset:
k6 run scripts/k6/peak_5000_docs_h.js

# Authenticated local peak (human-provided token):
AUTH_TOKEN="eyJ..." k6 run scripts/k6/peak_5000_docs_h.js
```

Default `BASE_URL=http://localhost:8000`. When WSL host **`:8000` RST**, run k6 on the Compose network instead, e.g. `docker run --rm --network doc-pipeline -v "$(pwd):/app" -w /app grafana/k6 run -e BASE_URL=http://api:8000 -e AUTH_TOKEN=... scripts/k6/peak_5000_docs_h.js`. S3 PUT uses the API's `presigned_url` plus `required_headers` — do not invent an unsigned bucket URL.
