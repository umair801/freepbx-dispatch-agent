// simulator.js — "Simulate a call" widget. Posts to /dispatch/webhook/web,
// the same adapter endpoint a client's existing dashboard would call, and
// renders the conversational reply plus any resulting dispatch record.

import { sendSimulatedMessage, ApiError } from "./api.js";
import { escapeHtml } from "./helpers.js";

let sessionId = null;

function appendMessage(html) {
  const thread = document.getElementById("simulator-thread");
  const wrapper = document.createElement("div");
  wrapper.innerHTML = html;
  thread.appendChild(wrapper.firstElementChild);
  thread.scrollTop = thread.scrollHeight;
}

function renderUserMessage(text) {
  appendMessage(`
    <div class="thread-msg thread-msg--user">
      <span class="thread-msg__label">Customer</span>
      ${escapeHtml(text)}
    </div>
  `);
}

function renderAgentMessage(text) {
  appendMessage(`
    <div class="thread-msg thread-msg--agent">
      <span class="thread-msg__label">Dispatch agent</span>
      ${escapeHtml(text)}
    </div>
  `);
}

function renderDispatchResult(dispatch) {
  if (!dispatch) return;
  const lines = [
    dispatch.job_id ? `Job: ${dispatch.job_id}` : null,
    dispatch.assigned_technician_name ? `Assigned to: ${dispatch.assigned_technician_name}` : "No technician assigned yet",
    dispatch.status ? `Status: ${dispatch.status}` : null,
  ].filter(Boolean);

  appendMessage(`
    <div class="thread-msg thread-msg--dispatch">
      <span class="thread-msg__label">Dispatch record</span>
      ${lines.map(escapeHtml).join("<br>")}
    </div>
  `);
}

function renderErrorMessage(text) {
  appendMessage(`
    <div class="thread-msg thread-msg--agent" style="border-color:var(--signal-red);">
      <span class="thread-msg__label">Error</span>
      ${escapeHtml(text)}
    </div>
  `);
}

export function initSimulator(onDispatchCreated) {
  const toggleBtn = document.getElementById("simulator-toggle");
  const panel = document.getElementById("simulator-panel");
  const form = document.getElementById("simulator-form");
  const submitBtn = document.getElementById("sim-submit");
  const submitLabel = document.getElementById("sim-submit-label");
  const messageInput = document.getElementById("sim-message");

  toggleBtn.addEventListener("click", () => {
    const isOpen = !panel.hidden;
    panel.hidden = isOpen;
    toggleBtn.setAttribute("aria-expanded", String(!isOpen));
    if (!isOpen) messageInput.focus();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const message = messageInput.value.trim();
    if (!message) return;

    const name = document.getElementById("sim-name").value.trim();
    const phone = document.getElementById("sim-phone").value.trim();

    renderUserMessage(message);
    messageInput.value = "";
    submitBtn.disabled = true;
    submitLabel.textContent = "Sending…";

    try {
      const result = await sendSimulatedMessage({
        message,
        sessionId,
        customerName: name || undefined,
        customerPhone: phone || undefined,
      });

      sessionId = result.session_id || sessionId;
      renderAgentMessage(result.reply || "(no reply text returned)");
      renderDispatchResult(result.dispatch);

      if (result.dispatch && onDispatchCreated) {
        onDispatchCreated();
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not reach the dispatch API.";
      renderErrorMessage(message);
    } finally {
      submitBtn.disabled = false;
      submitLabel.textContent = "Send";
    }
  });
}
