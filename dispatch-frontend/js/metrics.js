// metrics.js — header status strip, pulled from GET /metrics.

import { fetchMetrics, ApiError } from "./api.js";

export async function renderMetrics() {
  const totalEl = document.getElementById("metric-total");
  const assignedEl = document.getElementById("metric-assigned");
  const unassignedEl = document.getElementById("metric-unassigned");
  const rateEl = document.getElementById("metric-rate");

  try {
    const data = await fetchMetrics();
    totalEl.textContent = String(data.total_jobs ?? 0);
    assignedEl.textContent = String(data.assigned_count ?? 0);
    unassignedEl.textContent = String(data.unassigned_count ?? 0);
    rateEl.textContent = data.assignment_rate_pct != null ? `${data.assignment_rate_pct}%` : "—";
  } catch (err) {
    // Non-critical panel; fail quietly but leave a visible marker.
    [totalEl, assignedEl, unassignedEl, rateEl].forEach((el) => (el.textContent = "—"));
    if (err instanceof ApiError) {
      console.warn("metrics fetch failed:", err.message);
    }
  }
}
