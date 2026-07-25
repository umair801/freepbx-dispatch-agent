// helpers.js — shared formatting and status-mapping utilities.

export const STATUS_COLOR_VAR = {
  pending: "--status-pending",
  assigned: "--status-assigned",
  en_route: "--status-en-route",
  in_progress: "--status-in-progress",
  completed: "--status-completed",
  cancelled: "--status-cancelled",
  unassigned: "--status-unassigned",
};

export const STATUS_LABEL = {
  pending: "Pending",
  assigned: "Assigned",
  en_route: "En Route",
  in_progress: "In Progress",
  completed: "Completed",
  cancelled: "Cancelled",
  unassigned: "Unassigned",
};

export function statusColor(status) {
  const varName = STATUS_COLOR_VAR[status] || "--text-faint";
  return `var(${varName})`;
}

export function statusLabel(status) {
  return STATUS_LABEL[status] || (status ? status.replace(/_/g, " ") : "Unknown");
}

export function isActiveStatus(status) {
  return status === "pending" || status === "unassigned" || status === "assigned";
}

export function timeAgo(isoString) {
  if (!isoString) return "—";
  const then = new Date(isoString).getTime();
  if (Number.isNaN(then)) return "—";
  const diffMs = Date.now() - then;
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

export function formatClock(date = new Date()) {
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function escapeHtml(str) {
  if (str == null) return "";
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function truncate(str, max = 42) {
  if (!str) return "";
  return str.length > max ? `${str.slice(0, max - 1)}…` : str;
}
