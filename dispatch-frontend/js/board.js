// board.js — active dispatch board panel, status filtering, job-card rendering.

import { fetchJobs, ApiError } from "./api.js";
import { statusColor, statusLabel, isActiveStatus, timeAgo, escapeHtml, truncate } from "./helpers.js";
import { openTimeline } from "./timeline.js";

let currentFilter = "";
let latestJobs = [];

function renderJobCard(job) {
  const status = job.status || "unknown";
  const color = statusColor(status);
  const pulsing = isActiveStatus(status) ? "is-pulsing" : "";
  const urgency = (job.urgency || "").toLowerCase();
  const urgencyClass = urgency === "emergency" || urgency === "urgent" ? `job-card__urgency--${urgency}` : "";

  return `
    <div class="job-card" data-job-id="${escapeHtml(job.job_id || "")}" tabindex="0" role="button"
         aria-label="Open timeline for job ${escapeHtml(job.job_id || "")}">
      <span class="job-card__status ${pulsing}" style="background:${color}"></span>
      <div class="job-card__main">
        <span class="job-card__type">${escapeHtml(job.job_type || "Unspecified job")}</span>
        <span class="job-card__meta">${escapeHtml(truncate(job.customer_location, 46))} · ${escapeHtml(timeAgo(job.created_at))}</span>
      </div>
      <span class="job-card__tech">${job.assigned_technician_name ? escapeHtml(job.assigned_technician_name) : "Unassigned"}</span>
      ${job.urgency ? `<span class="job-card__urgency ${urgencyClass}">${escapeHtml(job.urgency)}</span>` : "<span></span>"}
    </div>
  `;
}

function attachCardHandlers(listEl) {
  listEl.querySelectorAll(".job-card").forEach((card) => {
    const jobId = card.dataset.jobId;
    const job = latestJobs.find((j) => j.job_id === jobId);
    if (!job) return;

    const open = () => openTimeline(job);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
  });
}

export async function renderBoard() {
  const listEl = document.getElementById("job-list");

  try {
    const data = await fetchJobs(currentFilter, 50);
    latestJobs = data.jobs || [];

    if (latestJobs.length === 0) {
      listEl.innerHTML = `<div class="empty-state">No jobs${currentFilter ? ` with status "${escapeHtml(statusLabel(currentFilter))}"` : ""} yet. Try the simulator below to create one.</div>`;
      return;
    }

    listEl.innerHTML = latestJobs.map(renderJobCard).join("");
    attachCardHandlers(listEl);
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Could not reach the dispatch API.";
    listEl.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
    throw err;
  }
}

export function initFilters(onChange) {
  const container = document.getElementById("status-filters");
  container.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;

    container.querySelectorAll(".chip").forEach((c) => c.classList.remove("chip--active"));
    btn.classList.add("chip--active");

    currentFilter = btn.dataset.status || "";
    renderBoard();
    if (onChange) onChange(currentFilter);
  });
}

export function getLatestJobs() {
  return latestJobs;
}
