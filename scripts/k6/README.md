# Local peak load (k6) — Stage 3

**Label: local / LocalStack only — not contractual SLA.**

## Math

- Target: **5000 docs/h**
- 5000 / 3600 ≈ **1.389 docs/s**
- k6 `constant-arrival-rate`: `rate: 84`, `timeUnit: '1m'` ≈ 5040/h

## JWT caveat

- API verifies JWT from **`JWT_PUBLIC_KEY_PEM`** (Compose interpolates `.env`; `JWT_PUBLIC_KEY_PATH` is empty — no `public.pem` bind-mount).
- Host minting: `make gen-dev-jwt` writes gitignored `.local/jwt/*.pem` and patches `.env`; then `make mint-jwt` / `AUTH_TOKEN`.
- Recreate the `api` container after rotating keys so Compose re-reads `JWT_PUBLIC_KEY_PEM`.
- Live `POST /v1/documents` returns **401** without a Bearer JWT signed by the matching private key.
- Do **not** commit PEM private keys.

## Run

```bash
# Health-only / honest skip when AUTH_TOKEN unset:
k6 run scripts/k6/peak_5000_docs_h.js

# Authenticated local peak (human-provided token):
AUTH_TOKEN="eyJ..." k6 run scripts/k6/peak_5000_docs_h.js
```

Default `BASE_URL=http://localhost:8000`. When WSL host **`:8000` RST**, run k6 on the Compose network. Docker Desktop on WSL needs a Windows mount path, e.g. `-v "$(wslpath -w "$(pwd)"):/app"`. Example: `docker run --rm --network doc-pipeline -v "$(wslpath -w "$(pwd)"):/app" -w /app grafana/k6 run -e BASE_URL=http://api:8000 scripts/k6/peak_5000_docs_h.js`. With `AUTH_TOKEN` unset the script hits `/v1/health` only (honest skip of create→PROCESSED). S3 PUT uses the API's `presigned_url` plus `required_headers` — do not invent an unsigned bucket URL.
