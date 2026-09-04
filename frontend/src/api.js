/**
 * API client for the Durable Agent backend.
 * All methods return parsed JSON or throw structured errors.
 */

const BASE_URL = "http://localhost:8000";

/**
 * Generic fetch wrapper with error handling.
 */
async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });

  const data = await res.json().catch(() => null);

  if (!res.ok) {
    const err = new Error(data?.detail?.message || data?.message || `HTTP ${res.status}`);
    err.status = res.status;
    err.code = data?.detail?.code || data?.code || "UNKNOWN";
    err.detail = data?.detail || data;
    throw err;
  }

  return data;
}

/**
 * Create a new agent run.
 * @param {string} task - The task description
 * @param {number} ttlSeconds - TTL for approval window
 * @returns {Promise<{thread_id, status, task, plan, pending_action, time_remaining}>}
 */
export async function createRun(task, ttlSeconds = 3600) {
  return request("/agent/runs", {
    method: "POST",
    body: JSON.stringify({ task, ttl_seconds: ttlSeconds }),
  });
}

/**
 * Get full status of a run.
 * @param {string} threadId
 * @returns {Promise<RunStatusResponse>}
 */
export async function getRun(threadId) {
  return request(`/agent/runs/${threadId}`);
}

/**
 * List all runs with optional status filter.
 * @param {string} [status] - Filter by status
 * @returns {Promise<{runs: Array, count: number}>}
 */
export async function listRuns(status) {
  const query = status ? `?status=${status}` : "";
  return request(`/agent/runs${query}`);
}

/**
 * Approve a suspended run.
 * @param {string} threadId
 * @param {string} approver
 * @param {string} note
 * @returns {Promise<ApprovalResponse>}
 */
export async function approveRun(threadId, approver = "user", note = "") {
  return request(`/agent/runs/${threadId}/approve`, {
    method: "POST",
    body: JSON.stringify({ approver, note }),
  });
}

/**
 * Reject a suspended run.
 * @param {string} threadId
 * @param {string} approver
 * @param {string} reason
 * @returns {Promise<ApprovalResponse>}
 */
export async function rejectRun(threadId, approver = "user", reason = "") {
  return request(`/agent/runs/${threadId}/reject`, {
    method: "POST",
    body: JSON.stringify({ approver, reason }),
  });
}

/**
 * Health check.
 */
export async function healthCheck() {
  return request("/health");
}
