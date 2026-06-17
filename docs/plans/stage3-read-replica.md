# Stage 3 read replica plan (ADR-011)

## Decision reminder

- **No RDS sharding** in Stages 1–3.
- **Status + audit writes only on primary.**
- Read replica serves **list/audit/compliance read** traffic when enabled.

## Application topology (target)

| Traffic | Endpoint |
|---------|----------|
| API writes (status transitions via worker; control-plane creates) | Primary `DATABASE_URL` |
| Worker status + audit commits | Primary only |
| Optional API list/audit GET | Future `DATABASE_READ_URL` → replica (not required to ship Stage 3) |

Eventual consistency: replica lag monitoring is an ops follow-up (CloudWatch `ReplicaLag`).

## Terraform

`terraform/modules/rds`: `var.enable_read_replica` default **false**.
When true, `aws_db_instance` replica with `replicate_source_db = aws_db_instance.this.identifier`.

Do not `terraform apply` without human GO.

## Compose

Optional second Postgres service is **not a Stage 3 gate**. Local demo continues with one Postgres.
If added later for exploration, never send worker writes to it.

## Non-goals

- Aurora global database
- Sharding by `tenant_id`
- Dual-id or schema-per-tenant as “replica alternative”
