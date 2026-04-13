# Cost Explorer and per-tenant throughput (FinOps)

Stage 3 narrative. No live AWS Cost Explorer API calls required in this environment.

## AWS Cost Explorer (when account exists)

1. Open Cost Explorer → group by tag `Environment` / `CostCenter` / `Owner` / `Project=doc-pipeline`
   (Terraform `default_tags` + module tags — see `terraform/README.md`).
2. Optional: link CUR to Athena for allocation; out of scope for local Stage 3.
3. Monthly review RACI: FinOps Analyst Responsible — `docs/ownership-raci.md`.

Do **not** put long-lived access keys in git to scrape Cost Explorer.

## Application metric (canonical)

| Name (OTel create_counter) | Prom / Collector view | Per-tenant attribute |
|----------------------------|-----------------------|----------------------|
| `documents_processed` | `doc_pipeline_documents_processed_total` | `tenant_slug` |

Also label with `document_type`, `status`. **Never** `document_id`, `correlation_id`, `tenant_id` UUID,
or job UUIDs on metrics (cardinality + PII-adjacent).

Local Grafana/Prom: rate by `tenant_slug` for economics conversations.

## Stage 3 load note

Spec §3.5 peak **5000 docs/h** is exercised **locally** (Task 4 k6) and labelled **local** —
not a contractual SLA and not proof of AWS 99.9%.

## Non-goals

- New metric names for "Stage 3"
- Billing ledger / Stripe-style dual-id economics (anti-copy)
- Fake pen-test or SLA certificate
