// api.js — thin wrapper around the AgAI-33 dispatch API.
// Base URL is configurable so the same static bundle works against
// local dev (uvicorn on :8000) and the deployed dispatch-api.datawebify.com
// domain without a rebuild.

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);

function resolveApiBase() {
  // Allow an explicit override via ?api=https://... for demo flexibility,
  // e.g. when showing this against a client's own staging backend.
  const params = new URLSearchParams(window.location.search);
  const override = params.get("api");
  if (override) return override.replace(/\/$/, "");

  if (LOCAL_HOSTS.has(window.location.hostname)) {
    return "http://127.0.0.1:8000";
  }
  return "https://dispatch-api.datawebify.com";
}

export const API_BASE = resolveApiBase();

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  let res;
  try {
    res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (networkErr) {
    throw new ApiError(`Network error reaching ${url}: ${networkErr.message}`, 0);
  }

  let body = null;
  try {
    body = await res.json();
  } catch {
    // Non-JSON body; leave as null.
  }

  if (!res.ok) {
    const detail = body?.error || body?.detail || res.statusText;
    throw new ApiError(detail, res.status);
  }

  return body;
}

export async function fetchJobs(status = "", limit = 50) {
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  qs.set("limit", String(limit));
  return request(`/dispatch/jobs?${qs.toString()}`);
}

export async function fetchTechnicians(status = "") {
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request(`/dispatch/technicians${suffix}`);
}

export async function fetchMetrics(period = "monthly") {
  return request(`/metrics?period=${encodeURIComponent(period)}`);
}

export async function sendSimulatedMessage({ message, sessionId, customerPhone, customerEmail, customerName }) {
  return request(`/dispatch/webhook/web`, {
    method: "POST",
    body: JSON.stringify({
      message,
      session_id: sessionId || undefined,
      customer_phone: customerPhone || undefined,
      customer_email: customerEmail || undefined,
      customer_name: customerName || undefined,
    }),
  });
}

export { ApiError };
