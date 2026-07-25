// roster.js — technician roster panel.

import { fetchTechnicians, ApiError } from "./api.js";
import { escapeHtml } from "./helpers.js";

const TECH_STATUS_COLOR = {
  available: "var(--signal-green-bright)",
  on_job: "var(--signal-orange-bright)",
  off_shift: "var(--text-faint)",
  unavailable: "var(--signal-red)",
};

function techStatusColor(status) {
  return TECH_STATUS_COLOR[status] || "var(--text-faint)";
}

function renderSkills(skills) {
  if (!Array.isArray(skills) || skills.length === 0) return "";
  return skills
    .map((s) => `<span class="skill-tag">${escapeHtml(s)}</span>`)
    .join("");
}

function queueDepthPct(depth) {
  const d = Number(depth) || 0;
  // Assume a queue of 5+ reads as "full" for the bar visualization.
  return Math.min(100, Math.round((d / 5) * 100));
}

function renderTechCard(tech) {
  const status = tech.status || "unknown";
  const color = techStatusColor(status);
  const label = status.replace(/_/g, " ");
  const depth = tech.current_queue_depth ?? 0;

  return `
    <div class="tech-card" data-tech-id="${escapeHtml(tech.technician_id || "")}">
      <div class="tech-card__row">
        <span class="tech-card__name">${escapeHtml(tech.name || "Unnamed")}</span>
        <span class="tech-status">
          <span class="tech-status__dot" style="background:${color}"></span>
          ${escapeHtml(label)}
        </span>
      </div>
      <div class="tech-card__skills">${renderSkills(tech.skills)}</div>
      <div class="tech-card__queue">
        <span>Queue: ${escapeHtml(String(depth))}</span>
        <span class="queue-bar"><span class="queue-bar__fill" style="width:${queueDepthPct(depth)}%"></span></span>
      </div>
    </div>
  `;
}

export async function renderRoster() {
  const listEl = document.getElementById("roster-list");
  const countEl = document.getElementById("roster-count");

  try {
    const data = await fetchTechnicians();
    const technicians = data.technicians || [];

    countEl.textContent = String(technicians.length);

    if (technicians.length === 0) {
      listEl.innerHTML = `<div class="empty-state">No technicians registered yet.</div>`;
      return;
    }

    // Available technicians float to the top, so the panel reads as
    // "who can I dispatch right now" at a glance.
    const sorted = [...technicians].sort((a, b) => {
      const rank = { available: 0, on_job: 1, off_shift: 2, unavailable: 3 };
      return (rank[a.status] ?? 9) - (rank[b.status] ?? 9);
    });

    listEl.innerHTML = sorted.map(renderTechCard).join("");
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Could not reach the dispatch API.";
    listEl.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
    throw err;
  }
}
