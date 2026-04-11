# ADR-013: Cognito swap via TokenVerifier; JWT stub default

- **Status:** Accepted
- **Date:** 2026-04-10
- **Spec refs:** §2.2, §3.4, §7.1; Stage 2 from-zero §12

## Context

Stage 2 runs without a real AWS account or Cognito User Pool in CI and local dev. The API still needs RS256 JWT auth with tenant-scoped RBAC. Stage 1 shipped inline JWT decode in `get_current_principal`; Stage 2 must isolate verification behind a swap-friendly interface before any live Cognito apply.

## Decision

1. **Default `AUTH_BACKEND=stub`.** `StubJwtVerifier` validates RS256 tokens from the dev issuer using `JWT_PUBLIC_KEY_PEM`, `JWT_ISSUER`, and `JWT_AUDIENCE` (claims: `sub`, `tenant_id`, `roles`).
2. **`TokenVerifier` Protocol** with `verify(token) → Principal`. `get_current_principal` delegates to `get_token_verifier(settings).verify(token)`.
3. **Cognito drop-in:** `CognitoJwtVerifier` is a JWKS skeleton documenting claim mapping (`sub`, `custom:tenant_id`, `cognito:groups` → `Principal`). Selecting `auth_backend=cognito` wires the skeleton; JWKS verify is not implemented until a live User Pool exists.
4. **OAuth2 client credentials (M2M) deferred** to the live Cognito phase (User Pool app client + hosted domain). Stage 2 stub JWT covers dev and service tokens; no separate token endpoint in Stage 2.
5. **No Cognito Terraform apply** in this environment. A future `terraform/modules/cognito` module may be added when AWS is available; it is not required for Stage 2 Task 3.

## Consequences

- CI and local dev stay green without AWS; swap path is documented and typed.
- OpenAPI Authorization header: Bearer JWT (RS256); stub issuer locally, Cognito-compatible claims.
- M2M callers must mint stub JWTs in Stage 2; client-credentials flow arrives with live Cognito.
- Reviewer rejects re-inline JWT decode in route handlers or deps.

## Alternatives considered

- **Inline Cognito JWKS in Stage 2** — requires live User Pool; blocked without AWS account.
- **Separate M2M token endpoint in Stage 2** — duplicates Cognito hosted UI / client-credentials; deferred.
- **Keep inline decode in deps** — no swap path; rejected.
