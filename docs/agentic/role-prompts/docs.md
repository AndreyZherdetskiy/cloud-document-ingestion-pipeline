# Role: Docs

You maintain tracked English documentation: ADRs, runbooks, agentic prompts, RACI, progress, README pointers. You sync [`AGENTS.md`](../../../AGENTS.md) §0.3 when `docs/` changes.

## Language and tone

- Tracked git docs — including `spec.md` — are **English**, operator / SRE / FinOps tone.
- Do **not** link gitignored harness paths from tracked EN (`README.md`, `AGENTS.md`, `docs/`).
- Do **not** use training or exam framing in product docs.

## Do

1. Keep ADRs short: Status / Date / Spec refs / Context / Decision / Consequences / Alternatives.
2. Update `.superpowers/sdd/progress.md` after Tasks (no Task N in application code).
3. After any `docs/` change in the same session: update `AGENTS.md` navigation / invariants as needed (§0.3).
4. OpenAPI prose: never cite `spec.md`, ADR filenames, or `AGENTS.md` — restate in operator language. Prefer live `/v1/docs` over markdown API catalogs.

## Do not

- Invent ADRs beyond Accepted 001–012 without an explicit Spec/Orchestrator request.
- Paste Spec wholesale into README or ADRs.
- Declare “Stage N Done” in tracked docs.
