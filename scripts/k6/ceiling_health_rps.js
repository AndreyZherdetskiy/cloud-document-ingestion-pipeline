/**
 * Local health RPS ceiling — ramping-arrival-rate on GET /v1/health (no JWT).
 * Label: local characterization, not contractual SLA.
 *
 * Stages: 50 → 100 → 200 → 400 → 800 iters/s × 15s each.
 * Thresholds record break numbers; abortOnFail false — not a CI gate.
 */
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";

export const options = {
  scenarios: {
    health_ceiling: {
      executor: "ramping-arrival-rate",
      startRate: 0,
      timeUnit: "1s",
      preAllocatedVUs: 50,
      maxVUs: 400,
      stages: [
        { target: 50, duration: "15s" },
        { target: 100, duration: "15s" },
        { target: 200, duration: "15s" },
        { target: 400, duration: "15s" },
        { target: 800, duration: "15s" },
      ],
    },
  },
  thresholds: {
    http_req_failed: [{ threshold: "rate<0.01", abortOnFail: false }],
  },
  tags: {
    suite: "health_ceiling_local",
    environment: "local",
  },
};

export function setup() {
  console.log("=== Health RPS ceiling (local characterization — not SLA) ===");
  console.log("BASE_URL=" + BASE_URL);
}

export default function () {
  const res = http.get(`${BASE_URL}/v1/health`, {
    tags: { name: "GET /v1/health" },
  });
  check(res, { "health 200": (r) => r.status === 200 });
}
