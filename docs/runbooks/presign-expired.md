# Presign expired / upload after TTL

## When

Client upload fails after the presigned URL TTL; API reports cancelled / expired upload; spec scenario: upload after TTL → CANCELLED / re-presign.

## Symptoms

- S3/LocalStack rejects PUT (signature expired / 403).
- Document remains without a successful object; status reflects cancelled or awaiting new upload.
- Clients retry the same URL instead of requesting a fresh presign.

## Diagnosis

1. Confirm wall clock skew on the client.
2. Check API response for expired upload / cancelled document semantics in OpenAPI (`/v1/docs`).
3. Verify bucket policy / LocalStack init still allows the expected key prefix.
4. Rule out IAM `AccessDenied` on an otherwise valid URL (`iam-access-denied.md`).

## Mitigation

1. Issue a new presign: `POST /v1/uploads/presign` (see live OpenAPI at `/v1/docs`).
2. Client PUTs to the **new** URL only; do not log full presigned URLs.
3. If the document was CANCELLED by policy, create a new document or follow product rules for reopen.
4. Educate integrators: treat TTL as hard; clock sync required.

## Exit criteria

Successful PUT; worker receives ObjectCreated; document advances via the state machine.

## Related

- `docs/runbooks/iam-access-denied.md`
- Root `README.md` (presign flow)
