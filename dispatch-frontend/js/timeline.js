// timeline.js — visual job lifecycle, derived from the job record returned
// by GET /dispatch/jobs. There's no dedicated timeline/events endpoint on
// the backend yet, so this reconstructs a lifecycle view from the fields
// that already exist (status, assigned_technician, urgency, notes,
// created_at) rather than requesting new API surface for a portfolio demo.

import { escapeHtml, statusLabel } from "./helpers.js";

const LIFECYCLE_ORDER = ["pending", "assigned", "en_route", "in_progress", "completed"];

function buildSteps(job) {
  const status = job.status || "pending";
  const currentIdx = status === "cancelled" || status === "unassigned"
    ? -1
    : LIFECYCLE_ORDER.indexOf(status);

  const steps = [
    {
      key: "intent_parsed",
      label: "Intent parsed",
      detail: `"${job.job_type || "service request"}" · ${job.customer_location || "location not captured"}`,
      done: true,
    },
    {
      key: "assigned",
      label: "Technician assigned",
      detail: job.assigned_technician_name
        ? `${job.assigned_technician_name} (ID ${job.assigned_technician_id || "—"})`
        : "Not yet assigned",
      done: Boolean(job.assigned_technician_id),
    },
    {
      key: "en_route",
      label: "En route",
      detail: status === "en_route" || currentIdx > LIFECYCLE_ORDER.indexOf("en_route") ? "Technician traveling to site" : "Pending",
      done: currentIdx > LIFECYCLE_ORDER.indexOf("en_route"),
    },
    {
      key: "in_progress",
      label: "In progress",
      detail: status === "in_progress" || currentIdx > LIFECYCLE_ORDER.indexOf("in_progress") ? "Job underway on site" : "Pending",
      done: currentIdx > LIFECYCLE_ORDER.indexOf("in_progress"),
    },
    {
      key: "completed",
      label: "Completed",
      detail: status === "completed" ? "Job closed out" : "Pending",
      done: status === "completed",
    },
  ];

  // Mark whichever step matches the job's live status as "current" so the
  // timeline always shows an active pulse at the job's actual position,
  // even when that step is also flagged done (e.g. status "assigned" means
  // the assignment step is both complete and the current stage).
  const currentKey = status === "cancelled" || status === "unassigned" ? null : status;
  return steps.map((s) => ({ ...s, current: s.key === currentKey }));
}

function renderStep(step, isLast) {
  // "current" wins visually over "done" so the job's live position is
  // always the one that pulses, even on a step that's also complete.
  const dotClass = step.current ? "is-current" : step.done ? "is-done" : "";
  return `
    <div class="tl-step">
      <div class="tl-step__rail">
        <span class="tl-step__dot ${dotClass}"></span>
        ${isLast ? "" : `<span class="tl-step__line"></span>`}
      </div>
      <div class="tl-step__body">
        <div class="tl-step__label">${escapeHtml(step.label)}</div>
        <div class="tl-step__detail">${escapeHtml(step.detail)}</div>
      </div>
    </div>
  `;
}

export function openTimeline(job) {
  const panel = document.getElementById("timeline-panel");
  const body = document.getElementById("timeline-body");
  const heading = document.getElementById("timeline-heading");

  heading.textContent = `Job Timeline — ${job.job_type || job.job_id || "Untitled"}`;

  const steps = buildSteps(job);
  const cancelled = job.status === "cancelled";
  const unassignedNote = job.status === "unassigned"
    ? `<div class="empty-state" style="text-align:left;padding:var(--sp-3) 0;">No matching technician was found at dispatch time. ${escapeHtml(job.notes || "")}</div>`
    : "";

  body.innerHTML = `
    ${cancelled ? `<div class="empty-state" style="text-align:left;padding:var(--sp-3) 0;">This job was cancelled.</div>` : ""}
    ${unassignedNote}
    <div class="tl-track">
      ${steps.map((s, i) => renderStep(s, i === steps.length - 1)).join("")}
    </div>
    <div style="margin-top:var(--sp-4); font-family:var(--font-mono); font-size:var(--fs-xs); color:var(--text-faint);">
      Job ID: ${escapeHtml(job.job_id || "—")} · Status: ${escapeHtml(statusLabel(job.status))} · Urgency: ${escapeHtml(job.urgency || "—")}
    </div>
  `;

  panel.hidden = false;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function initTimelineClose() {
  document.getElementById("timeline-close").addEventListener("click", () => {
    document.getElementById("timeline-panel").hidden = true;
  });
}
