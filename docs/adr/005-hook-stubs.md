# ADR-005: Hook stubs with stable interfaces

- **Status:** Accepted
- **Date:** 2026-04-08
- **Spec refs:** §7.6, §12 ADR-005

## Context

Stage 1 must prove ingestion, status machine, IAM, and IaC without blocking on DS/security vendor selection for OCR and antivirus.

## Decision

Define `VirusScanHook`, `OcrHook`, and `ExtractHook` interfaces. Stage 1 ships **deterministic stubs** with the same I/O shape as future Textract/ClamAV (or equivalent) adapters. Real vendors plug in behind the same contracts in Stage 2+.

## Consequences

- Unblocks MVP demo and audit completeness without vendor lock-in.
- “Smart” processing demo is deferred; stubs must still fail/succeed realistically (e.g. virus `clean=false` → FAILED).
- Reviewer rejects skipping the interface in favor of inline vendor SDK calls.

## Alternatives considered

- Ship Textract + ClamAV in MVP — blocks Stage 1 on vendors and cost.
- No hooks — hard to swap later without rewriting the worker.
