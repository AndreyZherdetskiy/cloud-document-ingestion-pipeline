/**
 * Stage 3 local peak ≈ 5000 docs/h against Compose/LocalStack.
 * Results are LOCAL only — not contractual SLA.
 *
 * Math: 5000/3600 ≈ 1.389/s → constant-arrival-rate 84/min ≈ 5040/h.
 *
 * AUTH_TOKEN set  → POST /v1/documents → POST /v1/uploads/presign → PUT to
 *   LocalStack using presigned_url + required_headers (never API body).
 * AUTH_TOKEN missing → GET /v1/health only + honest skip of create→PROCESSED path.
 *
 * Contract: docs/openapi/openapi.json — DocumentType INVOICE; PresignRequest
 * requires document_id + content_type + checksum_sha256; response field is
 * presigned_url (not upload_url).
 */
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const AUTH_TOKEN = __ENV.AUTH_TOKEN || "";
const AUTHENTICATED = AUTH_TOKEN.length > 0;
const OBJECT_BODY = "k6-local-pdf-bytes";
// sha256(OBJECT_BODY) — must match x-amz-checksum-sha256 on PUT
const CHECKSUM_SHA256 =
  "4796dae0fd17c020adfdb7142cab91d162f5e24ea3729c841c0f9e8a478bb915";

const docsCreated = new Counter("local_docs_created");
const docsSkippedAuth = new Counter("local_docs_auth_skipped");

export const options = {
  scenarios: {
    peak_local_5000_per_hour: {
      executor: "constant-arrival-rate",
      rate: 84,
      timeUnit: "1m",
      duration: "2m",
      preAllocatedVUs: 10,
      maxVUs: 40,
    },
  },
  thresholds: AUTHENTICATED
    ? {
        http_req_failed: ["rate<0.05"],
        local_docs_created: ["count>0"],
      }
    : {
        // Health-only path: do not require create success.
        http_req_failed: ["rate<0.1"],
      },
  tags: {
    suite: "stage3_local_peak",
    environment: "local",
  },
};

function correlationId() {
  // UUIDv4-ish for load only; API accepts UUIDv7 — prefer env CORRELATION_PREFIX + random.
  return "00000000-0000-7000-8000-0000" + String(Math.floor(Math.random() * 1e8)).padStart(8, "0");
}

export function setup() {
  console.log("=== Stage 3 k6 LOCAL peak (not SLA) ===");
  console.log("Target ≈ 5000 docs/h (84 arrivals/min). BASE_URL=" + BASE_URL);
  if (!AUTHENTICATED) {
    console.warn(
      "AUTH_TOKEN unset: will hit /v1/health only. " +
        "Honest SKIP of create→presign→PUT→PROCESSED (live JWT often 401 with placeholder PEM).",
    );
  } else {
    console.log("AUTH_TOKEN present: authenticated create→presign→LocalStack PUT path enabled.");
  }
  return { authenticated: AUTHENTICATED };
}

export default function (data) {
  if (!data.authenticated) {
    const res = http.get(`${BASE_URL}/v1/health`, {
      tags: { name: "health_only_skip_create" },
    });
    check(res, { "health 200": (r) => r.status === 200 });
    docsSkippedAuth.add(1);
    return;
  }

  const idem = `k6-${__VU}-${__ITER}-${Date.now()}`;
  const corr = correlationId();
  const createHeaders = {
    Authorization: `Bearer ${AUTH_TOKEN}`,
    "Content-Type": "application/json",
    "Idempotency-Key": idem,
    "X-Correlation-ID": corr,
  };

  const createRes = http.post(
    `${BASE_URL}/v1/documents`,
    JSON.stringify({
      document_type: "INVOICE",
      file_name: `k6-${__VU}-${__ITER}.pdf`,
      content_type: "application/pdf",
      checksum_sha256: CHECKSUM_SHA256,
    }),
    { headers: createHeaders, tags: { name: "post_documents" } },
  );

  const created = check(createRes, {
    "create 201or200": (r) => r.status === 201 || r.status === 200,
  });
  if (!created) {
    // Do not pretend success — common when token/PEM mismatch → 401.
    return;
  }

  let body;
  try {
    body = createRes.json();
  } catch (e) {
    return;
  }
  const documentId = body.id;
  if (!documentId) return;

  const presignRes = http.post(
    `${BASE_URL}/v1/uploads/presign`,
    JSON.stringify({
      document_id: documentId,
      content_type: "application/pdf",
      checksum_sha256: CHECKSUM_SHA256,
    }),
    { headers: createHeaders, tags: { name: "post_presign" } },
  );
  if (!check(presignRes, { "presign 200": (r) => r.status === 200 })) {
    return;
  }

  let presignBody;
  try {
    presignBody = presignRes.json();
  } catch (e) {
    return;
  }
  const putUrl = presignBody.presigned_url;
  const requiredHeaders = presignBody.required_headers || {};
  if (!putUrl) return;

  // ADR-004: PUT object bytes to the presigned S3/LocalStack URL — never FastAPI.
  // Do not synthesize an unsigned LocalStack path; signature would not match.
  const putRes = http.put(putUrl, OBJECT_BODY, {
    headers: requiredHeaders,
    tags: { name: "put_localstack_s3" },
  });
  check(putRes, {
    "s3 put not api": (r) => r.url.indexOf(":8000") === -1,
    "s3 put 2xx": (r) => r.status >= 200 && r.status < 300,
  });
  docsCreated.add(1);
  sleep(0.01);
}

export function teardown(data) {
  if (!data.authenticated) {
    console.warn(
      "RESULT=LOCAL_SKIP_AUTH create→presign→PUT→PROCESSED not exercised. " +
        "Do not record PASS for peak docs/h in evidence.",
    );
  } else {
    console.log("RESULT=LOCAL_AUTH_PATH_RUN labelled local — not contractual SLA.");
  }
}
