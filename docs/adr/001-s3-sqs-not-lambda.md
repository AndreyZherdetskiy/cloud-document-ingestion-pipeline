# ADR-001: S3 → SQS, not direct Lambda trigger

- **Status:** Accepted
- **Date:** 2026-06-15
- **Spec refs:** §4.4, §12 ADR-001

## Context

ObjectCreated events must drive multi-step document processing (virus/OCR/extract) with buffering, redrive, and replay. Direct S3→Lambda couples producers to short-lived handlers and weakens DLQ/replay stories for long hooks.

## Decision

S3 event notifications write to **SQS Standard**; ECS Fargate workers consume the queue. DLQ with `maxReceiveCount=5` and redrive policy. **No Kafka** as the work queue.

## Consequences

- Natural back-pressure and independent scale-out by queue depth.
- Poison messages land in DLQ with CloudWatch alarms and a replay runbook.
- Another managed service to own via Terraform; no global ordering without FIFO (order is per-document via the state machine).

## Alternatives considered

- S3 → Lambda directly — poor fit for long multi-step hooks and redrive.
- S3 → SNS → Lambda — extra hop without solving duration/replay.
- Kafka/MSK only — overkill cost/ops for a document work queue.
