# ADR-006: ECS Fargate, not Lambda-only or EKS

- **Status:** Accepted
- **Date:** 2026-04-08
- **Spec refs:** §5.4, §12 ADR-006

## Context

Pipeline stages have variable duration and need predictable container runtime and long-lived connections. Lambda duration/packaging limits and EKS cluster tax are poor fits for Stage 1 Must.

## Decision

API and workers run on **ECS Fargate**. Local equivalent: Docker Compose `api` + `worker`. **EKS/Kubernetes is not Must** for Stages 1–3.

## Consequences

- Managed containers without cluster control-plane cost.
- Task sizing and autoscaling by queue depth must be right-sized (documented Stage 2).
- Do not add “look bigger” EKS YAML as a Must deliverable.

## Alternatives considered

- Lambda-only — weak for long multi-step hooks and persistent connections.
- EKS — cluster tax and ops surface without Stage 1 KPI payoff.
