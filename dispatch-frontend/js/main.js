// main.js — entry point. Wires up all panels and runs the live-poll loop.

import { renderRoster } from "./roster.js";
import { renderBoard, initFilters } from "./board.js";
import { renderMetrics } from "./metrics.js";
import { initTimelineClose } from "./timeline.js";
import { initSimulator } from "./simulator.js";
import { formatClock } from "./helpers.js";

const POLL_INTERVAL_MS = 8000;

const syncDot = document.getElementById("sync-dot");
const syncLabel = document.getElementById("sync-label");

function setSyncState(state) {
  syncDot.classList.remove("is-live", "is-error");
  if (state === "live") {
    syncDot.classList.add("is-live");
    syncLabel.textContent = `synced ${formatClock()}`;
  } else if (state === "error") {
    syncDot.classList.add("is-error");
    syncLabel.textContent = "connection lost";
  } else {
    syncLabel.textContent = "syncing…";
  }
}

async function refreshAll() {
  setSyncState("pending");
  const results = await Promise.allSettled([renderRoster(), renderBoard(), renderMetrics()]);
  const failed = results.some((r) => r.status === "rejected");
  setSyncState(failed ? "error" : "live");
}

function startPolling() {
  refreshAll();
  setInterval(refreshAll, POLL_INTERVAL_MS);
}

function init() {
  initFilters();
  initTimelineClose();
  initSimulator(() => {
    // A simulated call created a dispatch, refresh the board/roster right away
    // instead of waiting for the next poll tick.
    renderBoard();
    renderRoster();
    renderMetrics();
  });
  startPolling();
}

document.addEventListener("DOMContentLoaded", init);
