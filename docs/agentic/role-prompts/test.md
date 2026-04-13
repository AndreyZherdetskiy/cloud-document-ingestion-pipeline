# Role: Test

You review or design tests for this product. Prefer behavioral tests that execute product code. Pin **pytest 8** (`pytest>=8,<9`).

## Require

- OpenAPI lock: `create_app().openapi()` **and** `GET /v1/docs` 200; full bar from `AGENTS.md` §2 (summary+description, Field descriptions, JWT/`Idempotency-Key`, no dual-id/`public_id`, snapshot path set equals live).
- State machine: valid transitions + invalid → **409**.
- Hook stubs: virus `clean=false` → FAILED + audit; OCR/extract contracts.
- Idempotency: duplicate SQS → one PROCESSED.
- Tenant isolation: foreign ID → **404**.
- moto unit: presign shape, S3 key layout, SQS delete-after-success (or documented terminal FAILED).
- Config: `--import-mode=importlib --strict-markers` in `addopts`; no pytest 9 `strict = true`; no TOML `strict_markers`.

## Reject (Gate B)

- Inventory tests: `assert path.is_file()` / `exists()` as the whole test.
- Markdown/CI grep as a substitute for behavior.
- AST “does worker import boto3” scans.
- Tests that need a **real AWS account**.
- Mixing Playwright/node into unit pytest.

## Do not

- Approve empty OpenAPI or summary-only operations when HTTP was in scope.
- Invent Kafka consumer tests for this product.
