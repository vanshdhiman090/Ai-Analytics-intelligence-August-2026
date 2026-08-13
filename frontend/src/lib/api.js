const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";

export class ApiError extends Error {
  constructor(message, { code = "request_failed", requestId = null, fields = [], status = 0 } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.requestId = requestId;
    this.fields = fields;
    this.status = status;
  }
}

function requestId() {
  return globalThis.crypto?.randomUUID?.() || `rca-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function headers(extra = {}) {
  return {
    ...extra,
    "X-Request-ID": extra["X-Request-ID"] || requestId(),
    ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
  };
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      cache: "no-store",
      headers: headers(options.headers || {}),
    });
  } catch {
    throw new ApiError("The investigation service cannot be reached. Check that the backend is running, then try again.", {
      code: "network_error",
    });
  }

  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (response.ok) return payload;

  if (payload?.error) {
    throw new ApiError(payload.error.message || "The RCA request could not be completed.", {
      code: payload.error.code,
      requestId: payload.error.request_id || response.headers.get("X-Request-ID"),
      fields: Array.isArray(payload.error.fields) ? payload.error.fields : [],
      status: response.status,
    });
  }

  throw new ApiError(typeof payload?.detail === "string" ? payload.detail : `Request failed (${response.status}).`, {
    code: "dataset_request_failed",
    requestId: response.headers.get("X-Request-ID"),
    status: response.status,
  });
}

export async function uploadDataset(file) {
  const body = new FormData();
  body.append("file", file);
  return request("/datasets", { method: "POST", body });
}

export async function deleteDataset(datasetId) {
  if (!datasetId) return;
  await request(`/datasets/${datasetId}`, { method: "DELETE" });
}

export async function runRcaInvestigation(payload) {
  return request("/v1/rca/investigations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
